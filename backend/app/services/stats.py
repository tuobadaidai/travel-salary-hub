"""分位数与趋势计算核心。SQL 只做过滤/分组，numpy 算分位数。"""

import numpy as np
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
              country: str | None, level: str | None = None, position: str | None = None):
    q = db.query(
        SalaryRecord.city,
        SalaryRecord.country,
        SalaryRecord.company_type,
        SalaryRecord.job_family_id,
        SalaryRecord.collect_date,
        METRIC,
        SalaryRecord.level,
        SalaryRecord.position_norm,
    ).filter(METRIC.isnot(None))
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
                       position: str | None = None) -> list[dict]:
    rows = _filtered(db, city, company_type, job_family_id, date_from, date_to, country,
                     level, position)
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
    """
    from sqlalchemy import text as _text

    pos_norm = position.strip()
    market: dict[str, dict[str, dict]] = {}
    rows = db.query(SalaryRecord).filter(
        SalaryRecord.position_norm.contains(pos_norm), METRIC.isnot(None))
    if levels:
        rows = rows.filter(SalaryRecord.level.in_(levels))
    if cities:
        rows = rows.filter(SalaryRecord.city.in_(cities))
    for r in rows.all():
        lv, ct = r.level or "未分类", r.city or "未知"
        market.setdefault(lv, {}).setdefault(ct, []).append(float(r.annual_salary_avg_base))

    # DIDA 内部（dida_payroll 表，职务模糊匹配）
    dida: dict[str, dict[str, dict]] = {}
    try:
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
                  city: str | None = None, limit: int = 50) -> list[dict]:
    """穿透：按岗位/级别/城市筛选原始记录（证据链）。"""
    q = db.query(SalaryRecord).filter(METRIC.isnot(None))
    if position:
        q = q.filter(SalaryRecord.position_norm.contains(position.strip()))
    if level:
        q = q.filter(SalaryRecord.level == level)
    if city:
        q = q.filter(SalaryRecord.city == city)
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
