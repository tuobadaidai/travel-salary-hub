"""财报/统计局薪酬数据导入器：读取人工维护的 CSV（巨潮/披露易/统计局下载）导入 reports 表。

CSV 口径：company_name, fiscal_year, report_type(annual_report|gov_statistics),
avg_salary, employees, total_comp, source, source_url, confidence
"""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from app.db import SessionLocal
from app.models import CollectRun, IngestSchedule, Report
from pipeline.ingest import match_company


def import_reports_csv(path: Path) -> tuple[int, int]:
    db = SessionLocal()
    run = CollectRun(source_name="reports_csv", params_json=json.dumps({"file": str(path)}, ensure_ascii=False))
    db.add(run)
    db.flush()
    added = skipped = 0
    try:
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                company_id = match_company(db, row["company_name"])
                if not company_id:
                    skipped += 1
                    continue
                key = (company_id, int(row["fiscal_year"]), row["report_type"])
                exists = db.query(Report).filter_by(
                    company_id=key[0], fiscal_year=key[1], report_type=key[2]).first()
                if exists:
                    skipped += 1
                    continue
                db.add(Report(
                    company_id=company_id,
                    fiscal_year=key[1],
                    report_type=row["report_type"],
                    avg_salary=float(row["avg_salary"]) if row.get("avg_salary") else None,
                    employees=int(row["employees"]) if row.get("employees") else None,
                    total_comp=float(row["total_comp"]) if row.get("total_comp") else None,
                    source=row.get("source"),
                    source_url=row.get("source_url"),
                    confidence=row.get("confidence") or "medium",
                ))
                added += 1
        run.items_fetched = added + skipped
        run.items_new = added
        run.status = "success"
        run.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _touch_schedule(db, run)
        db.commit()
        return added, skipped
    except Exception as e:
        db.rollback()
        run.status = "failed"
        run.error_message = str(e)
        db.commit()
        raise
    finally:
        db.close()


def _touch_schedule(db, run: CollectRun):
    s = db.query(IngestSchedule).filter_by(source_name=run.source_name).first()
    if not s:
        s = IngestSchedule(source_name=run.source_name, cadence="yearly")
        db.add(s)
        db.flush()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    s.last_run_at = now
    s.last_success_at = now


if __name__ == "__main__":
    import sys
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/seed/reports_seed.csv")
    if not path.exists():
        print(f"no file: {path}")
        raise SystemExit(0)
    a, s = import_reports_csv(path)
    print(f"reports: +{a}, skipped {s}")
