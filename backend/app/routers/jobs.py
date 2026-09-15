from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import SalaryRecord

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get("")
def list_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    city: str | None = None,
    company_type: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(SalaryRecord)
    if city:
        q = q.filter(SalaryRecord.city.in_(city.split(",")))
    if company_type:
        q = q.filter(SalaryRecord.company_type == company_type)
    total = q.count()
    rows = q.order_by(SalaryRecord.collect_date.desc(), SalaryRecord.id.desc()) \
        .offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total, "page": page, "page_size": page_size,
        "items": [_job_dict(r) for r in rows],
    }


@router.get("/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    r = db.query(SalaryRecord).filter(SalaryRecord.id == job_id).first()
    if not r:
        raise HTTPException(404, "record not found")
    return _job_dict(r)


def _job_dict(r: SalaryRecord) -> dict:
    return {
        "id": r.id, "position": r.position, "company_name": r.company_name,
        "company_type": r.company_type, "salary_range": r.salary_range,
        "salary_monthly_low": r.salary_monthly_low, "salary_monthly_high": r.salary_monthly_high,
        "months": r.months, "annual_salary_avg": r.annual_salary_avg,
        "annual_salary_avg_base": r.annual_salary_avg_base,
        "location": r.location, "city": r.city, "country": r.country, "currency": r.currency,
        "experience": r.experience, "education": r.education,
        "source": r.source, "collect_date": r.collect_date,
    }
