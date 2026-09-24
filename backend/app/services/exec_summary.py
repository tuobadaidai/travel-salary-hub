"""高管薪酬分析聚合服务（首页重构，麦肯锡人效分析框架）。

三大板块：
1. 薪酬水位定位 — DIDA 各级别 P25/P50/P75 vs 市场分位带（对标决策）
2. 人效分析 — 上市公司人均人力成本 × 人均营收散点（薪酬策略投入产出）
3. 薪酬结构 — 岗位族 × 级别市场水位矩阵（定薪参考）
"""

import numpy as np
from sqlalchemy.orm import Session

from app.models import Company, Report, SalaryRecord
from app.services.stats import _market_filter, _quantiles, CN_LOCATIONS

_LEVELS = ["专员", "高级", "主管", "经理", "总监"]


def _dida_level_quantiles(db: Session) -> dict:
    """DIDA 内部各级别年化薪酬分位（CN 城市，sqlite 原生查询）。"""
    from sqlalchemy import text as _text
    ph = ",".join(f":cn{i}" for i in range(len(CN_LOCATIONS)))
    params = {f"cn{i}": c for i, c in enumerate(CN_LOCATIONS)}
    rows = db.execute(_text(
        f"SELECT level, monthly_cny * 12 FROM dida_payroll "
        f"WHERE location IN ({ph}) AND level IS NOT NULL AND monthly_cny IS NOT NULL"
    ), params).fetchall()
    by: dict[str, list[float]] = {}
    for lv, v in rows:
        by.setdefault(lv, []).append(float(v))
    return {lv: _quantiles(vals) for lv, vals in by.items()}


def _market_level_quantiles(db: Session) -> dict:
    q = db.query(SalaryRecord.level, SalaryRecord.annual_salary_avg_base).filter(
        SalaryRecord.level.isnot(None),
        SalaryRecord.annual_salary_avg_base.isnot(None))
    q = _market_filter(q)
    by: dict[str, list[float]] = {}
    for lv, v in q.all():
        if v is not None:
            by.setdefault(lv, []).append(float(v))
    return {lv: _quantiles(vals) for lv, vals in by.items()}


def level_positioning(db: Session) -> dict:
    """板块1：级别 × (DIDA 分位 vs 市场分位) 水位图数据。"""
    dida = _dida_level_quantiles(db)
    market = _market_level_quantiles(db)
    levels = []
    for lv in _LEVELS:
        d = dida.get(lv)
        m = market.get(lv)
        if not d and not m:
            continue
        # 只在双侧可靠时给出 gap（水位差）
        gap = None
        if d and m and d["reliable"] and m["reliable"] and m["p50"]:
            gap = round((d["p50"] - m["p50"]) / m["p50"], 3)
        levels.append({
            "level": lv,
            "dida": d,
            "market": m,
            "gap_pct": gap,
            "verdict": _verdict(gap, d, m),
        })
    return {"levels": levels}


def _verdict(gap: float | None, d: dict | None, m: dict | None) -> str:
    if gap is None:
        if d and not m:
            return "市场无参照"
        if m and not d:
            return "内部无数据"
        return "样本不足"
    if gap > 0.10:
        return "高于市场"
    if gap < -0.10:
        return "低于市场"
    return "持平"


def people_efficiency(db: Session, fiscal_year: int = 2024) -> dict:
    """板块2：上市公司人效散点（人均人力成本 × 人均营收）+ 行业参照线。"""
    rows = []
    reports = db.query(Report).filter_by(fiscal_year=fiscal_year, report_type="annual_report").all()
    for r in reports:
        if not r.employees:
            continue
        c = db.query(Company).get(r.company_id)
        row = {
            "company": c.short_name or c.name,
            "company_type": c.company_type,
            "employees": r.employees,
            "revenue_yi": round(r.revenue / 1e8, 1) if r.revenue else None,
            "total_comp_yi": round(r.total_comp / 1e8, 2) if r.total_comp else None,
            "avg_comp_wan": round(r.total_comp / r.employees / 1e4, 1) if r.total_comp else None,
            "avg_rev_wan": round(r.revenue / r.employees / 1e4) if r.revenue else None,
            "rev_per_comp": round(r.revenue / r.total_comp, 2) if (r.revenue and r.total_comp) else None,
            "confidence": r.confidence,
        }
        rows.append(row)
    return {"fiscal_year": fiscal_year, "companies": rows}


def family_level_matrix(db: Session) -> dict:
    """板块3：岗位族 × 级别 市场年薪 P50 矩阵（可靠的格子才算数）。"""
    from app.models import JobFamily
    fams = {f.id: f.name for f in db.query(JobFamily).all()}
    q = db.query(
        SalaryRecord.job_family_id, SalaryRecord.level,
        SalaryRecord.annual_salary_avg_base,
    ).filter(
        SalaryRecord.job_family_id.isnot(None),
        SalaryRecord.level.isnot(None),
        SalaryRecord.annual_salary_avg_base.isnot(None),
    )
    q = _market_filter(q)
    cells: dict[str, dict[str, list[float]]] = {}
    for fid, lv, v in q.all():
        if v is None:
            continue
        cells.setdefault(fams.get(fid, str(fid)), {}).setdefault(lv, []).append(float(v))
    matrix = {
        fam: {lv: _quantiles(vals) for lv, vals in sorted(lvs.items(), key=lambda kv: _LEVELS.index(kv[0]) if kv[0] in _LEVELS else 99)}
        for fam, lvs in cells.items()
    }
    return {"levels": _LEVELS, "families": sorted(matrix.keys()), "matrix": matrix}


def exec_summary(db: Session) -> dict:
    return {
        "positioning": level_positioning(db),
        "efficiency": people_efficiency(db),
        "matrix": family_level_matrix(db),
    }
