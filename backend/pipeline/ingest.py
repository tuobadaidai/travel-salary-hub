"""通用入库逻辑：种子数据、历史 CSV、幂等导入。"""

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    CollectRun,
    Company,
    FxRate,
    IngestSchedule,
    JobFamily,
    Report,
    SalaryRecord,
)
from pipeline.cleaning.normalize import (  # noqa: E402
    dedup_hash,
    detect_currency,
    monthly_to_annual,
    normalize_city,
    normalize_education,
    normalize_experience,
    normalize_position,
    parse_months,
)

# 常用币种 → CNY 参考汇率（写死为种子值，后续可由 fx_rates 表更新覆盖）
DEFAULT_FX = {
    "CNY": 1.0, "USD": 7.2, "EUR": 7.8, "GBP": 9.1,
    "SGD": 5.4, "AED": 1.96, "INR": 0.086, "HKD": 0.92,
}


def init_db():
    Base.metadata.create_all(engine)


def seed_fx_rates(db):
    today = datetime.now(timezone.utc).date().isoformat()
    for cur, rate in DEFAULT_FX.items():
        exists = db.query(FxRate).filter_by(currency=cur, rate_date=today).first()
        if not exists:
            db.add(FxRate(currency=cur, rate_date=today, rate_to_cny=rate, source="seed"))


def seed_job_families(db, path: Path):
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not db.query(JobFamily).filter_by(code=row["code"]).first():
                db.add(JobFamily(code=row["code"], name=row["name"], sort_order=int(row["sort_order"])))


def seed_companies(db, path: Path):
    """公司种子 + 上市公司的员工数快照进 reports。"""
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = row["name"].strip()
            company = db.query(Company).filter_by(name=name).first()
            if not company:
                company = Company(name=name)
                db.add(company)
            company.short_name = row["short_name"]
            company.company_type = row["company_type"]
            company.aliases = row["aliases"]
            company.stock_code = row["stock_code"] or None
            company.is_listed = int(row["is_listed"] or 0)
            company.hq_country = row.get("hq_country", "CN")
            db.flush()
            emp = row.get("employees_2024", "").strip()
            if emp and row["company_type"] in ("OTA", "traditional_agency"):
                exists = db.query(Report).filter_by(
                    company_id=company.id, fiscal_year=2024, report_type="annual_report").first()
                if not exists:
                    db.add(Report(
                        company_id=company.id, fiscal_year=2024, report_type="annual_report",
                        employees=int(emp), source=f"竞品调研报告({row['source_tier']}级)",
                        confidence="low",
                    ))


def match_company(db, company_name: str) -> int | None:
    """按 name/short_name/aliases 匹配公司，未命中返回 None。"""
    t = company_name.strip()
    for c in db.query(Company).all():
        candidates = [c.name, c.short_name or ""] + (c.aliases or "").split("/")
        if any(t == x.strip() or (x.strip() and x.strip() in t) for x in candidates if x):
            return c.id
    return None


def backfill_job_families(db) -> int:
    """为未分类的 salary_records 按岗位名关键词回填 job_family_id。"""
    fams = {jf.code: jf.id for jf in db.query(JobFamily).all()}
    from pipeline.cleaning.normalize import classify_job_family
    n = 0
    for r in db.query(SalaryRecord).filter(SalaryRecord.job_family_id.is_(None)).all():
        code = classify_job_family(r.position)
        if code and code in fams:
            r.job_family_id = fams[code]
            n += 1
    return n


def import_history_csv(db, path: Path, source_label: str = "manual_csv") -> tuple[int, int]:
    """导入历史 JD CSV（76 行口径），幂等：dedup_hash 冲突跳过。返回 (新增, 跳过)。"""
    run = CollectRun(source_name=source_label, params_json=json.dumps({"file": str(path)}, ensure_ascii=False))
    db.add(run)
    db.flush()

    added = skipped = 0
    seen_in_batch: set[str] = set()
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            monthly_low = float(row["salary_monthly_low"]) if row.get("salary_monthly_low") else None
            monthly_high = float(row["salary_monthly_high"]) if row.get("salary_monthly_high") else None
            months = int(row.get("months") or 12)
            annual_low = annual_high = annual_avg = None
            if monthly_low and monthly_high:
                annual_low, annual_high = monthly_to_annual(monthly_low, monthly_high, months)
                annual_avg = (annual_low + annual_high) / 2

            city, country = normalize_city(row.get("location"))
            currency = detect_currency(row.get("salary_range"), country)
            pos_norm = normalize_position(row["position"])
            exp_min, exp_max = normalize_experience(row.get("experience"))
            h = dedup_hash(row["company_name"], pos_norm, city, monthly_low, monthly_high,
                           row["collect_date"][:7])
            if h in seen_in_batch or db.query(SalaryRecord).filter_by(dedup_hash=h).first():
                skipped += 1
                continue
            seen_in_batch.add(h)

            db.add(SalaryRecord(
                collect_run_id=run.id,
                company_id=match_company(db, row["company_name"]),
                position=row["position"],
                company_name=row["company_name"],
                company_type=row.get("company_type"),
                salary_range=row.get("salary_range"),
                salary_monthly_low=monthly_low,
                salary_monthly_high=monthly_high,
                months=months,
                annual_salary_low=annual_low,
                annual_salary_high=annual_high,
                annual_salary_avg=annual_avg,
                location=row.get("location"),
                experience=row.get("experience"),
                education=row.get("education"),
                source=row.get("source") or source_label,
                collect_date=row["collect_date"],
                position_norm=pos_norm,
                city=city,
                country=country,
                currency=currency,
                annual_salary_avg_base=annual_avg * DEFAULT_FX.get(currency, 1.0) if annual_avg else None,
                experience_min_yrs=exp_min,
                experience_max_yrs=exp_max,
                education_level=normalize_education(row.get("education")),
                dedup_hash=h,
            ))
            added += 1
    run.items_fetched = added + skipped
    run.items_new = added
    run.status = "success"
    run.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return added, skipped


def main():
    init_db()
    db = SessionLocal()
    try:
        seed = PROJECT_ROOT / "data" / "seed"
        seed_fx_rates(db)
        seed_job_families(db, seed / "job_families_seed.csv")
        seed_companies(db, seed / "companies_seed.csv")
        db.commit()
        print("seed ok")

        history = PROJECT_ROOT / "data" / "seed" / "history_jd.csv"
        if history.exists():
            added, skipped = import_history_csv(db, history)
            n = backfill_job_families(db)
            db.commit()
            print(f"history csv: +{added}, skipped {skipped}, families backfilled: {n}")
        else:
            print(f"history csv not found at {history}, skip")
    finally:
        db.close()


if __name__ == "__main__":
    main()
