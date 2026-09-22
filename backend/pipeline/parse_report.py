"""解析第三方薪酬报告 PDF（如 Michael Page 中国大陆薪酬报告）。

报告结构：按行业分章，每章 1-2 页薪酬表，行格式：
    岗位名  min - max   （单位：千元人民币/年，全国平均）
本模块只负责抽文本 + 正则识别，入库逻辑在调用方。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pdfplumber

_LINE_PAT = re.compile(r"^(.+?)\s+(\d{2,4}(?:,\d{3})*)\s*[-–]\s*(\d{2,4}(?:,\d{3})*)\s*$")
_SKIP_KEYWORDS = (
    "全国平均", "薪酬表", "基本薪资", "Michael Page", "中国大陆",
    "查看该领域", "关键技能", "热门职位", "高薪职位", "有招聘需求",
    "联系我们", "搜索理想职位", "查看该",
)


def infer_level(title: str) -> str:
    """从岗位名推断市场 level。粗粒度，宁可错分不可漏分。"""
    t = title
    if re.search(r"VP|副总裁|首席|CFO|COO|CTO|CMO|CPO|CHRO|CEO|负责人|主管合伙人", t):
        return "VP"
    if "总监" in t:
        return "总监"
    if "高级" in t:
        return "高级"
    if "经理" in t:
        return "经理"
    if "专员" in t or "助理" in t:
        return "专员"
    # 工程师/分析师/顾问等无明显级别词 → 按中级处理，归"主管"档
    return "主管"


def parse_pdf(pdf_path: str | Path) -> list[dict]:
    """解析 PDF，返回 [{position, level, low_k, high_k}, ...]（单位千元/年）。"""
    rows = []
    seen = set()
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            for line in txt.split("\n"):
                line = line.strip()
                m = _LINE_PAT.match(line)
                if not m:
                    continue
                pos = m.group(1).strip()
                lo = int(m.group(2).replace(",", ""))
                hi = int(m.group(3).replace(",", ""))
                if any(k in pos for k in _SKIP_KEYWORDS):
                    continue
                if len(pos) < 2 or len(pos) > 30:
                    continue
                if lo > hi or lo < 1 or hi > 10_000_000:
                    continue
                key = (pos, lo, hi)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "position": pos,
                    "level": infer_level(pos),
                    "raw_low": lo,
                    "raw_high": hi,
                })

    # 自动推断单位：按所有行的中位数判断
    # 千元：中位数 50-5000（如 300-600）
    # 万元：中位数 5-200（如 30-60）
    # 元：中位数 > 10000（如 300000-600000）
    if not rows:
        return []
    med = sorted((r["raw_low"] + r["raw_high"]) / 2 for r in rows)[len(rows) // 2]
    if med < 20:
        unit = "wan"  # 万元
        mult = 10000
    elif med > 10000:
        unit = "yuan"  # 元
        mult = 1
    else:
        unit = "k"  # 千元
        mult = 1000
    for r in rows:
        r["low_k"] = round(r["raw_low"] * mult / 1000, 1)  # 统一存千元
        r["high_k"] = round(r["raw_high"] * mult / 1000, 1)
        r["unit_detected"] = unit
    return rows


def dedup_hash(position: str, city: str, company: str, low: float, high: float) -> str:
    raw = "|".join([position, city, company, f"{low:.0f}", f"{high:.0f}"]).encode()
    return hashlib.md5(raw).hexdigest()
