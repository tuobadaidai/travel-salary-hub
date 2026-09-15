from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.services import stats

router = APIRouter(prefix="/api/v1", tags=["dashboard"])


@router.get("/meta")
def get_meta(db: Session = Depends(get_db)):
    return stats.meta_full(db)


@router.get("/stats/quantiles")
def get_quantiles(
    group_by: str = Query("job_family", pattern="^(city|country|company_type|job_family)$"),
    city: str | None = None,
    country: str | None = None,
    company_type: str | None = None,
    job_family_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
):
    return stats.quantiles_by_group(
        db, group_by, city=city, company_type=company_type,
        job_family_id=job_family_id, date_from=date_from, date_to=date_to, country=country,
    )


@router.get("/stats/trend")
def get_trend(
    city: str | None = None,
    country: str | None = None,
    company_type: str | None = None,
    job_family_id: int | None = None,
    db: Session = Depends(get_db),
):
    return stats.trend_by_month(
        db, city=city, company_type=company_type, job_family_id=job_family_id, country=country,
    )
