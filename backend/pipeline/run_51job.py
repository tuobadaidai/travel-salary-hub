"""51job 前程无忧 JD 采集器（骨架，待调试）。

URL 规律：
  列表页：https://we.51job.com/pc/search?keyword={kw}&jobArea={city_code}
  JD 页： https://jobs.51job.com/{city}/{id}.html

51job 反爬较弱，公开列表页即可见薪酬区间（如 "15-25K·14薪"）。
实际页面结构需在有 scrapling 环境的部署机上调试后补充正则。

用法：
  python3 -m pipeline.run_51job --keyword 后端工程师 --city 深圳
"""
import argparse
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from pipeline.collectors.scraper import fetch_scrapling, infer_level  # noqa: E402
from pipeline.cleaning.normalize import normalize_city, normalize_position, dedup_hash  # noqa: E402
from pipeline.ingest import init_db  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import CollectRun, SalaryRecord  # noqa: E402


# 51job 城市代码（常用城市，按需扩展）
CITY_CODES = {
    "深圳": "040010", "北京": "010000", "上海": "020000", "广州": "030200",
    "杭州": "080100", "成都": "090200", "武汉": "180100", "南京": "070200",
}

SALARY_RE = re.compile(r"(\d+\.?\d*)\s*-\s*(\d+\.?\d*)\s*[Kk千]?\s*(?:·\s*(\d+)\s*薪)?")


def parse_salary(text: str):
    """从 JD 文本抽薪酬区间，返回 (monthly_low, monthly_high, months)。"""
    m = SALARY_RE.search(text)
    if not m:
        return None
    lo = float(m.group(1)) * 1000
    hi = float(m.group(2)) * 1000
    months = int(m.group(3)) if m.group(3) else 12
    return lo, hi, months


def collect(keyword: str, city: str, max_pages: int = 3):
    """采集 51job 搜索结果。TODO: 实际页面选择器需部署后调试。"""
    city_code = CITY_CODES.get(city, "040010")
    init_db()
    db = SessionLocal()
    run = CollectRun(source_name="job_51job", status="running",
                     params_json=f'{{"keyword":"{keyword}","city":"{city}"}}')
    db.add(run)
    db.flush()

    added = skipped = 0
    # TODO: 实际列表页解析
    # for page in range(1, max_pages+1):
    #     url = f"https://we.51job.com/pc/search?keyword={keyword}&jobArea={city_code}&page={page}"
    #     html = fetch_scrapling(url)
    #     ... 提取 JD 链接、岗位名、公司、薪酬 ...
    print("51job collector: skeleton only, needs HTML samples to finish parsing rules")

    run.items_fetched = added + skipped
    run.items_new = added
    run.status = "partial"
    run.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.commit()
    print(f"done: +{added}, skipped {skipped} → run #{run.id}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyword", required=True)
    ap.add_argument("--city", default="深圳")
    args = ap.parse_args()
    collect(args.keyword, args.city)
