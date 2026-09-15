from fastapi import APIRouter, Depends
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
