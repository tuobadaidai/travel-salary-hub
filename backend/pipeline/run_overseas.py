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
from pipeline.ingest import get_fx, init_db  # noqa: E402
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
# kind 由周期词直接判定，不再用"pattern 里含 month"推断
_PATTERNS = [
    # "SGD 6,000 - SGD 8,000 per month" / "THB60000 - THB100000 per month"
    (re.compile(r"([A-Z]{3})\s?([\d,]{3,10})\s?(?:-|–|to)\s?(?:[A-Z]{3})?\s?([\d,]{3,10})\s*(per month|/month|a month|monthly)", re.I), "monthly"),
    (re.compile(r"([A-Z]{3})\s?([\d,]{3,10})\s?(?:-|–|to)\s?(?:[A-Z]{3})?\s?([\d,]{3,10})\s*(per year|/year|per annum|a year|annual|yearly)", re.I), "annual"),
    # "SGD 6,000 per month"
    (re.compile(r"([A-Z]{3})\s?([\d,]{3,10})\s*(per month|/month|a month|monthly)", re.I), "monthly"),
    (re.compile(r"([A-Z]{3})\s?([\d,]{3,10})\s*(per year|/year|per annum|a year|annual|yearly)", re.I), "annual"),
    # "S$3,400 per month" / "HK$20,000 monthly"（Glassdoor 常用本地符号）
    (re.compile(r"(S\$|HK\$|RM|Rp|₹|€|£|A\$|C\$|US\$)\s?([\d,]{3,10})\s*(?:-|–)?\s?(?:[\d,]{3,10})?\s*(per month|/month|a month|monthly)", re.I), "monthly"),
    (re.compile(r"(S\$|HK\$|RM|Rp|₹|€|£|A\$|C\$|US\$)\s?([\d,]{3,10})\s*(?:-|–)?\s?(?:[\d,]{3,10})?\s*(per year|/year|per annum|a year|annual|yearly)", re.I), "annual"),
    # "$3,400 per month"（裸 $：Glassdoor 用本地符号渲染，按城市映射本币；
    # 负向后顾排除 A$/C$/S$/HK$ 等带前缀符号）
    (re.compile(r"(?<![A-Za-z])\$\s?([\d,]{3,10})\s*(?:-|–)?\s?(?:[\d,]{3,10})?\s*(per month|/month|a month|monthly)", re.I), "monthly"),
    (re.compile(r"(?<![A-Za-z])\$\s?([\d,]{3,10})\s*(?:-|–)?\s?(?:[\d,]{3,10})?\s*(per year|/year|per annum|a year|annual|yearly)", re.I), "annual"),
]

# 符号 → ISO 币种
_SYMBOL_CURRENCY = {
    "S$": "SGD", "HK$": "HKD", "RM": "MYR", "Rp": "IDR", "₹": "INR",
    "€": "EUR", "£": "GBP", "A$": "AUD", "C$": "CAD", "US$": "USD",
}

# 城市英文名 → 裸 $ 的本币映射与异币种黑名单（美国/加拿大站点的 $ 数据不适用于本地市场）
_CITY_DOLLAR_CURRENCY = {
    "新加坡": "SGD", "香港": "HKD",
}
# 这些城市的 snippet 出现 USD/北美语境时直接丢弃（indeed.com/glassdoor 美国站污染）
_CITY_FOREIGN_EXCLUDE = {
    "曼谷": ("USD", "CAD"), "吉隆坡": ("USD", "CAD"), "雅加达": ("USD", "CAD"),
    "东京": ("USD", "CAD"), "首尔": ("USD", "CAD"), "马尼拉": ("USD", "CAD"),
    "胡志明市": ("USD", "CAD"), "马德里": ("USD", "CAD", "MXN"), "迪拜": ("INR",),
    "伦敦": ("USD", "CAD"), "香港": ("USD", "CAD"), "新加坡": ("USD", "CAD"),
}
# 年薪合理下限（等值 CNY）：低于此值视为月薪被误标为年薪或噪声
_ANNUAL_CNY_FLOOR = 50000
# 月薪合理上限（等值 CNY）：高于此值视为年薪被误标为月薪
_MONTHLY_CNY_CEILING = 200000


def _detect_geo_context(text: str) -> str:
    """从 snippet 上下文检测实际地区（美国/加拿大/澳洲等），用于排除错配数据。"""
    t = text.lower()
    for kw in ("united states", " u.s.", "us$", "woburn", "boston", "new york",
               "san francisco", "chicago", "atlanta", "texas", "california",
               "canada", "toronto", "vancouver", "burnaby", "australia", "sydney",
               "melbourne", "london uk"):
        if kw in t:
            if "australia" in kw or "sydney" in kw or "melbourne" in kw:
                return "AU"
            if "canada" in kw or "toronto" in kw or "vancouver" in kw or "burnaby" in kw:
                return "CA"
            if "london" in kw:
                return "UK"
            return "US"
    return ""


def extract_amounts(text: str, city_cn: str = "", city_en: str = "") -> list[dict]:
    """从摘要文本抽取 (币种, 月/年薪低, 高, kind)。"""
    out = []
    claimed: list[tuple[int, int]] = []  # 已命中的文本区间，避免同一金额被多模式重复抽取
    for pat, kind in _PATTERNS:
        for m in pat.finditer(text):
            if any(s <= m.start() < e for s, e in claimed):
                continue
            groups = m.groups()[:-1]  # 末组是周期词，不参与金额解析
            if pat.pattern.startswith("(?<![A-Za-z])\\$"):
                sym, lo_s = "$", groups[0]
                hi_s = groups[1] if len(groups) >= 2 and groups[1] else None
            elif len(groups) == 2:
                sym, lo_s = groups[0], groups[1]
                hi_s = None
            else:
                sym = groups[0]
                lo_s = groups[1]
                hi_s = groups[2] if len(groups) >= 3 and groups[2] else None
            lo = float(lo_s.replace(",", ""))
            hi = float(hi_s.replace(",", "")) if hi_s else None
            if lo < 100:  # 时薪类噪声
                continue
            sym = str(sym).strip()
            if sym in _SYMBOL_CURRENCY:
                cur = _SYMBOL_CURRENCY[sym]
            elif re.fullmatch(r"[A-Z]{3}", sym.upper()):
                cur = sym.upper()
            else:
                cur = "USD"  # 裸 $
            # 裸 $ → 按城市映射本币（仅 新加坡/香港 语境可信）
            if cur == "USD" and sym == "$" and city_cn in _CITY_DOLLAR_CURRENCY:
                cur = _CITY_DOLLAR_CURRENCY[city_cn]
            # 城市语境币种黑名单：美国/加拿大/澳洲站点数据混入（snippet 含
            # Woburn/Boston/US 等词），这是曼谷 USD 6万/月污染的根源
            geo = _detect_geo_context(text)
            if geo and geo != _CITY_COUNTRY_CODE.get(city_cn, ""):
                continue
            if cur in _CITY_FOREIGN_EXCLUDE.get(city_cn, ()) and geo in ("US", "CA", "AU"):
                continue
            # A$/C$/US$ 等异币种在本地城市无意义，直接丢
            if cur in ("AUD", "CAD", "MXN") and city_cn not in ("悉尼", "墨尔本", "多伦多", "墨西哥城"):
                continue
            # 非本币数据必须明示目标城市（"in Bangkok"）才可信：
            # Thomas & Betts / Barnstable 这类无地名词的美国数据靠这条拦住
            native = _CITY_NATIVE_CURRENCIES.get(city_cn, set())
            if cur not in native and city_en.lower() not in text.lower():
                continue
            claimed.append((m.start(), m.end()))
            out.append({"currency": cur, "low": lo, "high": hi, "kind": kind,
                        "geo": geo,
                        "snippet": text[max(0, m.start() - 60):m.end() + 30]})
    return out


# 城市 → 国家码（与 _CITY_FOREIGN_EXCLUDE 配套）
_CITY_COUNTRY_CODE = {
    "香港": "HK", "新加坡": "SG", "曼谷": "TH", "吉隆坡": "MY", "雅加达": "ID",
    "东京": "JP", "首尔": "KR", "马尼拉": "PH", "胡志明市": "VN", "马德里": "ES",
    "迪拜": "AE", "伦敦": "GB",
}

# 城市本币白名单：snippet 数据只有本币（或 USD/EUR/GBP 等国际发布口径）才可信。
# 这是单源噪声（曼谷 INR、胡志明 PHP 串城市）的最后一道闸
_CITY_NATIVE_CURRENCIES = {
    "香港": {"HKD"}, "新加坡": {"SGD"}, "曼谷": {"THB"}, "吉隆坡": {"MYR"},
    "雅加达": {"IDR"}, "东京": {"JPY"}, "首尔": {"KRW"}, "马尼拉": {"PHP"},
    "胡志明市": {"VND"}, "马德里": {"EUR"}, "迪拜": {"AED"}, "伦敦": {"GBP"},
}
# 这些国际通用币种在任何城市都可接受（招聘顾问/全球报告常用）
_INTERNATIONAL_CURRENCIES = {"USD", "EUR", "GBP"}


def aggregate_amounts(candidates: list[dict], city_cn: str) -> dict | None:
    """口径归一后按 币种×周期 分桶，桶间互不混合；取最大桶做中位聚合。

    每条 candidate 先做口径合理性校验（年薪折 CNY 过低 / 月薪折 CNY 过高
    视为口径误标，转为另一口径），再进入分桶。
    """
    checked = []
    for c in candidates:
        lo, hi = c["low"], c["high"] or c["low"]
        # 城市本币白名单：非本币且非国际通用币种的记录直接丢弃
        # （INR 数据出现在曼谷、PHP 数据出现在东京这类跨城噪声）
        native = _CITY_NATIVE_CURRENCIES.get(city_cn)
        if native and c["currency"] not in native | _INTERNATIONAL_CURRENCIES:
            continue
        fx = get_fx(c["currency"])
        if c["kind"] == "annual":
            # 年薪 < 5万CNY 多为月薪误标或小币种噪声
            if lo * fx < _ANNUAL_CNY_FLOOR:
                c = {**c, "kind": "monthly", "low": lo, "high": hi}
        else:
            # 月薪 > 20万CNY 多为年薪误标
            if lo * fx > _MONTHLY_CNY_CEILING:
                c = {**c, "kind": "annual", "low": lo, "high": hi}
        checked.append(c)
    if not checked:
        return None

    # 币种 × 周期 分桶：不同币种/口径绝不混算
    buckets: dict[tuple[str, str], list[dict]] = {}
    for c in checked:
        buckets.setdefault((c["currency"], c["kind"]), []).append(c)
    key, bucket = max(buckets.items(), key=lambda kv: len(kv[1]))
    cur, kind = key

    lows = sorted(c["low"] for c in bucket)
    his = sorted((c["high"] or c["low"]) for c in bucket)
    n = len(lows)
    low_med = lows[n // 2] if n % 2 else (lows[n // 2 - 1] + lows[n // 2]) / 2
    hi_med = his[n // 2] if n % 2 else (his[n // 2 - 1] + his[n // 2]) / 2
    return {"currency": cur, "kind": kind, "low": low_med, "high": hi_med,
            "n": n, "mixed_dropped": len(checked) - n}


def collect_city_position(db, run_id: int, family_map: dict, city_cn: str, city_en: str,
                          pos_cn: str, pos_en: str) -> tuple[int, int]:
    """搜一岗一城，抽数字落库。返回 (新增, 跳过)。"""
    query = f'"{pos_en}" salary {city_en} average'
    try:
        results = searx_search(query, pages=1)
    except Exception as e:
        print(f"  SEARCH-ERR {city_cn}/{pos_cn}: {e}")
        return 0, 0

    candidates = []
    for r in results:
        content = (r.get("content") or "") + " " + (r.get("title") or "")
        for amt in extract_amounts(content, city_cn, city_en):
            amt["url"] = r.get("url", "")
            candidates.append(amt)
    raw_dump("overseas_snippet", f"searx::{query}", {
        "city": city_cn, "position": pos_cn, "hits": candidates})

    if not candidates:
        print(f"  MISS {city_cn}/{pos_cn}")
        return 0, 0

    # 币种×周期分桶中位聚合（不混币种、不混月薪/年薪口径）
    agg = aggregate_amounts(candidates, city_cn)
    if agg is None:
        print(f"  MISS {city_cn}/{pos_cn} (all filtered)")
        return 0, 0
    cur, kind = agg["currency"], agg["kind"]
    low_med, hi_med = agg["low"], agg["high"]
    n = agg["n"]

    if kind == "annual":
        monthly_low, monthly_high = low_med / 12, hi_med / 12
    else:
        monthly_low, monthly_high = low_med, hi_med
    # 明显离谱（月薪 > 200k 等值 CNY）跳过
    if monthly_low * get_fx(cur) > 200000:
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
        annual_salary_avg_base=annual_avg * get_fx(cur),
        level=infer_level(pos_cn),
        sample_count=n,
        extra_json=json.dumps({"basis": "search_snippet", "confidence": "low",
                               "basis_kind": kind,
                               "mixed_dropped": agg["mixed_dropped"],
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
