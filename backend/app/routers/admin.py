from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import CollectRun, IngestSchedule, SalaryRecord

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/collect-runs")
def list_runs(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.query(CollectRun).order_by(CollectRun.id.desc()).limit(limit).all()
    return [
        {
            "id": r.id, "source_name": r.source_name, "status": r.status,
            "started_at": r.started_at, "finished_at": r.finished_at,
            "items_fetched": r.items_fetched, "items_new": r.items_new,
            "items_rejected": r.items_rejected, "error_message": r.error_message,
        }
        for r in rows
    ]


@router.get("/schedules")
def list_schedules(db: Session = Depends(get_db)):
    rows = db.query(IngestSchedule).order_by(IngestSchedule.source_name).all()
    return [
        {
            "source_name": r.source_name, "cadence": r.cadence, "enabled": bool(r.enabled),
            "last_success_at": r.last_success_at, "next_due_at": r.next_due_at,
        }
        for r in rows
    ]


@router.post("/import/payroll")
async def upload_payroll(file: UploadFile):
    """上传 DIDA 薪酬表 xlsx，匿名化导入 dida_payroll（幂等，重复行跳过）。"""
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(400, "仅支持 .xlsx 文件")
    import tempfile
    from pathlib import Path

    from pipeline.import_dida_payroll import ensure_table, import_xlsx

    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(400, "文件超过 20MB 限制")
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        ensure_table()
        added, skipped = import_xlsx(tmp_path)
    except Exception as e:
        raise HTTPException(400, f"导入失败：{e}") from e
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return {"added": added, "skipped": skipped, "filename": file.filename}


@router.post("/upload-report")
async def upload_report(file: UploadFile, source_label: str = "Michael Page 2026",
                        db: Session = Depends(get_db)):
    """上传第三方薪酬报告 PDF（如 Michael Page），解析后入库为"全国 base 参考线"。

    方案 B：source 以 report: 前缀标记，benchmark 矩阵默认不混入差距计算，
    单独以"全国参考线"展示。
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "仅支持 .pdf 文件")
    import tempfile
    from datetime import date
    from pathlib import Path

    from pipeline.parse_report import parse_pdf, dedup_hash

    data = await file.read()
    if len(data) > 30 * 1024 * 1024:
        raise HTTPException(400, "文件超过 30MB 限制")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        rows = parse_pdf(tmp_path)
    except Exception as e:
        raise HTTPException(400, f"PDF 解析失败：{e}") from e
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if not rows:
        raise HTTPException(400, "未解析到任何薪酬行，请确认是 Michael Page 格式报告")

    today = date.today().isoformat()
    company_name = "行业基准（" + source_label.split()[0] + "）"
    source_tag = f"report:{source_label}"
    added = 0
    skipped = 0
    for r in rows:
        low = r["low_k"] * 1000
        high = r["high_k"] * 1000
        avg = (low + high) / 2
        h = dedup_hash(r["position"], "全国", company_name, low, high)
        if db.query(SalaryRecord).filter(SalaryRecord.dedup_hash == h).first():
            skipped += 1
            continue
        rec = SalaryRecord(
            position=r["position"],
            position_norm=r["position"],
            company_name=company_name,
            company_type="other",
            city="全国",
            country="CN",
            currency="CNY",
            salary_range=f'{r["low_k"]} - {r["high_k"]} 千',
            months=12,
            annual_salary_low=low,
            annual_salary_high=high,
            annual_salary_avg=avg,
            annual_salary_avg_base=avg,
            level=r["level"],
            source=source_tag,
            collect_date=today,
            dedup_hash=h,
            sample_count=1,
        )
        db.add(rec)
        added += 1
    db.commit()

    # 记录采集批次
    run = CollectRun(
        source_name=f"薪酬报告上传：{source_label}",
        status="success",
        items_fetched=len(rows),
        items_new=added,
        items_updated=0,
        items_rejected=skipped,
        params_json=f'{{"file":"{file.filename}"}}',
    )
    db.add(run)
    db.commit()

    return {"added": added, "skipped": skipped, "parsed": len(rows), "filename": file.filename,
            "source_tag": source_tag}
