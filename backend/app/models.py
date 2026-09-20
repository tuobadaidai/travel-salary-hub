from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, ForeignKey, Float, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        CheckConstraint("company_type IN ('OTA','B2B','traditional_agency','other')", name="ck_company_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    short_name: Mapped[str | None] = mapped_column(Text)
    company_type: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[str | None] = mapped_column(Text)
    hq_country: Mapped[str] = mapped_column(Text, default="CN", server_default="CN")
    stock_code: Mapped[str | None] = mapped_column(Text)
    is_listed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[str] = mapped_column(Text, default=_now)
    updated_at: Mapped[str] = mapped_column(Text, default=_now, onupdate=_now)


class JobFamily(Base):
    __tablename__ = "job_families"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class SalaryRecord(Base):
    __tablename__ = "salary_records"
    __table_args__ = (
        UniqueConstraint("dedup_hash", name="uq_sr_dedup"),
        Index("idx_sr_family_city", "job_family_id", "city"),
        Index("idx_sr_company", "company_id"),
        Index("idx_sr_date", "collect_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collect_run_id: Mapped[int | None] = mapped_column(ForeignKey("collect_runs.id"))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    job_family_id: Mapped[int | None] = mapped_column(ForeignKey("job_families.id"))
    # CSV 原口径
    position: Mapped[str] = mapped_column(Text, nullable=False)
    company_name: Mapped[str] = mapped_column(Text, nullable=False)
    company_type: Mapped[str | None] = mapped_column(Text)
    salary_range: Mapped[str | None] = mapped_column(Text)
    salary_monthly_low: Mapped[float | None] = mapped_column(Float)
    salary_monthly_high: Mapped[float | None] = mapped_column(Float)
    months: Mapped[int] = mapped_column(Integer, default=12)
    annual_salary_low: Mapped[float | None] = mapped_column(Float)
    annual_salary_high: Mapped[float | None] = mapped_column(Float)
    annual_salary_avg: Mapped[float | None] = mapped_column(Float)
    location: Mapped[str | None] = mapped_column(Text)
    experience: Mapped[str | None] = mapped_column(Text)
    education: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    collect_date: Mapped[str] = mapped_column(Text, nullable=False)
    # 归一化扩展
    position_norm: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str] = mapped_column(Text, default="CN", server_default="CN")
    currency: Mapped[str] = mapped_column(Text, default="CNY", server_default="CNY")
    annual_salary_avg_base: Mapped[float | None] = mapped_column(Float)  # 折算 CNY/年，跨国对比用
    experience_min_yrs: Mapped[float | None] = mapped_column(Float)
    experience_max_yrs: Mapped[float | None] = mapped_column(Float)
    education_level: Mapped[str | None] = mapped_column(Text)
    dedup_hash: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    # 聚合源扩展：jobui 等聚合页的样本量与分段明细
    sample_count: Mapped[int | None] = mapped_column(Integer)
    extra_json: Mapped[str | None] = mapped_column(Text)  # segment_wages / city_district_wages / distribution
    # 级别维度：市场级别（专员/高级/主管/经理/总监/VP）+ DIDA 等效级（L1-L6，对标用）
    level: Mapped[str | None] = mapped_column(Text, index=True)
    dida_grade: Mapped[str | None] = mapped_column(Text)  # O1-O4 / P0-P8 / M4-M5
    created_at: Mapped[str] = mapped_column(Text, default=_now)


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("company_id", "fiscal_year", "report_type", name="uq_report_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    report_type: Mapped[str] = mapped_column(Text, nullable=False)
    avg_salary: Mapped[float | None] = mapped_column(Float)
    employees: Mapped[int | None] = mapped_column(Integer)
    total_comp: Mapped[float | None] = mapped_column(Float)
    revenue: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(Text, default="medium")


class FxRate(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (
        UniqueConstraint("currency", "rate_date", name="uq_fx_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    currency: Mapped[str] = mapped_column(Text, nullable=False)  # ISO 4217，如 USD/EUR/INR
    rate_date: Mapped[str] = mapped_column(Text, nullable=False)  # ISO 日期，取生效日起
    rate_to_cny: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, default=_now)


class CollectRun(Base):
    __tablename__ = "collect_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    started_at: Mapped[str] = mapped_column(Text, default=_now)
    finished_at: Mapped[str | None] = mapped_column(Text)
    items_fetched: Mapped[int] = mapped_column(Integer, default=0)
    items_new: Mapped[int] = mapped_column(Integer, default=0)
    items_updated: Mapped[int] = mapped_column(Integer, default=0)
    items_rejected: Mapped[int] = mapped_column(Integer, default=0)
    params_json: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)


class IngestSchedule(Base):
    """定期更新注册表：每个数据源一行，记录刷新节奏与最近成功时间。"""

    __tablename__ = "ingest_schedules"
    __table_args__ = (
        UniqueConstraint("source_name", name="uq_schedule_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    cadence: Mapped[str] = mapped_column(Text, nullable=False, default="monthly")
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    last_run_at: Mapped[str | None] = mapped_column(Text)
    last_success_at: Mapped[str | None] = mapped_column(Text)
    next_due_at: Mapped[str | None] = mapped_column(Text)
