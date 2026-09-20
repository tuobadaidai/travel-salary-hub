"""一次性清洗存量海外数据：用 data/raw/overseas_snippet 审计 JSONL 重抽重算。

对 source='overseas_snippet' 的记录：
- 删除旧记录（按 position_norm+city 匹配）
- 用修复后的 extract_amounts/aggregate_amounts 重新聚合入新记录

用法：python3 -m backend.pipeline.clean_overseas
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from pipeline.collectors.scraper import infer_level  # noqa: E402
from pipeline.cleaning.normalize import (  # noqa: E402
    classify_job_family, dedup_hash, normalize_city, normalize_position,
)
from pipeline.ingest import DEFAULT_FX, init_db  # noqa: E402
from pipeline.run_overseas import aggregate_amounts, extract_amounts  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import CollectRun, JobFamily, SalaryRecord  # noqa: E402

RAW_DIR = PROJECT_ROOT / "data" / "raw" / "overseas_snippet"

# 与 run_overseas.OVERSEAS_CITIES 一致：清洗时需要城市英文名做非本币城市校验
CITY_EN = {
    "香港": "Hong Kong", "新加坡": "Singapore", "曼谷": "Bangkok Thailand",
    "吉隆坡": "Kuala Lumpur Malaysia", "雅加达": "Jakarta Indonesia",
    "东京": "Tokyo Japan", "首尔": "Seoul Korea", "马尼拉": "Manila Philippines",
    "胡志明市": "Ho Chi Minh Vietnam", "马德里": "Madrid Spain",
    "迪拜": "Dubai UAE", "伦敦": "London UK",
}


def main():
    init_db()
    db = SessionLocal()
    family_map = {jf.code: jf.id for jf in db.query(JobFamily).all()}

    # 汇总全部 raw 审计文件：city/position → candidates
    files = sorted(RAW_DIR.glob("*.jsonl"))
    if not files:
        print("无 raw 审计文件")
        return
    hits = []
    for f in files:
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            hits.append(d)

    run = CollectRun(source_name="overseas_clean", status="running",
                     params_json=json.dumps({"raw_files": [f.name for f in files]}))
    db.add(run)
    db.flush()

    # 删除全部旧海外记录
    old = db.query(SalaryRecord).filter_by(source="overseas_snippet").all()
    old_keys = {(r.position_norm, r.city) for r in old}
    for r in old:
        db.delete(r)
    db.flush()
    print(f"deleted {len(old)} old overseas records")

    today = datetime.now(timezone.utc).date().isoformat()
    added = skipped = miss = 0
    for d in hits:
        city_cn, pos_cn = d["city"], d["position"]
        candidates = []
        for h in d.get("hits", []):
            for amt in extract_amounts(h.get("snippet", ""), city_cn, CITY_EN.get(city_cn, "")):
                amt["url"] = h.get("url", "")
                candidates.append(amt)
        if not candidates:
            miss += 1
            continue
        agg = aggregate_amounts(candidates, city_cn)
        if agg is None:
            miss += 1
            continue
        cur, kind = agg["currency"], agg["kind"]
        if kind == "annual":
            monthly_low, monthly_high = agg["low"] / 12, agg["high"] / 12
        else:
            monthly_low, monthly_high = agg["low"], agg["high"]
        if monthly_low * DEFAULT_FX.get(cur, 1.0) > 200000:
            print(f"  OUTLIER {city_cn}/{pos_cn}: {cur} {monthly_low:.0f}/mo")
            miss += 1
            continue
        annual_low, annual_high = monthly_low * 12, monthly_high * 12
        annual_avg = (annual_low + annual_high) / 2
        city_norm, country = normalize_city(
            {"香港": "香港", "新加坡": "新加坡", "曼谷": "曼谷", "吉隆坡": "吉隆坡",
             "雅加达": "雅加达", "东京": "东京", "首尔": "首尔", "马尼拉": "马尼拉",
             "胡志明市": "胡志明市", "马德里": "马德里", "迪拜": "迪拜", "伦敦": "伦敦"
             }.get(city_cn, city_cn))
        pos_norm = normalize_position(pos_cn)
        h = dedup_hash("overseas", pos_norm, city_norm, round(monthly_low),
                       round(monthly_high), today[:7])
        if db.query(SalaryRecord).filter_by(dedup_hash=h).first():
            skipped += 1
            continue
        db.add(SalaryRecord(
            collect_run_id=run.id,
            position=pos_cn,
            company_name="海外聚合摘要",
            company_type="aggregator",
            salary_range=f"{monthly_low:,.0f}-{monthly_high:,.0f} {cur}/月",
            salary_monthly_low=monthly_low,
            salary_monthly_high=monthly_high,
            months=12,
            annual_salary_low=annual_low,
            annual_salary_high=annual_high,
            annual_salary_avg=annual_avg,
            location=city_norm,
            source="overseas_snippet",
            source_url=candidates[0]["url"],
            collect_date=today,
            position_norm=pos_norm,
            city=city_norm,
            country=country,
            currency=cur,
            annual_salary_avg_base=annual_avg * DEFAULT_FX.get(cur, 7.0),
            level=infer_level(pos_cn),
            sample_count=agg["n"],
            extra_json=json.dumps({"basis": "search_snippet", "confidence": "low",
                                   "basis_kind": kind,
                                   "mixed_dropped": agg["mixed_dropped"],
                                   "reprocessed_from_raw": True},
                                  ensure_ascii=False),
            job_family_id=family_map.get(classify_job_family(pos_cn)),
            dedup_hash=h,
        ))
        added += 1
        print(f"  + {city_cn}/{pos_cn}: {cur} {monthly_low:,.0f}-{monthly_high:,.0f}/mo ({agg['n']} src)")

    run.items_fetched = added + skipped + miss
    run.items_new = added
    run.status = "success"
    run.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.commit()
    print(f"done: +{added} new, {skipped} dup, {miss} miss → run #{run.id}")


if __name__ == "__main__":
    main()
