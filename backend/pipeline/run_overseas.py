"""海外市场薪酬采集：SearxNG 搜索摘要抽取（Glassdoor/招聘站摘要级数据）。

jobui 只覆盖国内；海外市场（DIDA 驻地：港/新/曼谷/吉隆坡/雅加达/马德里/伦敦/迪拜等）
页面都有墙，走搜索摘要抽数字路线（hermes 法务调研同款路数）。

摘要模式：
- Glassdoor: "The average salary for a Sales Manager is SGD 6,000 per month"
- 招聘站:    "THB60000 - THB100000 per month"

用法：
    python3 -m backend.pipeline.run_overseas                 # 全量海外城市 × 销售序列岗
    python3 -m backend.pipeline.run_overseas --only 新加坡    # 指定城市
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

from pipeline.collectors.scraper import infer_level, raw_dump, searx_search  # noqa: E402
from pipeline.cleaning.normalize import (  # noqa: E402
    classify_job_family,
    dedup_hash,
    normalize_city,
    normalize_position,
)
from pipeline.ingest import DEFAULT_FX, init_db  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import CollectRun, JobFamily, SalaryRecord  # noqa: E402

# 海外城市 → 英文名（搜索用）
OVERSEAS_CITIES = {
    "香港": "Hong Kong", "新加坡": "Singapore", "曼谷": "Bangkok Thailand",
    "吉隆坡": "Kuala Lumpur Malaysia", "雅加达": "Jakarta Indonesia",
    "东京": "Tokyo Japan", "首尔": "Seoul Korea", "马尼拉": "Manila Philippines",
    "胡志明市": "Ho Chi Minh Vietnam", "马德里": "Madrid Spain",
    "迪拜": "Dubai UAE", "伦敦": "London UK",
}
# 海外销售序列岗（DIDA 海外主要岗位：BD/业务/大客户/区域销售）
OVERSEAS_POSITIONS = {
    "业务经理": "sales manager",
    "大客户经理": "account manager",
    "BD支持": "business development representative",
    "区域销售经理": "regional sales manager",
    "销售总监": "sales director",
}
RATE_LIMIT_S = 4.0

# 摘要抽数字模式：货币符号/代码 + 数值 + 周期
_PATTERNS = [
    # "SGD 6,000 - SGD 8,000 per month" / "THB60000 - THB100000 per month"
    re.compile(r"([A-Z]{3})\s?([\d,]{3,10})\s?(?:-|–|to)\s?(?:[A-Z]{3})?\s?([\d,]{3,10})\s*(?:per month|/month|a month|monthly)", re.I),
    # "SGD 6,000 per month"
    re.compile(r"([A-Z]{3})\s?([\d,]{3,10})\s*(?:per month|/month|a month|monthly)", re.I),
    re.compile(r"([A-Z]{3})\s?([\d,]{3,10})\s*(?:per year|/year|per annum|a year|annual|yearly)", re.I),
    # "S$3,400 per month" / "HK$20,000 monthly"（Glassdoor 常用本地符号）
    re.compile(r"(S\$|HK\$|RM|Rp|₹|€|£)\s?([\d,]{3,10})\s*(?:per month|/month|a month|monthly)", re.I),
    # "$3,400 per month"（语境里带城市名时 $ 按本币处理，由上下文币种映射）
    re.compile(r"\$\s?([\d,]{3,10})\s*(?:per month|/month|a month|monthly)"),
    re.compile(r"\$\s?([\d,]{3,10})\s*(?:per year|/year|per annum|a year|annual)", re.I),
]

# 符号 → ISO 币种
_SYMBOL_CURRENCY = {
    "S$": "SGD", "HK$": "HKD", "RM": "MYR", "Rp": "IDR", "₹": "INR",
    "€": "EUR", "£": "GBP",
}


def extract_amounts(text: str, city_en: str = "") -> list[dict]:
    """从摘要文本抽取 (币种, 月/年薪低, 高)。"""
    out = []
    for pat in _PATTERNS:
        for m in pat.finditer(text):
            groups = m.groups()
            if len(groups) == 1:
                # 纯 $ 模式：只有一个金额捕获组
                sym, lo_s, hi_s = "$", groups[0], None
            elif len(groups) >= 3 and groups[2] is not None:
                sym, lo_s, hi_s = groups[0], groups[1], groups[2]
            else:
                sym, lo_s = groups[0], groups[1]
                hi_s = groups[2] if len(groups) >= 3 else None
            lo = float(lo_s.replace(",", ""))
            hi = float(hi_s.replace(",", "")) if hi_s else None
            if lo < 100:  # 时薪类噪声
                continue
            sym = str(sym).strip()
            if re.fullmatch(r"[A-Za-z$]{1,3}", sym) and not sym.upper().startswith(("S$", "HK")):
                sym_u = sym.upper()
                cur = sym_u if re.fullmatch(r"[A-Z]{3}", sym_u) else _SYMBOL_CURRENCY.get(sym, "USD")
            else:
                cur = _SYMBOL_CURRENCY.get(sym, "USD")
            # 纯 $ + 城市语境 → 本币
            if cur == "USD" and sym == "$":
                if "singapore" in city_en.lower():
                    cur = "SGD"
                elif "hong kong" in city_en.lower():
                    cur = "HKD"
            # HK$ 模式第二个数字重复报了一次（低-高区间两个 match），去重
            if out and out[-1]["currency"] == cur and out[-1]["low"] == lo:
                out[-1]["high"] = hi or out[-1]["low"]
                continue
            kind = "monthly" if "month" in pat.pattern.lower() else "annual"
            out.append({"currency": cur, "low": lo, "high": hi, "kind": kind,
                        "snippet": text[max(0, m.start() - 60):m.end() + 30]})
    return out


def collect_city_position(db, run_id: int, family_map: dict, city_cn: str, city_en: str,
                          pos_cn: str, pos_en: str) -> tuple[int, int]:
    """搜一岗一城，抽数字落库。返回 (新增, 跳过)。"""
    query = f'"{pos_en}" salary {city_en} average per month'
    try:
        results = searx_search(query, pages=1)
    except Exception as e:
        print(f"  SEARCH-ERR {city_cn}/{pos_cn}: {e}")
        return 0, 0

    candidates = []
    for r in results:
        content = (r.get("content") or "") + " " + (r.get("title") or "")
        for amt in extract_amounts(content, city_en):
            amt["url"] = r.get("url", "")
            candidates.append(amt)
    raw_dump("overseas_snippet", f"searx::{query}", {
        "city": city_cn, "position": pos_cn, "hits": candidates})

    if not candidates:
        print(f"  MISS {city_cn}/{pos_cn}")
        return 0, 0

    # 多来源数字取中位聚合：低P50/高P50 当 low/high（摘要级数据 confidence=low）
    lows = sorted(c["low"] for c in candidates)
    his = sorted((c["high"] or c["low"]) for c in candidates)
    n = len(lows)
    low_med = lows[n // 2] if n % 2 else (lows[n // 2 - 1] + lows[n // 2]) / 2
    hi_med = his[n // 2] if n % 2 else (his[n // 2 - 1] + his[n // 2]) / 2

    amt0 = candidates[0]
    cur = amt0["currency"]
    if amt0["kind"] == "annual":
        monthly_low, monthly_high = low_med / 12, hi_med / 12
    else:
        monthly_low, monthly_high = low_med, hi_med
    # 明显离谱（月薪 > 200k 等值 CNY）跳过
    if monthly_low * DEFAULT_FX.get(cur, 1.0) > 200000:
        print(f"  OUTLIER {city_cn}/{pos_cn}: {cur} {monthly_low:.0f}/mo")
        return 0, 0

    annual_low, annual_high = monthly_low * 12, monthly_high * 12
    annual_avg = (annual_low + annual_high) / 2
    city_norm, country = normalize_city(city_en)
    pos_norm = normalize_position(pos_cn)
    today = datetime.now(timezone.utc).date().isoformat()
    h = dedup_hash("overseas", pos_norm, city_norm, round(monthly_low), round(monthly_high), today[:7])
    if db.query(SalaryRecord).filter_by(dedup_hash=h).first():
        return 0, 1

    db.add(SalaryRecord(
        collect_run_id=run_id,
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
        source_url=amt0["url"],
        collect_date=today,
        position_norm=pos_norm,
        city=city_norm,
        country=country,
        currency=cur,
        annual_salary_avg_base=annual_avg * DEFAULT_FX.get(cur, 7.0),
        level=infer_level(pos_cn),
        sample_count=n,
        extra_json=json.dumps({"basis": "search_snippet", "confidence": "low",
                               "sources": list({c["url"] for c in candidates})[:5]},
                              ensure_ascii=False),
        job_family_id=family_map.get(classify_job_family(pos_cn)),
        dedup_hash=h,
    ))
    print(f"  + {city_cn}/{pos_cn}: {cur} {monthly_low:,.0f}-{monthly_high:,.0f}/mo ({n} sources)")
    return 1, 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="过滤城市或岗位")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()
    family_map = {jf.code: jf.id for jf in db.query(JobFamily).all()}

    run = CollectRun(source_name="overseas_snippet", status="running",
                     params_json=json.dumps({"cities": list(OVERSEAS_CITIES)}, ensure_ascii=False))
    db.add(run)
    db.flush()

    added = skipped = miss = 0
    for city_cn, city_en in OVERSEAS_CITIES.items():
        if args.only and city_cn not in args.only:
            continue
        for pos_cn, pos_en in OVERSEAS_POSITIONS.items():
            if args.only and pos_cn not in args.only:
                continue
            try:
                a, s = collect_city_position(db, run.id, family_map, city_cn, city_en, pos_cn, pos_en)
                added += a
                skipped += s
                miss += 1 if (a == 0 and s == 0) else 0
            except Exception as e:
                print(f"  ERR {city_cn}/{pos_cn}: {e}")
            db.commit()
            time.sleep(RATE_LIMIT_S)

    run.items_fetched = added + skipped + miss
    run.items_new = added
    run.status = "success" if (added or skipped) else "partial"
    run.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.commit()
    print(f"done: +{added} new, {skipped} dup, {miss} miss → run #{run.id}")


if __name__ == "__main__":
    main()
