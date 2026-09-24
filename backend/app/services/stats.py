"""分位数与趋势计算核心。SQL 只做过滤/分组，numpy 算分位数。"""

import re

import numpy as np
from sqlalchemy import bindparam, or_
from sqlalchemy.orm import Session

from app.models import Company, JobFamily, SalaryRecord

# 跨国对比统一用 CNY 折算口径
METRIC = SalaryRecord.annual_salary_avg_base
GROUP_COLS = {
    "city": SalaryRecord.city,
    "country": SalaryRecord.country,
    "company_type": SalaryRecord.company_type,
    "job_family": SalaryRecord.job_family_id,
    "level": SalaryRecord.level,
    "position": SalaryRecord.position_norm,
}

_LEVEL_ORDER = ["专员", "高级", "主管", "经理", "总监", "VP"]

# months>13 的记录（15/18/20 薪等异常口径）不计入分位数，避免离群拉偏
_VALID_MONTHS = or_(SalaryRecord.months.is_(None), SalaryRecord.months <= 13)

# DIDA 国内驻地（其余 location 归海外舱）
CN_LOCATIONS = [
    "深圳", "长沙", "上海", "重庆", "北京", "成都", "广州", "杭州",
    "南京", "大连", "潍坊", "平湖",
]


def _market_filter(q, include_overseas: bool = False):
    """市场记录统一过滤：口径月份有效 + 默认排除海外。"""
    q = q.filter(METRIC.isnot(None), _VALID_MONTHS)
    if not include_overseas:
        q = q.filter(SalaryRecord.country == "CN")
    return q

# DIDA 职级 → 等效市场 level（与 pipeline/import_dida_payroll.py GRADE_TO_LEVEL 保持一致）
GRADE_TO_LEVEL = {
    "O1": "专员", "O2": "专员", "O3": "高级", "O4": "主管",
    "P0": "专员", "P1": "专员", "P2": "高级", "P3": "高级",
    "P4": "主管", "P5": "经理", "P6": "经理", "P7": "总监",
    "P8": "总监", "P9": "VP",
    "M4": "总监", "M5": "VP",
}
# DIDA 职级元数据（code → 标准岗位名/序列/展示顺序）
GRADE_META = [
    {"code": "P0", "title": "专员",     "seq": "P"},
    {"code": "P1", "title": "高级专员", "seq": "P"},
    {"code": "P2", "title": "主管",     "seq": "P"},
    {"code": "P3", "title": "经理",     "seq": "P"},
    {"code": "P4", "title": "高级经理", "seq": "P"},
    {"code": "P5", "title": "资深经理", "seq": "P"},
    {"code": "P6", "title": "总监",     "seq": "P"},
    {"code": "P7", "title": "高级总监", "seq": "P"},
    {"code": "P8", "title": "资深总监", "seq": "P"},
    {"code": "O1", "title": "初级专员", "seq": "O"},
    {"code": "O2", "title": "中级专员", "seq": "O"},
    {"code": "O3", "title": "高级专员", "seq": "O"},
    {"code": "O4", "title": "组长",     "seq": "O"},
    {"code": "M4", "title": "SVP/VP",   "seq": "M"},
    {"code": "M5", "title": "CEO/总裁", "seq": "M"},
]


def _quantiles(values: list[float]) -> dict:
    arr = np.array(values, dtype=float)
    p25, p50, p75, p90 = np.quantile(arr, [0.25, 0.5, 0.75, 0.9])
    return {
        "count": len(values),
        "p25": round(float(p25)),
        "p50": round(float(p50)),
        "p75": round(float(p75)),
        "p90": round(float(p90)),
        "reliable": len(values) >= 5,
    }


def _filtered(db: Session, city: str | None, company_type: str | None,
              job_family_id: int | None, date_from: str | None, date_to: str | None,
              country: str | None, level: str | None = None, position: str | None = None,
              include_overseas: bool = False):
    q = db.query(
        SalaryRecord.city,
        SalaryRecord.country,
        SalaryRecord.company_type,
        SalaryRecord.job_family_id,
        SalaryRecord.collect_date,
        METRIC,
        SalaryRecord.level,
        SalaryRecord.position_norm,
    )
    q = _market_filter(q, include_overseas=include_overseas)
    if city:
        q = q.filter(SalaryRecord.city.in_(city.split(",")))
    if country:
        q = q.filter(SalaryRecord.country.in_(country.split(",")))
    if company_type:
        q = q.filter(SalaryRecord.company_type == company_type)
    if job_family_id:
        q = q.filter(SalaryRecord.job_family_id == job_family_id)
    if level:
        q = q.filter(SalaryRecord.level.in_(level.split(",")))
    if position:
        q = q.filter(SalaryRecord.position_norm.in_(position.split(",")))
    if date_from:
        q = q.filter(SalaryRecord.collect_date >= date_from)
    if date_to:
        q = q.filter(SalaryRecord.collect_date <= date_to)
    return q.all()


def quantiles_by_group(db: Session, group_by: str, city: str | None = None,
                       company_type: str | None = None, job_family_id: int | None = None,
                       date_from: str | None = None, date_to: str | None = None,
                       country: str | None = None, level: str | None = None,
                       position: str | None = None,
                       include_overseas: bool = False) -> list[dict]:
    rows = _filtered(db, city, company_type, job_family_id, date_from, date_to, country,
                     level, position, include_overseas=include_overseas)
    gi = {"city": 0, "country": 1, "company_type": 2, "job_family": 3,
          "level": 6, "position": 7}[group_by]
    groups: dict[str, list[float]] = {}
    for r in rows:
        key = str(r[gi]) if r[gi] is not None else "未分类"
        groups.setdefault(key, []).append(float(r[5]))
    out = [{"group_key": k, **_quantiles(v)} for k, v in groups.items()]
    if group_by == "level":
        order = {lv: i for i, lv in enumerate(_LEVEL_ORDER)}
        out.sort(key=lambda x: order.get(x["group_key"], 99))
    else:
        out.sort(key=lambda x: x["group_key"])
    return out


def benchmark_matrix(db: Session, position: str, levels: list[str] | None = None,
                     cities: list[str] | None = None) -> dict:
    """岗位对标矩阵：岗位 × (级别 × 城市) 的市场分位数 + DIDA 内部对照。

    返回 {levels: [...], cities: [...], market: {level: {city: {...quantiles}}},
          dida: {level: {city: {count, p50}}}}

    匹配策略：position_norm 精确匹配优先；不足时放宽为「前缀+同长近义」，
    但绝不包含「资深/高级」差异（查「产品经理」不得混入「资深产品经理」）。
    """
    from sqlalchemy import text as _text

    pos_norm = position.strip().lower()
    market: dict[str, dict[str, dict]] = {}

    def _query(norm_kw: str):
        q = db.query(SalaryRecord).filter(SalaryRecord.position_norm == norm_kw)
        q = _market_filter(q)
        if levels:
            q = q.filter(SalaryRecord.level.in_(levels))
        if cities:
            q = q.filter(SalaryRecord.city.in_(cities))
        return q.all()

    rows = _query(pos_norm)
    matched_kind = "exact"
    if not rows:
        # 放宽：LIKE 前缀，但排除因「资深/高级/助理」前缀差异带来的混岗
        near_re = re.compile(r"^(资深|高级|初级|助理)")
        cand = db.query(SalaryRecord).filter(SalaryRecord.position_norm.contains(pos_norm))
        cand = _market_filter(cand)
        if levels:
            cand = cand.filter(SalaryRecord.level.in_(levels))
        if cities:
            cand = cand.filter(SalaryRecord.city.in_(cities))
        rows = [r for r in cand.all()
                if near_re.sub("", r.position_norm or "") == pos_norm]
        if rows:
            matched_kind = "near"
    for r in rows:
        lv, ct = r.level or "未分类", r.city or "未知"
        market.setdefault(lv, {}).setdefault(ct, []).append(float(r.annual_salary_avg_base))

    # DIDA 内部（dida_payroll 表，职务精确匹配优先、模糊兜底）
    dida: dict[str, dict[str, dict]] = {}
    try:
        prows = db.execute(_text(
            "SELECT level, location, monthly_cny FROM dida_payroll "
            "WHERE title = :kw"), {"kw": pos_norm}).fetchall()
        if not prows:
            prows = db.execute(_text(
                "SELECT level, location, monthly_cny FROM dida_payroll "
                "WHERE title LIKE :kw"), {"kw": f"%{pos_norm}%"}).fetchall()
        for lv, loc, monthly in prows:
            dida.setdefault(lv or "未分类", {}).setdefault(loc or "未知", []).append(float(monthly) * 12)
    except Exception:
        pass  # 表不存在时只出市场数据

    def _mk(groups: dict) -> dict:
        return {
            lv: {ct: _quantiles(vals) for ct, vals in cts.items()}
            for lv, cts in groups.items()
        }

    all_levels = [lv for lv in _LEVEL_ORDER if lv in market or lv in dida]
    all_cities = sorted({c for lv in all_levels for src in (market, dida)
                         for c in src.get(lv, {})})
    return {
        "position": pos_norm,
        "match_kind": matched_kind,
        "levels": all_levels,
        "cities": all_cities,
        "market": _mk(market),
        "dida": _mk(dida),
    }


def trend_by_month(db: Session, city: str | None = None, company_type: str | None = None,
                   job_family_id: int | None = None, country: str | None = None) -> list[dict]:
    rows = _filtered(db, city, company_type, job_family_id, None, None, country)
    groups: dict[str, list[float]] = {}
    for r in rows:
        groups.setdefault(str(r[4])[:7], []).append(float(r[5]))
    return [{"month": m, **_quantiles(groups[m])} for m in sorted(groups)]


def positions_list(db: Session) -> list[dict]:
    """可供对标的岗位清单（position_norm 去重 + 记录数 + 覆盖级别）。"""
    from collections import Counter
    rows = db.query(
        SalaryRecord.position_norm,
        SalaryRecord.level,
    ).filter(SalaryRecord.position_norm.isnot(None)).all()
    c = Counter(rows)
    by_pos: dict[str, Counter] = {}
    for (p, lv), n in c.items():
        by_pos.setdefault(p, Counter())[lv or "未分类"] = n
    return [
        {"position": p, "count": sum(lvs.values()),
         "levels": [lv for lv in _LEVEL_ORDER if lvs.get(lv)]}
        for p, lvs in sorted(by_pos.items(), key=lambda x: -sum(x[1].values()))
    ]


def meta_full(db: Session) -> dict:
    cities = sorted({r[0] for r in db.query(SalaryRecord.city).distinct() if r[0]})
    countries = sorted({r[0] for r in db.query(SalaryRecord.country).distinct() if r[0]})
    families = [
        {"id": jf.id, "code": jf.code, "name": jf.name}
        for jf in db.query(JobFamily).order_by(JobFamily.sort_order).all()
    ]
    latest = db.query(SalaryRecord.collect_date).order_by(SalaryRecord.collect_date.desc()).first()
    levels = [lv for lv in _LEVEL_ORDER
              if db.query(SalaryRecord).filter(SalaryRecord.level == lv).first()]
    return {
        "cities": cities,
        "countries": countries,
        "job_families": families,
        "company_types": ["OTA", "B2B", "traditional_agency", "other"],
        "levels": levels,
        "latest_collect_date": latest[0] if latest else None,
        "total_records": db.query(SalaryRecord).count(),
    }


def cross_heatmap(db: Session, row_dim: str = "job_family", col_dim: str = "city") -> dict:
    """交叉热力图：两维度交叉的 P50 矩阵 + 记录数。"""
    rows = _filtered(db, None, None, None, None, None, None)
    di = {"city": 0, "country": 1, "company_type": 2, "job_family": 3, "level": 6, "position": 7}
    ri, ci = di[row_dim], di[col_dim]
    fam_names = {jf.id: jf.name for jf in db.query(JobFamily).all()}

    def key_of(val, dim: str) -> str:
        if val is None:
            return "未分类"
        if dim == "job_family":
            return fam_names.get(val, str(val))
        return str(val)

    cells: dict[tuple[str, str], list[float]] = {}
    for r in rows:
        cells.setdefault((key_of(r[ri], row_dim), key_of(r[ci], col_dim)), []).append(float(r[5]))
    row_keys = sorted({k[0] for k in cells})
    col_keys = sorted({k[1] for k in cells})
    grid = []
    for rk in row_keys:
        row = []
        for ck in col_keys:
            vals = cells.get((rk, ck))
            if vals:
                q = _quantiles(vals)
                row.append({"p50": q["p50"], "count": q["count"], "reliable": q["reliable"]})
            else:
                row.append(None)
        grid.append(row)
    return {"row_dim": row_dim, "col_dim": col_dim, "row_keys": row_keys,
            "col_keys": col_keys, "grid": grid}


def drill_records(db: Session, position: str | None = None, level: str | None = None,
                  city: str | None = None, limit: int = 50,
                  job_family_id: int | None = None, company_type: str | None = None) -> list[dict]:
    """穿透：按岗位/级别/城市等筛选原始记录（证据链）。"""
    q = db.query(SalaryRecord).filter(METRIC.isnot(None))
    if position:
        q = q.filter(SalaryRecord.position_norm.contains(position.strip()))
    if level:
        q = q.filter(SalaryRecord.level == level)
    if city:
        q = q.filter(SalaryRecord.city == city)
    if job_family_id:
        q = q.filter(SalaryRecord.job_family_id == job_family_id)
    if company_type:
        q = q.filter(SalaryRecord.company_type == company_type)
    rows = q.order_by(METRIC.desc()).limit(limit).all()
    return [
        {
            "id": r.id, "position": r.position, "company_name": r.company_name,
            "city": r.city, "country": r.country, "currency": r.currency,
            "salary_range": r.salary_range,
            "annual_cny": round(float(r.annual_salary_avg_base)) if r.annual_salary_avg_base else None,
            "level": r.level, "source": r.source, "source_url": r.source_url,
            "collect_date": r.collect_date, "sample_count": r.sample_count,
        }
        for r in rows
    ]


# ============================================================
# DIDA 职级维度对标（apple-to-apple）
# ============================================================

# title 修饰词剥离：归一化到"岗位基名"（高级技术产品经理 → 产品经理）
_TITLE_MODIFIERS = re.compile(r"^(资深|高级|中级|初级|首席|技术|后台|前端|智能)")


def _title_base(title: str) -> str:
    t = (title or "").strip()
    prev = None
    while prev != t:
        prev = t
        t = _TITLE_MODIFIERS.sub("", t)
    return t or title


def dida_title_match(db: Session, title_kw: str) -> list[str]:
    """岗位关键词 → dida_payroll 匹配 title 集合（族内收敛）。

    只保留「基名相同」的 title（高级技术产品经理 与 产品经理 同族）。
    基名不同的一律不收（技术经理 与 产品经理 不同族），无匹配返回空。
    """
    from sqlalchemy import text as _text
    kw = _title_base(title_kw)
    rows = db.execute(_text(
        "SELECT DISTINCT title FROM dida_payroll WHERE title LIKE :kw"),
        {"kw": f"%{kw}%"}).fetchall()
    return [r[0] for r in rows if r[0] and _title_base(r[0]) == kw]


def grades_meta(db: Session) -> list[dict]:
    """返回所有 DIDA 职级 + 在册人数。"""
    from sqlalchemy import text as _text
    rows = db.execute(_text(
        "SELECT grade, COUNT(*) AS n FROM dida_payroll "
        "GROUP BY grade"
    )).fetchall()
    cnt = {g: n for g, n in rows}
    out = []
    for meta in GRADE_META:
        out.append({
            "code": meta["code"],
            "title": meta["title"],
            "seq": meta["seq"],
            "market_level": GRADE_TO_LEVEL.get(meta["code"]),
            "count": cnt.get(meta["code"], 0),
        })
    return out


def benchmark_by_grade(db: Session, position: str,
                      cities: list[str] | None = None) -> dict:
    """按 DIDA 职级（P0-P8/O1-O4/M4-M5）做行轴的对标矩阵（AD-1/AD-5 三层降级）。

    - dida 主轴：dida_payroll.grade × location（族内 title 收敛）
    - market 分层参照：
      tier1 = 本 grade×本城市 DIDA 样本≥5（直接对标市场同 grade 等效 level×城市）
      tier2 = 本 grade 全国 DIDA 样本≥5（市场参照降为全国同 level）
      tier3 = 市场级别带参照（pos×level 全国聚合，135 格中 41 格≥5）
    返回 {position, grades, cities, cells: {grade: {city: {tier, dida, market_ref, gap_pct}}},
          market, dida, market_band, national_reference}
    """
    from sqlalchemy import text as _text
    pos_norm = position.strip().lower()

    # 1) DIDA 侧：title 族内收敛 → grade × location 聚合年化薪酬
    dida_groups: dict[str, dict[str, list[float]]] = {}
    try:
        titles = dida_title_match(db, pos_norm)
        if titles:
            cn_ph = ",".join(f":cn{i}" for i in range(len(CN_LOCATIONS)))
            cn_params = {f"cn{i}": c for i, c in enumerate(CN_LOCATIONS)}
            prows = db.execute(_text(
                f"SELECT grade, location, monthly_cny FROM dida_payroll "
                f"WHERE title IN :titles AND location IN ({cn_ph})"
            ).bindparams(bindparam("titles", expanding=True)), {"titles": titles, **cn_params}).fetchall()
        else:
            prows = []
        for grade, loc, monthly in prows:
            if not grade or not loc or monthly is None:
                continue
            dida_groups.setdefault(grade, {}).setdefault(loc, []).append(float(monthly) * 12)
    except Exception:
        pass

    # 2) 市场侧：pos×level×城市（tier1 参照）+ pos×level 全国（tier2/3 带参照）
    # 时间窗口：只取最近 12 个月，避免陈旧数据拉低分位
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=365)).date().isoformat()
    base_q = db.query(
        SalaryRecord.level, SalaryRecord.city, METRIC
    ).filter(
        SalaryRecord.position_norm == pos_norm,
        ~SalaryRecord.source.like("report:%"),
        SalaryRecord.collect_date >= cutoff,
    )
    base_q = _market_filter(base_q)
    if cities:
        base_q = base_q.filter(SalaryRecord.city.in_(cities))
    market_groups: dict[str, dict[str, list[float]]] = {}
    market_band: dict[str, list[float]] = {}
    for lv, ct, val in base_q.all():
        if not lv or val is None:
            continue
        market_band.setdefault(lv, []).append(float(val))
        if ct:
            market_groups.setdefault(lv, {}).setdefault(ct, []).append(float(val))

    # 2b) 报告基准（方案 B）：source like 'report:%'，单独聚合，不参与 gap
    report_groups: dict[str, list[float]] = {}
    report_labels: set[str] = set()
    rq = db.query(
        SalaryRecord.level, METRIC, SalaryRecord.source
    ).filter(
        SalaryRecord.position_norm == pos_norm,
        METRIC.isnot(None),
        SalaryRecord.source.like("report:%"),
    )
    for lv, val, src in rq.all():
        if not lv or val is None:
            continue
        report_groups.setdefault(lv, []).append(float(val))
        if src:
            report_labels.add(src)

    # 3) 组 cells：每 grade × 城市 三层降级
    def _band_q(lv: str) -> dict | None:
        vals = market_band.get(lv)
        return _quantiles(vals) if vals else None

    cells: dict[str, dict[str, dict]] = {}
    for gmeta in GRADE_META:
        g = gmeta["code"]
        equiv = GRADE_TO_LEVEL.get(g)
        # 全国样本 = 该 grade 全部国内城市合并（tier2 判据）
        nat_vals = [v for cts in dida_groups.get(g, {}).values() for v in cts]
        nat_q = _quantiles(nat_vals) if nat_vals else None
        band = _band_q(equiv) if equiv else None
        g_cells: dict[str, dict] = {}
        city_set = sorted(dida_groups.get(g, {})) or (["全国"] if nat_vals else [])
        for ct in city_set:
            cvals = dida_groups.get(g, {}).get(ct, [])
            cq = _quantiles(cvals) if cvals else None
            mvals = market_groups.get(equiv, {}).get(ct) if equiv else None
            mq = _quantiles(mvals) if mvals else None
            if cq and cq["reliable"]:
                # tier1：本 grade×本城市 ≥5，直接对标市场同城同 level
                tier, ref, dq = 1, mq, cq
            elif nat_q and nat_q["reliable"]:
                # tier2：城市样本不足但全国 ≥5 → 展示全国 P50，市场参照降为全国同 level 带
                tier, ref, dq = 2, band, nat_q
            else:
                # tier3：样本不足 → 保留低样本 DIDA（reliable=false 灰显），只给市场带参照
                tier, ref, dq = 3, band, cq
            gap = None
            if dq and dq["reliable"] and ref and ref.get("reliable") and ref.get("p50"):
                gap = round((dq["p50"] - ref["p50"]) / ref["p50"], 3)
            g_cells[ct] = {"tier": tier, "dida": dq, "market_ref": ref, "gap_pct": gap}
        if g_cells:
            cells[g] = g_cells

    # 4) 城市并集（不过滤：前端按 cells 有无数据渲染，避免筛选后城市清单缩水）
    all_cities = sorted({ct for g in cells for ct in cells[g]} |
                        {c for lv in market_groups for c in market_groups[lv]})

    def _mk(src: dict[str, dict[str, list[float]]]) -> dict:
        out = {}
        for g, cts in src.items():
            out[g] = {ct: _quantiles(vals) for ct, vals in cts.items()}
        return out

    return {
        "position": pos_norm,
        "grades": grades_meta(db),
        "cities": all_cities,
        "cells": cells,
        "market": _mk(market_groups),
        "dida": _mk(dida_groups),
        "market_band": {lv: _quantiles(v) for lv, v in market_band.items()},
        "national_reference": {
            "labels": sorted(report_labels),
            "by_grade": {
                g: _quantiles(report_groups[equiv])
                for gmeta in GRADE_META
                for g, equiv in [(gmeta["code"], GRADE_TO_LEVEL.get(gmeta["code"]))]
                if equiv and equiv in report_groups
            },
        },
    }


def overseas_stats(db: Session, title_kw: str | None = None) -> dict:
    """海外驻地视图（F6，SPEC S3）。

    - 内部：dida_payroll location 不在 CN_LOCATIONS 的记录，按 国家 × level 聚合
      （monthly_cny 已折算 CNY；cur_dist 给币种分布）
    - 市场：salary_records country != 'CN'（search_snippet 聚合，低置信）单独返回
    """
    from sqlalchemy import text as _text

    cn_ph = ",".join(f":cn{i}" for i in range(len(CN_LOCATIONS)))
    params: dict = {f"cn{i}": c for i, c in enumerate(CN_LOCATIONS)}
    where_extra = ""
    if title_kw:
        kw = "%" + title_kw.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where_extra = " AND title LIKE :kw ESCAPE '\\'"
        params["kw"] = kw

    # 1) 内部：国家 × level 聚合
    prows = db.execute(_text(
        f"SELECT location, level, monthly_cny, currency, grade FROM dida_payroll "
        f"WHERE location NOT IN ({cn_ph}){where_extra}"
    ), params).fetchall()
    by_country: dict[str, dict[str, list[float]]] = {}
    country_meta: dict[str, dict] = {}
    for loc, level, monthly, cur, grade in prows:
        # count 在 monthly 缺失前累加：总人数口径不丢人
        cm = country_meta.setdefault(loc, {"count": 0, "currencies": {}})
        cm["count"] += 1
        if cur:
            cm["currencies"][cur] = cm["currencies"].get(cur, 0) + 1
        if monthly is None:
            continue
        m = by_country.setdefault(loc, {}).setdefault(level or "未知", [])
        m.append(float(monthly) * 12)

    countries_out = []
    for loc, levels in sorted(by_country.items(), key=lambda kv: -sum(len(v) for v in kv[1].values())):
        cm = country_meta.get(loc, {"count": 0, "currencies": {}})
        countries_out.append({
            "country": loc,
            "count": cm["count"],
            "currencies": cm["currencies"],
            "by_level": {lv: _quantiles(vals) for lv, vals in sorted(levels.items())},
        })

    # 2) 市场：海外 JD 聚合记录（低置信）
    mq = db.query(
        SalaryRecord.city, SalaryRecord.country, SalaryRecord.position_norm,
        METRIC, SalaryRecord.currency,
    ).filter(
        SalaryRecord.country.isnot(None),
        SalaryRecord.country != "CN",
        METRIC.isnot(None),
        _VALID_MONTHS,
    )
    if title_kw:
        esc = title_kw.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        mq = mq.filter(SalaryRecord.position_norm.like(f"%{esc}%"))
    market_rows = mq.all()
    m_by_city: dict[str, list[float]] = {}
    for _ct, _co, _pn, val, _cur in market_rows:
        if val is not None:
            m_by_city.setdefault(_ct or _co or "未知", []).append(float(val))

    return {
        "internal": {
            "countries": countries_out,
            "total": sum(c["count"] for c in countries_out),
        },
        "market": {
            "by_city": {ct: _quantiles(vals) for ct, vals in sorted(m_by_city.items())},
            "total": len(market_rows),
        },
    }
