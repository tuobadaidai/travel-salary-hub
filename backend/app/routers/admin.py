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


# ---------- 触发采集任务 ----------

# 已注册的采集任务：name → 可调用对象（无参数，阻塞运行）
_AVAILABLE_JOBS: dict[str, dict] = {
    "jobui_companies": {
        "label": "jobui 公司薪酬子页",
        "desc": "采集 6 家竞争公司×岗位薪酬子页（携程/美团/同程/众信/马蜂窝/阿里）",
    },
    "jobui_batch": {
        "label": "jobui 城市聚合",
        "desc": "按城市×岗位抓 jobui 聚合页",
    },
    "levels_fyi": {
        "label": "Levels.fyi（中国区）",
        "desc": "通过 Apify 抓字节/阿里/腾讯/美团薪酬分位（需配置 APIFY_TOKEN）",
    },
}


def _run_jobui_companies():
    """在子进程/线程里跑，避免 import 时连数据库。"""
    import subprocess
    import sys
    from pathlib import Path
    project_root = Path(__file__).resolve().parents[3]
    subprocess.Popen(
        [sys.executable, "-m", "pipeline.run_companies"],
        cwd=str(project_root / "backend"),
        stdout=open(project_root / "data" / "logs" / "jobui_companies.log", "a"),
        stderr=subprocess.STDOUT,
    )


@router.get("/jobs")
def list_jobs():
    """列出可触发的采集任务。"""
    return [{"name": k, **v} for k, v in _AVAILABLE_JOBS.items()]


@router.post("/trigger/{job_name}")
def trigger_job(job_name: str):
    """触发一个采集任务（后台异步跑，立即返回）。"""
    if job_name not in _AVAILABLE_JOBS:
        raise HTTPException(404, f"unknown job: {job_name}. available: {list(_AVAILABLE_JOBS)}")
    import threading
    from pathlib import Path
    log_dir = Path(__file__).resolve().parents[3] / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    if job_name == "jobui_companies":
        threading.Thread(target=_run_jobui_companies, daemon=True).start()
        return {"status": "started", "job": job_name, "note": "后台运行中，刷新批次记录看结果"}
    if job_name == "levels_fyi":
        from app.config import settings
        if not settings.apify_token:
            raise HTTPException(400, "未配置 APIFY_TOKEN。请先在 .env 或环境变量设置后再触发。")
        def _run_lf():
            import subprocess
            import sys
            project_root = Path(__file__).resolve().parents[3]
            subprocess.Popen(
                [sys.executable, "-m", "pipeline.run_levels_fyi"],
                cwd=str(project_root / "backend"),
                stdout=open(log_dir / "levels_fyi.log", "a"),
                stderr=subprocess.STDOUT,
            )
        threading.Thread(target=_run_lf, daemon=True).start()
        return {"status": "started", "job": job_name, "note": "Apify 任务已触发，通常 1-3 分钟完成"}
    raise HTTPException(400, f"job {job_name} trigger not wired yet")
