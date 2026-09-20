from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import CollectRun, IngestSchedule

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
