"""Levels.fyi 采集器（通过 Apify）。

前置条件：
  1. 注册 Apify 账号（https://apify.com），充值或用免费额度
  2. 在 Apify 上选一个 Levels.fyi scraper actor（推荐 scrapesage/levels-fyi-scraper，$1.38/千条）
  3. 把 token 填到环境变量 APIFY_TOKEN
  4. 部署后跑一次，根据 actor 返回的字段调整 PARSER_MAP

用法：
  APIFY_TOKEN=apify_xxx python3 -m pipeline.run_levels_fyi
  python3 -m pipeline.run_levels_fyi --actor scrapesage/levels-fyi-scraper
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.config import settings  # noqa: E402
from pipeline.ingest import init_db  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import CollectRun, SalaryRecord  # noqa: E402

# 关注的中国区公司（Levels.fyi slug）
DEFAULT_COMPANIES = [
    "bytedance",    # 字节跳动
    "alibaba",      # 阿里巴巴（含飞猪）
    "tencent",      # 腾讯
    "meituan",      # 美团
    "baidu",        # 百度
]

# 关注的岗位族（Levels.fyi job family slug）
DEFAULT_FAMILIES = [
    "software-engineer",
    "product-manager",
    "data-scientist",
    "designer",
    "marketing",
]


def run_apify(actor_id: str, input_data: dict) -> list[dict]:
    """调 Apify run-sync-get-dataset-items，返回结果数组。"""
    token = settings.apify_token
    if not token:
        raise RuntimeError("APIFY_TOKEN not set. 请先在环境变量配置 Apify token。")
    # actor_id 格式：username/actor-name → URL 编码
    act_encoded = actor_id.replace("/", "~")
    url = f"https://api.apify.com/v2/acts/{act_encoded}/run-sync-get-dataset-items?token={token}"
    with httpx.Client(timeout=120) as c:
        r = c.post(url, json=input_data)
        r.raise_for_status()
        return r.json()


def parse_item(item: dict) -> dict | None:
    """把 Apify 返回的一条记录归一到 SalaryRecord 字段。

    Apify 各 actor 返回字段名不同，这里做宽容匹配：
    - company / companyName / company_name
    - title / jobTitle / job_title / role
    - level / levelName / level_name
    - location / locationCity / city
    - totalComp / total_comp / totalCompensation（USD/年）
    - base / baseSalary / base_salary（USD/年）
    """
    company = item.get("company") or item.get("companyName") or item.get("company_name") or ""
    title = item.get("title") or item.get("jobTitle") or item.get("job_title") or item.get("role") or ""
    level_raw = item.get("level") or item.get("levelName") or item.get("level_name") or ""
    location = item.get("location") or item.get("locationCity") or item.get("city") or "China"

    # 总薪酬（USD）
    total_usd = (item.get("totalComp") or item.get("total_comp") or
                 item.get("totalCompensation") or item.get("total_compensation"))
    if total_usd is None:
        return None
    try:
        total_usd = float(total_usd)
    except (TypeError, ValueError):
        return None
    if total_usd < 1000 or total_usd > 10000000:
        return None

    # 只保留中国相关
    if not any(k in str(location).lower() for k in ["china", "beijing", "shanghai", "shenzhen",
                                                    "hangzhou", "chengdu", "china"]):
        return None

    cny = total_usd * settings.usd_to_cny
    # 粗略映射 level
    level_lower = str(level_raw).lower()
    if any(k in level_lower for k in ["principal", "staff", "senior", "l6", "l7", "l8", "l9", "l10", "e6", "e7", "e8"]):
        level = "高级"
    elif any(k in level_lower for k in ["l4", "l5", "e4", "e5", "sde ii", "swe iii"]):
        level = "主管"
    elif any(k in level_lower for k in ["l2", "l3", "e3", "sde i", "swe ii"]):
        level = "专员"
    else:
        level = "高级"

    city = "全国"
    loc = str(location).lower()
    for cn, en in [("北京", "beijing"), ("上海", "shanghai"), ("深圳", "shenzhen"),
                   ("杭州", "hangzhou"), ("成都", "chengdu")]:
        if en in loc:
            city = cn
            break

    return {
        "position": title,
        "company_name": f"{company}（levels.fyi）",
        "level": level,
        "city": city,
        "annual_avg_cny": cny,
        "annual_low_cny": cny * 0.85,
        "annual_high_cny": cny * 1.15,
        "location": str(location),
        "source_url": item.get("url") or item.get("link") or f"https://levels.fyi/company/{company}",
        "extra": {
            "total_usd": total_usd,
            "level_raw": level_raw,
            "fx_rate": settings.usd_to_cny,
        },
    }


def collect(actor_id: str, companies: list[str], families: list[str]):
    if not settings.apify_token:
        print("ERROR: 请先设置 APIFY_TOKEN 环境变量")
        sys.exit(1)

    init_db()
    db = SessionLocal()
    run = CollectRun(source_name="levels_fyi", status="running",
                     params_json=json.dumps({"actor": actor_id, "companies": companies},
                                            ensure_ascii=False))
    db.add(run)
    db.flush()

    # 不同 actor 的 input schema 不同，这里给一个通用模板，
    # 如果 actor 报错说 input 不对，看 Apify actor 文档调整下面的 body
    input_data = {
        "companies": companies,
        "jobFamilies": families,
        "location": "China",
        "maxItems": 5000,
    }

    print(f"调用 Apify actor {actor_id} ...")
    try:
        items = run_apify(actor_id, input_data)
    except Exception as e:
        run.status = "failed"
        run.error_message = str(e)[:500]
        run.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        db.commit()
        print(f"FAILED: {e}")
        return

    print(f"返回 {len(items)} 条原始记录，解析中...")
    added = skipped = 0
    for item in items:
        parsed = parse_item(item)
        if not parsed:
            skipped += 1
            continue
        h = f"levels_fyi:{parsed['company_name']}:{parsed['position']}:{parsed['level']}:{parsed['city']}"
        # 简化 dedup_hash（实际用 md5）
        import hashlib
        h = hashlib.md5(h.encode()).hexdigest()
        if db.query(SalaryRecord).filter_by(dedup_hash=h).first():
            skipped += 1
            continue
        db.add(SalaryRecord(
            position=parsed["position"],
            position_norm=parsed["position"],
            company_name=parsed["company_name"],
            company_type="aggregator",
            annual_salary_low=parsed["annual_low_cny"],
            annual_salary_high=parsed["annual_high_cny"],
            annual_salary_avg=parsed["annual_avg_cny"],
            annual_salary_avg_base=parsed["annual_avg_cny"],
            location=parsed["location"],
            city=parsed["city"],
            country="CN",
            currency="CNY",
            level=parsed["level"],
            source="levels_fyi",
            source_url=parsed["source_url"],
            collect_date=datetime.now(timezone.utc).date().isoformat(),
            collect_run_id=run.id,
            extra_json=json.dumps(parsed["extra"], ensure_ascii=False),
            dedup_hash=h,
        ))
        added += 1
    db.commit()

    run.items_fetched = len(items)
    run.items_new = added
    run.items_rejected = skipped
    run.status = "success" if added else "partial"
    run.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.commit()
    print(f"done: +{added} new, {skipped} skipped → run #{run.id}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--actor", default="scrapesage/levels-fyi-scraper",
                    help="Apify actor id（username/actor-name）")
    ap.add_argument("--companies", nargs="*", default=DEFAULT_COMPANIES)
    ap.add_argument("--families", nargs="*", default=DEFAULT_FAMILIES)
    args = ap.parse_args()
    collect(args.actor, args.companies, args.families)
