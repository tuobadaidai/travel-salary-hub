"""stats 服务单测：months 过滤（S1.3）、dida_title_match（S2.2）、tier 降级（S2.1）、海外统计（S3）。

内存 sqlite fixture，直接建表灌数据，不经 ORM metadata 依赖。
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.services import stats


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def _add_market(db, **kw):
    annual = kw.pop("annual", 300000)
    today = datetime.now().date().isoformat()
    row = {
        "position": "产品经理", "position_norm": "产品经理", "company_name": "测试公司",
        "city": "深圳", "country": "CN", "level": "高级", "source": "test_jd",
        "months": 12, "currency": "CNY",
        "annual_salary_avg_base": annual,
        "collect_date": today,
    }
    row.update(kw)
    row.setdefault("dedup_hash", f"t{annual}|{row['city']}|{row['country']}|{len(kw)}")
    for k in ("annual_salary_avg", "annual_salary_low", "annual_salary_high"):
        row.setdefault(k, row["annual_salary_avg_base"])
    db.add(stats.SalaryRecord(**row))
    db.flush()


def _add_dida(db, title, grade, location, monthly_cny):
    db.execute(text(
        "INSERT INTO dida_payroll (title, seq, grade, grade_equiv, level, monthly_cny, "
        "annual_cny, currency, location, pay_hash) VALUES "
        "(:t, 'P', :g, :g, '高级', :m, :m*12, 'CNY', :loc, :h)"
    ), {"t": title, "g": grade, "m": monthly_cny, "loc": location,
        "h": f"{title}|{grade}|{location}|{monthly_cny}"})


@pytest.fixture
def dida_table(db):
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS dida_payroll (
            id INTEGER PRIMARY KEY,
            title TEXT, dept_l1 TEXT, seq TEXT, grade TEXT, grade_equiv TEXT,
            level TEXT, monthly_cny REAL, annual_cny REAL, currency TEXT,
            location TEXT, pay_hash TEXT UNIQUE, imported_at TEXT
        )
    """))
    db.flush()


class TestMonthsFilter:
    def test_months_over_13_excluded(self, db):
        _add_market(db, annual=300000, months=12)
        _add_market(db, annual=3000000, months=18)  # 异常口径，应剔除
        q = db.query(stats.METRIC)
        q = stats._market_filter(q)
        vals = [v for (v,) in q.all()]
        assert vals == [300000]

    def test_months_none_kept(self, db):
        _add_market(db, annual=250000, months=None)
        q = stats._market_filter(db.query(stats.METRIC))
        assert [v for (v,) in q.all()] == [250000]

    def test_overseas_excluded_by_default(self, db):
        _add_market(db, annual=300000)
        _add_market(db, annual=900000, country="SG", city="新加坡")
        q = stats._market_filter(db.query(stats.METRIC))
        assert [v for (v,) in q.all()] == [300000]
        q2 = stats._market_filter(db.query(stats.METRIC), include_overseas=True)
        assert sorted(v for (v,) in q2.all()) == [300000, 900000]


class TestTitleMatch:
    def test_base_name_stripping(self, dida_table, db):
        for t in ["产品经理", "高级产品经理", "资深技术产品经理", "后台产品经理"]:
            _add_dida(db, t, "P3", "深圳", 30000)
        _add_dida(db, "销售经理", "P3", "深圳", 25000)
        titles = stats.dida_title_match(db, "产品经理")
        assert "产品经理" in titles
        assert "高级产品经理" in titles
        assert "资深技术产品经理" in titles
        assert "销售经理" not in titles

    def test_modifier_only_title_untouched(self, dida_table, db):
        assert stats._title_base("总经理") == "总经理"


class TestTierDegradation:
    def test_tier1_city_reliable(self, dida_table, db):
        # 5 人同 grade 同城 → tier1；市场同 level 同城 ≥5 样本才计 gap
        for i in range(5):
            _add_dida(db, "产品经理", "P4", "深圳", 25000 + i * 1000)
        for i in range(5):
            _add_market(db, annual=360000 + i * 5000, level="主管", city="深圳")
        r = stats.benchmark_by_grade(db, "产品经理")
        cell = r["cells"]["P4"]["深圳"]
        assert cell["tier"] == 1
        assert cell["dida"]["reliable"]
        assert cell["market_ref"] is not None
        assert cell["market_ref"]["reliable"]
        assert cell["gap_pct"] is not None

    def test_tier2_national_fallback(self, dida_table, db):
        # 深圳 2 人 + 长沙 3 人：单城不可靠，全国 5 人 → tier2，dida 显示全国聚合
        for i in range(2):
            _add_dida(db, "产品经理", "P4", "深圳", 26000 + i * 1000)
        for i in range(3):
            _add_dida(db, "产品经理", "P4", "长沙", 20000 + i * 1000)
        r = stats.benchmark_by_grade(db, "产品经理")
        cell = r["cells"]["P4"]["深圳"]
        assert cell["tier"] == 2
        assert cell["dida"]["count"] == 5  # 全国样本
        assert cell["dida"]["reliable"]

    def test_tier3_low_sample_kept_visible(self, dida_table, db):
        # 全国 2 人 → tier3，但 DIDA 数字保留（reliable=false），不消失
        _add_dida(db, "产品经理", "P2", "深圳", 13500)
        _add_dida(db, "产品经理", "P2", "长沙", 14800)
        r = stats.benchmark_by_grade(db, "产品经理")
        cell = r["cells"]["P2"]["深圳"]
        assert cell["tier"] == 3
        assert cell["dida"] is not None
        assert not cell["dida"]["reliable"]
        assert cell["dida"]["count"] == 1
        assert cell["gap_pct"] is None  # 低样本不算 gap


class TestOverseasStats:
    def test_internal_overseas_only(self, dida_table, db):
        _add_dida(db, "产品经理", "P4", "深圳", 25000)
        _add_dida(db, "产品经理", "P4", "新加坡", 45000)
        _add_dida(db, "运营专员", "P2", "雅加达", 12000)
        r = stats.overseas_stats(db)
        names = {c["country"] for c in r["internal"]["countries"]}
        assert "深圳" not in names
        assert "新加坡" in names and "雅加达" in names
        assert r["internal"]["total"] == 2

    def test_title_keyword_filter(self, dida_table, db):
        _add_dida(db, "产品经理", "P4", "新加坡", 45000)
        _add_dida(db, "销售经理", "P5", "泰国", 38000)
        r = stats.overseas_stats(db, "产品")
        assert r["internal"]["total"] == 1
        assert r["internal"]["countries"][0]["country"] == "新加坡"

    def test_market_overseas_records(self, dida_table, db):
        _add_market(db, annual=400000, country="SG", city="新加坡")
        _add_market(db, annual=300000)
        r = stats.overseas_stats(db)
        assert "新加坡" in r["market"]["by_city"]
        assert r["market"]["total"] == 1
