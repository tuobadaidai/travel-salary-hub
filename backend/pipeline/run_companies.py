"""竞争公司维度采集：jobui 公司×岗位薪酬子页 → salary_records。

用法：
    python3 -m backend.pipeline.run_companies                 # 全部公司×全部子页
    python3 -m backend.pipeline.run_companies --company 携程  # 指定公司

数据源：/company/{id}/salary/ 主页枚举岗位子页链接 → /salary/j/{slug}/ 解析。
公司 ID 2026-09-16 经页面标题逐一验证（site: 搜索噪声大，勿信）：
途牛两家主页均无 salary 子页，跳过。
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from pipeline.collectors.scraper import (  # noqa: E402
    fetch_scrapling, infer_level, parse_jobui_company_subpage, raw_dump,
)
from pipeline.cleaning.normalize import (  # noqa: E402
    classify_job_family, dedup_hash, normalize_city, normalize_position,
)
from pipeline.ingest import init_db, match_company  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import CollectRun, JobFamily, SalaryRecord  # noqa: E402

# 19 家竞争公司中 jobui 有薪酬子页的（ID 已验证）
COMPANIES = {
    "携程": 12078481,       # 携程计算机技术（上海）有限公司
    "美团": 12214432,       # 北京三快在线科技有限公司
    "同程旅行": 10675361,   # 同程网络科技股份有限公司
    "众信旅游": 13271995,   # 众信旅游集团股份有限公司
    "马蜂窝": 9186183,      # 北京蚂蜂窝网络科技有限公司
    "阿里巴巴": 1143597,    # 飞猪母公司
}

RATE_LIMIT_S = 4.0

# jobui 子页 slug 是截断拼音（bp/fa/oc），解析出的"岗位名"可能是碎片；
# 纯字母碎片与实习/蓝领岗无对标价值，跳过
NOISE_POSITION_RE = re.compile(r"^[a-z]{1,4}$|实习|学徒|水产|理货|分拣|打包|配送|防损|夜班|店员|net开发$|产品实习")


def is_noise_position(pos: str) -> bool:
    return bool(NOISE_POSITION_RE.match(pos))


def discover_subpages(cid: int) -> list[str]:
    """主页枚举岗位子页 slug。子页 slug 是截断拼音，无法猜测，只能枚举。"""
    html = fetch_scrapling(f"https://www.jobui.com/company/{cid}/salary/")
    if not html:
        return []
    return sorted(set(re.findall(rf"/company/{cid}/salary/j/([a-z]+)/", html)))


def collect_company(db, run_id: int, family_map: dict, name: str, cid: int) -> tuple[int, int, int]:
    """采集一家公司的全部薪酬子页。返回 (新增, 跳过, 失败)。"""
    company_id = match_company(db, name)
    slugs = discover_subpages(cid)
    print(f"{name}({cid}): {len(slugs)} 子页")
    added = skipped = miss = 0
    for slug in slugs:
        url = f"https://www.jobui.com/company/{cid}/salary/j/{slug}/"
        html = fetch_scrapling(url)
        time.sleep(RATE_LIMIT_S)
        if not html:
            miss += 1
            continue
        raw_dump("jobui_company", url, {"company": name, "slug": slug, "bytes": len(html)})
        row = parse_jobui_company_subpage(html, url)
        if row is None or not row.position:
            miss += 1
            continue

        # 岗位名去公司前缀："同程旅行 产品经理" → "产品经理"
        pos = row.position
        for prefix in (name,):
            if pos.startswith(prefix):
                pos = pos[len(prefix):].strip()
        if not pos or is_noise_position(pos):
            continue

        city_cn = row.city or "全国"
        city_norm, country = normalize_city(city_cn)
        pos_norm = normalize_position(pos)
        h = dedup_hash(f"jobui:{name}", pos_norm, city_norm, row.monthly_low, row.monthly_high,
                       datetime.now(timezone.utc).date().isoformat()[:7])
        if db.query(SalaryRecord).filter_by(dedup_hash=h).first():
            skipped += 1
            continue

        fam_code = classify_job_family(pos)
        db.add(SalaryRecord(
            collect_run_id=run_id,
            position=pos,
            company_name=f"{name}（jobui）",
            company_id=company_id,
            company_type="aggregator",
            salary_range=f"{(row.monthly_low or 0)/1000:.0f}-{(row.monthly_high or 0)/1000:.0f}K"
            if row.monthly_low else None,
            salary_monthly_low=row.monthly_low,
            salary_monthly_high=row.monthly_high,
            months=12,
            annual_salary_low=row.annual_low,
            annual_salary_high=row.annual_high,
            annual_salary_avg=row.annual_avg,
            location=city_cn,
            source="jobui_company",
            source_url=row.source_url,
            collect_date=datetime.now(timezone.utc).date().isoformat(),
            position_norm=pos_norm,
            city=city_norm,
            country=country,
            currency="CNY",
            annual_salary_avg_base=row.annual_avg,
            sample_count=row.sample_count,
            level=infer_level(pos),
            extra_json=json.dumps(row.extra, ensure_ascii=False),
            job_family_id=family_map.get(fam_code),
            dedup_hash=h,
        ))
        added += 1
        db.commit()
    return added, skipped, miss


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", nargs="*", help="指定公司名过滤")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()
    family_map = {jf.code: jf.id for jf in db.query(JobFamily).all()}

    targets = {k: v for k, v in COMPANIES.items() if not args.company or k in args.company}
    run = CollectRun(source_name="jobui_companies", status="running",
                     params_json=json.dumps(targets, ensure_ascii=False))
    db.add(run)
    db.flush()

    tot_a = tot_s = tot_m = 0
    for name, cid in targets.items():
        try:
            a, s, m = collect_company(db, run.id, family_map, name, cid)
            tot_a += a
            tot_s += s
            tot_m += m
        except Exception as e:
            print(f"ERR {name}: {e}")
            tot_m += 1

    run.items_fetched = tot_a + tot_s + tot_m
    run.items_new = tot_a
    run.status = "success" if tot_a or tot_s else "partial"
    run.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.commit()
    print(f"done: +{tot_a} new, {tot_s} dup, {tot_m} miss → run #{run.id}")


if __name__ == "__main__":
    main()
