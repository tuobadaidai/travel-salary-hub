from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Company, Report, SalaryRecord
from app.services.stats import _quantiles

router = APIRouter(prefix="/api/v1/companies", tags=["companies"])


@router.get("")
def list_companies(company_type: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Company).filter(Company.status == 1)
    if company_type:
        q = q.filter(Company.company_type == company_type)
    rows = q.order_by(Company.company_type, Company.name).all()
    latest = {r.company_id: r for r in db.query(Report).filter(
        Report.report_type == "annual_report").order_by(Report.fiscal_year).all()}
    out = []
    for c in rows:
        rec_count = db.query(SalaryRecord).filter(SalaryRecord.company_id == c.id).count()
        rpt = latest.get(c.id)
        out.append({
            "id": c.id, "name": c.name, "short_name": c.short_name,
            "company_type": c.company_type, "hq_country": c.hq_country,
            "stock_code": c.stock_code, "is_listed": bool(c.is_listed),
            "record_count": rec_count,
            "report": ({
                "fiscal_year": rpt.fiscal_year, "employees": rpt.employees,
                "total_comp": rpt.total_comp, "revenue": rpt.revenue,
                "avg_salary": rpt.avg_salary, "confidence": rpt.confidence,
            } if rpt else None),
        })
    return out


@router.get("/{company_id}")
def company_detail(company_id: int, db: Session = Depends(get_db)):
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c:
        raise HTTPException(404, "company not found")
    reports = db.query(Report).filter(Report.company_id == company_id).order_by(Report.fiscal_year).all()
    recs = db.query(SalaryRecord.annual_salary_avg_base).filter(
        SalaryRecord.company_id == company_id,
        SalaryRecord.annual_salary_avg_base.isnot(None),
    ).all()
    jd_summary = _quantiles([float(r[0]) for r in recs]) if recs else None
    return {
        "id": c.id, "name": c.name, "short_name": c.short_name,
        "company_type": c.company_type, "hq_country": c.hq_country,
        "stock_code": c.stock_code, "is_listed": bool(c.is_listed),
        "reports": [
            {
                "fiscal_year": r.fiscal_year, "report_type": r.report_type,
                "avg_salary": r.avg_salary, "employees": r.employees,
                "total_comp": r.total_comp, "revenue": r.revenue,
                "source": r.source, "confidence": r.confidence,
            }
            for r in reports
        ],
        "jd_summary": jd_summary,
    }
