from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.services import stats

router = APIRouter(prefix="/api/v1", tags=["dashboard"])


@router.get("/meta")
def get_meta(db: Session = Depends(get_db)):
    return stats.meta_full(db)


@router.get("/stats/quantiles")
def get_quantiles(
    group_by: str = Query("job_family", pattern="^(city|country|company_type|job_family|level|position)$"),
    city: str | None = None,
    country: str | None = None,
    company_type: str | None = None,
    job_family_id: int | None = None,
    level: str | None = None,
    position: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
):
    return stats.quantiles_by_group(
        db, group_by, city=city, company_type=company_type,
        job_family_id=job_family_id, date_from=date_from, date_to=date_to, country=country,
        level=level, position=position,
    )


@router.get("/positions")
def get_positions(db: Session = Depends(get_db)):
    """可对标岗位清单（position 去重 + 覆盖级别）。"""
    return stats.positions_list(db)


@router.get("/stats/heatmap")
def get_heatmap(
    row_dim: str = Query("job_family", pattern="^(city|country|company_type|job_family|level|position)$"),
    col_dim: str = Query("city", pattern="^(city|country|company_type|job_family|level|position)$"),
    db: Session = Depends(get_db),
):
    return stats.cross_heatmap(db, row_dim, col_dim)


@router.get("/records")
def get_records(
    position: str | None = None,
    level: str | None = None,
    city: str | None = None,
    job_family_id: int | None = None,
    company_type: str | None = None,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    """穿透：原始记录（证据链）。"""
    return stats.drill_records(db, position, level, city, limit,
                               job_family_id=job_family_id, company_type=company_type)


@router.get("/benchmark")
def get_benchmark(
    position: str = Query(..., min_length=2),
    level: str | None = None,
    city: str | None = None,
    db: Session = Depends(get_db),
):
    """岗位对标矩阵：市场(级别×城市)分位数 + DIDA 内部对照。"""
    return stats.benchmark_matrix(
        db, position,
        levels=level.split(",") if level else None,
        cities=city.split(",") if city else None,
    )


@router.get("/stats/trend")
def get_trend(
    city: str | None = None,
    country: str | None = None,
    company_type: str | None = None,
    job_family_id: int | None = None,
    db: Session = Depends(get_db),
):
    return stats.trend_by_month(
        db, city=city, company_type=company_type, job_family_id=job_family_id, country=country,
    )
