"""分位数与趋势计算核心。SQL 只做过滤/分组，numpy 算分位数。"""

import numpy as np
from sqlalchemy.orm import Session

from app.models import Company, JobFamily, SalaryRecord

# 跨国对比统一用 CNY 折算口径
METRIC = SalaryRecord.annual_salary_avg_base
GROUP_COLS = {
    "city": SalaryRecord.city,
    "country": SalaryRecord.country,
    "company_type": SalaryRecord.company_type,
    "job_family": SalaryRecord.job_family_id,
}


def _quantiles(values: list[float]) -> dict:
    arr = np.array(values, dtype=float)
    p25, p50, p75, p90 = np.quantile(arr, [0.25, 0.5, 0.75, 0.9])
    return {
        "count": len(values),
        "p25": round(float(p25)),
        "p50": round(float(p50)),
        "p75": round(float(p75)),
        "p90": round(float(p90)),
        "reliable": len(values) >= 5,
    }


def _filtered(db: Session, city: str | None, company_type: str | None,
              job_family_id: int | None, date_from: str | None, date_to: str | None,
              country: str | None):
    q = db.query(
        SalaryRecord.city,
        SalaryRecord.country,
        SalaryRecord.company_type,
        SalaryRecord.job_family_id,
        SalaryRecord.collect_date,
        METRIC,
    ).filter(METRIC.isnot(None))
    if city:
        q = q.filter(SalaryRecord.city.in_(city.split(",")))
    if country:
        q = q.filter(SalaryRecord.country.in_(country.split(",")))
    if company_type:
        q = q.filter(SalaryRecord.company_type == company_type)
    if job_family_id:
        q = q.filter(SalaryRecord.job_family_id == job_family_id)
    if date_from:
        q = q.filter(SalaryRecord.collect_date >= date_from)
    if date_to:
        q = q.filter(SalaryRecord.collect_date <= date_to)
    return q.all()


def quantiles_by_group(db: Session, group_by: str, city: str | None = None,
                       company_type: str | None = None, job_family_id: int | None = None,
                       date_from: str | None = None, date_to: str | None = None,
                       country: str | None = None) -> list[dict]:
    rows = _filtered(db, city, company_type, job_family_id, date_from, date_to, country)
    gi = {"city": 0, "country": 1, "company_type": 2, "job_family": 3}[group_by]
    groups: dict[str, list[float]] = {}
    for r in rows:
        key = str(r[gi]) if r[gi] is not None else "未分类"
        groups.setdefault(key, []).append(float(r[5]))
    out = [{"group_key": k, **_quantiles(v)} for k, v in groups.items()]
    out.sort(key=lambda x: x["group_key"])
    return out


def trend_by_month(db: Session, city: str | None = None, company_type: str | None = None,
                   job_family_id: int | None = None, country: str | None = None) -> list[dict]:
    rows = _filtered(db, city, company_type, job_family_id, None, None, country)
    groups: dict[str, list[float]] = {}
    for r in rows:
        groups.setdefault(str(r[4])[:7], []).append(float(r[5]))
    return [{"month": m, **_quantiles(groups[m])} for m in sorted(groups)]


def meta_full(db: Session) -> dict:
    cities = sorted({r[0] for r in db.query(SalaryRecord.city).distinct() if r[0]})
    countries = sorted({r[0] for r in db.query(SalaryRecord.country).distinct() if r[0]})
    families = [
        {"id": jf.id, "code": jf.code, "name": jf.name}
        for jf in db.query(JobFamily).order_by(JobFamily.sort_order).all()
    ]
    latest = db.query(SalaryRecord.collect_date).order_by(SalaryRecord.collect_date.desc()).first()
    return {
        "cities": cities,
        "countries": countries,
        "job_families": families,
        "company_types": ["OTA", "B2B", "traditional_agency", "other"],
        "latest_collect_date": latest[0] if latest else None,
        "total_records": db.query(SalaryRecord).count(),
    }
