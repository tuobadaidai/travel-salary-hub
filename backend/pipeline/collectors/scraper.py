"""三通道采集引擎（复用 hermes 搜索降级策略的可用部分）：

通道 A · 搜索发现：SearxNG (localhost:3004) — 发现目标页 URL
通道 B · 页面抓取：scrapling (chrome 指纹) — 主通道；Crawl4AI (11235) — 备用
通道 C · 薪酬抽取：jobui 聚合页结构化解析 → 统一 SalaryRow

数据源矩阵（首期）：
- jobui 职友集：城市×岗位聚合页（有样本量、分布、分位近似）——主源
- Glassdoor/LinkedIn：境外岗位，首期经搜索摘要抽取（页面有登录墙）
- 薪酬报告 PDF（Gemini Personnel 等）：搜索结果摘要级
"""

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.config import settings

SEARXNG = "http://localhost:3004"
CRAWL4AI = "http://localhost:11235"

PROJECT_ROOT = settings.db_path.parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"


@dataclass
class SalaryRow:
    position: str = ""
    city: str = ""
    country: str = "CN"
    source: str = ""
    source_url: str = ""
    sample_count: int | None = None
    monthly_low: float | None = None
    monthly_high: float | None = None
    months: int = 12
    annual_low: float | None = None
    annual_high: float | None = None
    annual_avg: float | None = None
    extra: dict = field(default_factory=dict)  # education_wages / experience_wages / distribution


# ---------- 通道 A：SearxNG ----------

def searx_search(query: str, pages: int = 1) -> list[dict]:
    out = []
    with httpx.Client(timeout=15) as c:
        for p in range(1, pages + 1):
            r = c.get(f"{SEARXNG}/search", params={
                "q": query, "format": "json", "language": "zh", "pageno": p,
            })
            r.raise_for_status()
            out.extend(r.json().get("results", []))
            time.sleep(1.5)
    return out


# ---------- 通道 B：抓取 ----------

def fetch_scrapling(url: str, referer: str = "https://www.google.com/") -> str | None:
    """主抓取通道：scrapling chrome 指纹。返回页面文本，失败返回 None。"""
    try:
        from scrapling.fetchers import Fetcher
        page = Fetcher.get(url, impersonate="chrome", referer=referer)
        if page.status != 200:
            return None
        body = page.body
        return body if isinstance(body, str) else body.decode("utf-8", "ignore")
    except Exception:
        return None


def fetch_crawl4ai(url: str) -> str | None:
    """备用通道：Crawl4AI 本地服务。"""
    try:
        with httpx.Client(timeout=30) as c:
            r = c.post(f"{CRAWL4AI}/crawl", json={"url": url, "formats": ["markdown"]})
            d = r.json()
            return d.get("markdown") or None
    except Exception:
        return None


def fetch(url: str) -> str | None:
    """降级链：scrapling → crawl4ai。"""
    html = fetch_scrapling(url)
    if html and "访问异常" not in html and "验证码" not in html[:600]:
        return html
    md = fetch_crawl4ai(url)
    if md and "验证码" not in md[:300]:
        return md
    return None


# ---------- 通道 C：解析 ----------

def _strip_html(s: str) -> str:
    s = re.sub(r"<script[^>]*>.*?</script>", "", s, flags=re.S)
    s = re.sub(r"<style[^>]*>.*?</style>", "", s, flags=re.S)
    s = re.sub(r"<[^>]+>", "\n", s)
    return re.sub(r"\n{2,}", "\n", s)


_CITY_SLUGS = {
    "shenzhen": "深圳", "beijing": "北京", "shanghai": "上海", "guangzhou": "广州",
    "hangzhou": "杭州", "chengdu": "成都", "wuhan": "武汉", "nanjing": "南京",
    "xian": "西安", "suzhou": "苏州", "tianjin": "天津", "changsha": "长沙",
    "xiamen": "厦门", "chongqing": "重庆", "hongkong": "香港", "singapore": "新加坡",
}

_LEVEL_HINTS = [
    ("总监", "总监"),
    ("高级经理", "经理"),
    # 资深/高级前缀优先于 经理/主管：「资深产品经理」是高级岗不是经理岗
    ("资深", "高级"), ("高级", "高级"),
    ("经理", "经理"),
    ("主管", "主管"),
    ("专员", "专员"), ("助理", "专员"), ("初级", "专员"),
]


def infer_level(position: str) -> str:
    """按岗位名推断级别：VP>总监>高级>经理>主管>专员。

    注意英文头衔必须整词匹配：「coordinator」含子串 coo，不能裸 match。
    """
    t = position.lower()
    if re.search(r"\b(vp|cto|cfo|coo|cmo|ceo|cho|cxo)\b|(^|[^a-z])vp([^a-z]|$)|合伙人|chief", t):
        return "VP"
    for kw, lv in _LEVEL_HINTS:
        if kw in t:
            return lv
    return "专员"


def parse_jobui_salary_page(html: str, url: str) -> SalaryRow | None:
    """解析职友集城市×岗位薪酬页（2026-09 实测格式）。"""
    m = re.search(r"jobui\.com/salary/([a-z]+)-([a-z]+)/", url)
    if not m:
        return None
    city = _CITY_SLUGS.get(m.group(1), m.group(1))
    text = _strip_html(html)
    # 压缩空白便于表格段解析（jobui 表格被大量 \r\n\t 分隔）
    flat = re.sub(r"[\n\r\t ]+", "\x00", text)

    row = SalaryRow(source="jobui", source_url=url, city=city)

    # 岗位名
    m = re.search(r"(?:深圳|北京|上海|广州|杭州|成都|武汉|南京|西安|苏州|天津|长沙|厦门|重庆)([^工资就业前景]{2,20}?)(?:工资|就业前景|月薪|年薪)", text)
    if m:
        row.position = m.group(1).strip()

    # 核心句：72.8%岗位拿￥20-50K/月，年薪￥24-60W
    m = re.search(r"(\d+\.?\d*)%岗位拿￥?(\d+\.?\d*)-(\d+\.?\d*)K/月，?年薪￥?(\d+\.?\d*)-(\d+\.?\d*)W", text)
    if m:
        row.monthly_low = float(m.group(2)) * 1000
        row.monthly_high = float(m.group(3)) * 1000
        row.annual_low = float(m.group(4)) * 10000
        row.annual_high = float(m.group(5)) * 10000
        row.annual_avg = (row.annual_low + row.annual_high) / 2
    # 样本数：数据统计来自近一年 26967 份样本（2026-09 实测格式）
    m2 = re.search(r"(?:取自|来自近一年)\s*(\d+)\s*份样本", text)
    if m2:
        row.sample_count = int(m2.group(1))

    # 学历/经验分段：句子式"按学历统计，中专工资￥11.4K"/"按经验，应届生工资￥14.1K"
    seg = {k: float(v) * 1000 for k, v in re.findall(
        r"(中专|大专|本科|硕士|博士|应届生|1-3年|3-5年|5-10年|10年以上)工资￥(\d+\.?\d*)K", text)}
    # 表格式：按学历统计\x00中专\x00￥11.4K（隐藏段显示 ***，不匹配 ￥ 模式自然跳过）
    for kind in ("按学历统计", "按经验统计"):
        for m3 in re.finditer(re.escape(kind) + r"\x00((?:(?!\x00).){1,15}?)\x00￥(\d+\.?\d*)K", flat):
            seg.setdefault(m3.group(1), float(m3.group(2)) * 1000)
    if seg:
        row.extra["segment_wages"] = seg

    # 城市内区域分段："南山区\x00￥30.6K\x0033.3%(9269)"
    dist = re.findall(
        r"([一-龥]{2,6}(?:区|市))\x00￥(\d+\.?\d*)K\x00(\d+\.?\d*)%(?:\((\d+)\))?", flat
    )
    if dist:
        row.extra["city_district_wages"] = [
            {"district": d, "monthly_k": float(k), "pct": float(p), "jobs": int(j) if j else None}
            for d, k, p, j in dist[:12]
        ]

    if row.annual_avg is None and not row.extra:
        return None
    return row


def parse_jobui_company_subpage(html: str, url: str) -> SalaryRow | None:
    """解析 jobui 公司×岗位薪酬子页 /company/{id}/salary/j/{slug}/（2026-09 实测格式）。

    核心句：同程旅行 产品经理 薪酬区间: 8K - 50K，其中85.5%的岗位拿￥20-50K
    样本句：取自近一年 131 个相关岗位
    地区表：苏州\x00￥25.1K\x0043.5%(57)

    薪酬口径：区间 (low+high)/2 会系统性虚高（"20-50K" 实际 85% 岗位在 20-50K
    但集中于下半段），优先用分布区间 × 占比加权；无分布数据才退回区间中点。
    """
    m = re.search(r"jobui\.com/company/(\d+)/salary/j/([a-z]+)/", url)
    if not m:
        return None
    text = _strip_html(html)
    flat = re.sub(r"[\n\r\t ]+", "\x00", text)

    row = SalaryRow(source="jobui_company", source_url=url)

    m = re.search(r"([一-龥A-Za-z0-9·]{2,25})\s*薪酬区间[：:]\s*￥?(\d+\.?\d*)K?\s*-\s*￥?(\d+\.?\d*)K", text)
    if not m:
        return None
    row.position = m.group(1).strip()
    row.monthly_low = float(m.group(2)) * 1000
    row.monthly_high = float(m.group(3)) * 1000

    # 分布加权：页面有 6 段桶（8-10K...50K以上），但 20-30K/30-50K 等热门桶
    # 占比隐藏（***），只露「最多岗位拿 X-YK」众数句 + 「其中86.1%拿￥20-50K」汇总句。
    # 策略：可见桶按占比取中点；隐藏质量 = 总% - 可见%，全部归到众数桶；
    # 「50K以上」按 50-65K 估计。加权均值远比全区间中点接近真实。
    i_rng = text.find("薪酬区间")
    flat_seg = re.sub(r"[\n\r\t ]+", "\x00", text[i_rng:i_rng + 2200]) if i_rng >= 0 else ""
    pairs = re.findall(
        r"(?:\x00|^)(\d+\.?\d*)%\x00+(\d+\.?\d*)-(\d+\.?\d*)K", flat_seg)
    all_buckets = re.findall(r"\x00(\d+\.?\d*)-(\d+\.?\d*)K\x00", flat_seg)
    m_mode = re.search(r"最多岗位拿\s*(\d+\.?\d*)-(\d+\.?\d*)K", text[i_rng:i_rng + 3000]) if i_rng >= 0 else None
    m_total = re.search(r"其中(\d+\.?\d*)%的岗位拿￥?(\d+\.?\d*)-(\d+\.?\d*)K", text)

    if all_buckets:
        vis = {f"{lo}-{hi}K": float(p) for p, lo, hi in pairs}
        seen = [f"{lo}-{hi}K" for lo, hi in all_buckets]
        # 去重保序（同一段区间可能重复出现）
        seen = list(dict.fromkeys(seen))
        hidden_names = [b for b in seen if b not in vis]
        mode_name = f"{m_mode.group(1)}-{m_mode.group(2)}K" if m_mode else (hidden_names[0] if hidden_names else None)
        # 50K以上 开区间按 50-65K 估计
        def mid_of(name: str) -> float:
            m = re.match(r"(\d+)-(\d+)K", name)
            if m:
                return (float(m.group(1)) + float(m.group(2))) / 2
            m = re.match(r"(\d+)K以上", name)
            return float(m.group(1)) + 7.5 if m else 0.0
        weighted_sum, weight_tot = 0.0, 0.0
        for name, pct in vis.items():
            weighted_sum += mid_of(name) * pct
            weight_tot += pct
        total_pct = float(m_total.group(1)) if m_total else weight_tot
        hidden_mass = max(total_pct - weight_tot, 0.0)
        if hidden_mass > 0 and mode_name:
            weighted_sum += mid_of(mode_name) * hidden_mass
            weight_tot += hidden_mass
        if weight_tot > 0:
            monthly_mid = weighted_sum / weight_tot * 1000  # K → 元
            row.annual_low = monthly_mid * 12 * 0.85
            row.annual_high = monthly_mid * 12 * 1.15
            row.annual_avg = monthly_mid * 12
            row.extra["wage_basis"] = "distribution_weighted"
            row.extra["wage_buckets"] = {**vis, mode_name: hidden_mass} if hidden_mass else vis
    elif m_total:
        # 只有汇总句，无桶表：用汇总区间中点（比全区间中点窄）
        dlo, dhi = float(m_total.group(2)), float(m_total.group(3))
        monthly_mid = (dlo + dhi) / 2 * 1000
        row.annual_low = monthly_mid * 12 * 0.9
        row.annual_high = monthly_mid * 12 * 1.1
        row.annual_avg = monthly_mid * 12
        row.extra["wage_basis"] = "distribution_summary"
    else:
        row.annual_low = row.monthly_low * 12
        row.annual_high = row.monthly_high * 12
        row.annual_avg = (row.annual_low + row.annual_high) / 2
        row.extra["wage_basis"] = "range_midpoint"

    m2 = re.search(r"取自近一年\s*(\d+)\s*个相关岗位", text)
    if m2:
        row.sample_count = int(m2.group(1))

    # 主要招聘地区：苏州\x00￥25.1K\x0043.5%(57)
    locs = re.findall(
        r"([一-龥]{2,8})\x00￥(\d+\.?\d*)K\x00(\d+\.?\d*)%(?:\((\d+)\))?", flat)
    if locs:
        row.extra["company_city_wages"] = [
            {"city": c, "monthly_k": float(k), "pct": float(p), "jobs": int(j) if j else None}
            for c, k, p, j in locs[:15]
        ]
        # 页面若未标城市，取占比最高的招聘地区作为该行 city
        top = max(row.extra["company_city_wages"], key=lambda x: x["pct"])
        row.city = top["city"]

    m3 = re.search(r"招聘地区[：:]\s*主要分布在([一-龥A-Za-z，,、 ]{2,60})", text)
    if m3:
        row.extra["main_cities"] = [
            c for c in re.split(r"[，,、]", m3.group(1)) if c.strip()
        ][:6]

    if row.annual_avg is None:
        return None
    return row


# ---------- 源发现：岗位 → jobui URL 模式 ----------


def jobui_salary_url(city_en: str, position: str) -> str:
    """jobui URL 规律：/salary/{city}-{position拼音}/。拼音转换不可靠，优先搜索发现。"""
    raise NotImplementedError("use discover_jobui_urls instead")


def discover_jobui_urls(position: str, city_en: str = "shenzhen", max_results: int = 3) -> list[str]:
    """SearxNG 搜索发现 jobui 薪酬页。"""
    urls = []
    for r in searx_search(f"jobui.com salary {city_en} {position} 工资", pages=1):
        u = r.get("url", "")
        if re.match(rf"https?://www\.jobui\.com/salary/{city_en}-", u):
            urls.append(u)
        if len(urls) >= max_results:
            break
    return list(dict.fromkeys(urls))


def raw_dump(source: str, url: str, payload: dict):
    d = RAW_DIR / source
    d.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date().isoformat()
    with open(d / f"{today}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"url": url, "ts": datetime.now(timezone.utc).isoformat(), **payload}, ensure_ascii=False) + "\n")
