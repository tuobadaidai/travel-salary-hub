"""批量采集 DIDA 核心岗位 × 城市的 jobui 聚合薪酬页，落库 salary_records。

用法：
    python3 -m backend.pipeline.run_batch                  # 全量（核心岗位 × DIDA 城市）
    python3 -m backend.pipeline.run_batch --only 深圳 产品经理 后端工程师   # 指定城市岗位

岗位清单来自 DIDA 薪酬表（299 职务归一化后 ≥4 人的 45 核心岗位，剔除内部特有岗），
映射到 jobui 有聚合页的通用市场岗位名。城市取 DIDA 工作地点Top（国内为主）。
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from pipeline.collectors.scraper import (  # noqa: E402
    fetch,
    infer_level,
    parse_jobui_salary_page,
    raw_dump,
)
from pipeline.cleaning.normalize import classify_job_family  # noqa: E402
from pipeline.ingest import DEFAULT_FX, backfill_job_families, init_db  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import CollectRun, JobFamily, SalaryRecord  # noqa: E402
from pipeline.cleaning.normalize import dedup_hash  # noqa: E402

# DIDA 核心岗位（≥4人）→ 市场通用岗位名（jobui 可检索）
DIDA_POSITIONS = [
    # 客服/运营序列（O 序列主力）
    "客服专员", "订单运营专员", "录入专员", "退改操作专员", "客诉专员",
    "内容运营专员", "运营专员", "售后收益运营", "供应商运营", "技术运营",
    # 业务/销售序列
    "业务经理", "区域销售经理", "大客户经理", "海外渠道运营", "区域总监",
    # 技术序列
    "后端工程师", "前端工程师", "测试工程师", "数据开发工程师", "运维工程师",
    "产品经理", "UI设计师", "算法工程师",
    # 职能序列
    "会计", "法务专员", "人事专员", "行政专员", "资金专员",
    "数据分析师", "市场营销专员",
]
# jobui 用更通用的名称检索
JOBUI_NAME_MAP = {
    "录入专员": "数据录入员", "退改操作专员": "机票预订员", "客诉专员": "客服专员",
    "售后收益运营": "运营专员", "供应商运营": "运营专员", "技术运营": "运维工程师",
    "后端工程师": "后端开发工程师", "前端工程师": "前端开发工程师",
    "测试工程师": "测试工程师", "数据开发工程师": "大数据开发工程师",
    "算法工程师": "算法工程师", "会计": "会计", "法务专员": "法务专员",
    "人事专员": "人事专员", "资金专员": "资金专员", "海外渠道运营": "渠道运营",
}

# DIDA 工作地点 → jobui 城市slug
CITY_SLUGS = {
    "深圳": "shenzhen", "长沙": "changsha", "上海": "shanghai", "重庆": "chongqing",
    "北京": "beijing", "成都": "chengdu", "杭州": "hangzhou", "广州": "guangzhou",
}

RATE_LIMIT_S = 4.0  # 合规限速


def slugify_pinyin(name: str) -> str | None:
    """jobui slug 是全拼。内置高频岗位映射，避免拼音库依赖。"""
    known = {
        "客服专员": "kefuzhuanyuan", "订单运营专员": "dingdanyunyingzhuanyuan",
        "运营专员": "yunyingzhuanyuan", "业务经理": "yewujingli",
        "区域销售经理": "quyuxiaoshoujingli", "大客户经理": "dakehujingli",
        "后端开发工程师": "houduankaifagongchengshi", "前端开发工程师": "qianduankaifagongchengshi",
        "测试工程师": "ceshigongchengshi", "数据开发工程师": "shujukaifagongchengshi",
        "大数据开发工程师": "dashujukaifagongchengshi", "运维工程师": "yunweigongchengshi",
        "产品经理": "chanpinjingli", "UI设计师": "uishejishi", "算法工程师": "suanfagongchengshi",
        "会计": "kuaiji", "法务专员": "fawuzhuanyuan", "人事专员": "renshizhuanyuan",
        "行政专员": "xingzhengzhuanyuan", "资金专员": "zijinzhuanyuan",
        "数据分析师": "shujufenxishi", "市场营销专员": "yingxiaoyunyingzhuanyuan",
        "渠道运营": "qudaoyunying", "数据录入员": "shujuluruyuan",
        "机票预订员": "jipiaoyudingyuan",
    }
    return known.get(name)


def collect_one(db, run_id: int, family_map: dict, position_dida: str, city_cn: str) -> tuple[int, int]:
    """采集一个 岗位×城市 页面并落库。返回 (新增, 跳过)。"""
    from pipeline.collectors.scraper import fetch_scrapling, discover_jobui_urls
    from pipeline.cleaning.normalize import normalize_city, normalize_position

    market_name = JOBUI_NAME_MAP.get(position_dida, position_dida)
    slug_city = CITY_SLUGS[city_cn]
    slug_pos = slugify_pinyin(market_name)

    url = None
    if slug_city and slug_pos:
        url = f"https://www.jobui.com/salary/{slug_city}-{slug_pos}/"
        html = fetch_scrapling(url)
    else:
        html = None
    # slug 猜测失败 → 搜索发现兜底
    if not html:
        found = discover_jobui_urls(market_name, slug_city)
        if found:
            url = found[0]
            html = fetch_scrapling(url)
    if not html:
        print(f"  MISS {city_cn}/{market_name}")
        return 0, 0

    raw_dump("jobui", url, {"position": market_name, "city": city_cn, "bytes": len(html)})
    row = parse_jobui_salary_page(html, url)
    if row is None or row.annual_avg is None:
        print(f"  NOPARSE {city_cn}/{market_name} ({url})")
        return 0, 0

    city_norm, country = normalize_city(city_cn)
    pos_norm = normalize_position(market_name)
    h = dedup_hash("jobui", pos_norm, city_norm, row.monthly_low, row.monthly_high,
                   datetime.now(timezone.utc).date().isoformat()[:7])
    if db.query(SalaryRecord).filter_by(dedup_hash=h).first():
        return 0, 1

    fam_code = classify_job_family(market_name)
    db.add(SalaryRecord(
        collect_run_id=run_id,
        position=market_name,
        company_name="职友集聚合",
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
        source="jobui",
        source_url=row.source_url,
        collect_date=datetime.now(timezone.utc).date().isoformat(),
        position_norm=pos_norm,
        city=city_norm,
        country=country,
        currency="CNY",
        annual_salary_avg_base=row.annual_avg,
        sample_count=row.sample_count,
        education_level=None,
        level=infer_level(market_name),
        extra_json=json.dumps(row.extra, ensure_ascii=False),
        job_family_id=family_map.get(fam_code),
        dedup_hash=h,
    ))
    return 1, 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="指定 城市 岗位... 过滤")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()
    family_map = {jf.code: jf.id for jf in db.query(JobFamily).all()}

    run = CollectRun(source_name="jobui_batch", status="running",
                     params_json=json.dumps({"positions": len(DIDA_POSITIONS),
                                             "cities": list(CITY_SLUGS)}, ensure_ascii=False))
    db.add(run)
    db.flush()

    cities = [c for c in CITY_SLUGS if not args.only or c in args.only]
    positions = [p for p in DIDA_POSITIONS if not args.only or p in args.only or JOBUI_NAME_MAP.get(p, p) in args.only]

    added = skipped = miss = 0
    for city in cities:
        for pos in positions:
            try:
                a, s = collect_one(db, run.id, family_map, pos, city)
                added += a
                skipped += s
                if a == 0 and s == 0:
                    miss += 1
            except Exception as e:
                print(f"  ERR {city}/{pos}: {e}")
                miss += 1
            db.commit()
            time.sleep(RATE_LIMIT_S)

    run.items_fetched = added + skipped + miss
    run.items_new = added
    run.status = "success" if added or skipped else "partial"
    run.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.commit()
    print(f"done: +{added} new, {skipped} dup, {miss} miss → run #{run.id}")


if __name__ == "__main__":
    main()
