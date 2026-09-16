import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.cleaning.normalize import (
    dedup_hash,
    detect_currency,
    monthly_to_annual,
    normalize_city,
    normalize_education,
    normalize_experience,
    normalize_position,
    parse_months,
    parse_salary_k,
)


class TestParseMonths:
    def test_k_with_months(self):
        assert parse_months("15-25K·14薪") == 14

    def test_plain(self):
        assert parse_months("15-25K") == 12

    def test_none(self):
        assert parse_months(None) == 12

    def test_out_of_range_defaults_12(self):
        assert parse_months("15-25K·30薪") == 12


class TestParseSalaryK:
    def test_k_range(self):
        assert parse_salary_k("15-25K") == (15000, 25000)

    def test_k_range_with_months(self):
        assert parse_salary_k("40-55K·14薪") == (40000, 55000)

    def test_wan_range(self):
        assert parse_salary_k("1.8-3万") == (18000, 30000)

    def test_plain_yuan(self):
        assert parse_salary_k("25000-35000") == (25000, 35000)

    def test_bare_numbers_treated_as_k(self):
        assert parse_salary_k("15-25") == (15000, 25000)

    def test_annual_explicit(self):
        low, high = parse_salary_k("30-42万/年")
        assert (low, high) == (25000.0, 35000.0)  # 年薪 30-42万 ÷ 12 月
        assert low * 12 == 300000

    def test_empty(self):
        assert parse_salary_k("") is None
        assert parse_salary_k(None) is None


class TestMonthlyToAnnual:
    def test_12_months(self):
        assert monthly_to_annual(25000, 35000, 12) == (300000, 420000)

    def test_14_months(self):
        assert monthly_to_annual(40000, 55000, 14) == (560000, 770000)


class TestCity:
    def test_shenzhen_with_district(self):
        assert normalize_city("深圳光明") == ("深圳", "CN")

    def test_shanghai(self):
        assert normalize_city("上海·浦东") == ("上海", "CN")

    def test_singapore(self):
        assert normalize_city("Singapore CBD") == ("新加坡", "SG")

    def test_dubai(self):
        assert normalize_city("Dubai") == ("迪拜", "AE")

    def test_unknown_chinese(self):
        assert normalize_city("三亚市")[1] == "CN"

    def test_unknown_latin(self):
        assert normalize_city("Berlin")[1] == "DE"  # DIDA 海外驻地，已收录
        assert normalize_city("Zaragoza")[1] == "XX"  # 未收录城市


class TestExperience:
    def test_range(self):
        assert normalize_experience("5-10年") == (5.0, 10.0)

    def test_min_only(self):
        assert normalize_experience("3年以上") == (3.0, None)

    def test_unlimited(self):
        assert normalize_experience("经验不限") == (None, None)

    def test_none(self):
        assert normalize_experience(None) == (None, None)


class TestEducation:
    def test_bachelor(self):
        assert normalize_education("本科") == "本科"

    def test_unlimited(self):
        assert normalize_education("学历不限") == "不限"

    def test_none(self):
        assert normalize_education(None) is None


class TestPosition:
    def test_strips_paren(self):
        assert normalize_position("法务总监（海外）") == "法务总监"

    def test_lower(self):
        assert normalize_position("Product Manager") == "productmanager"


class TestCurrency:
    def test_cny(self):
        assert detect_currency("2.5-3.5万", "CN") == "CNY"

    def test_usd(self):
        assert detect_currency("$5000-7000/mo", "US") == "USD"

    def test_country_fallback(self):
        assert detect_currency(None, "SG") == "SGD"


class TestDedupHash:
    def test_deterministic(self):
        a = dedup_hash("携程", "产品经理", "上海", 20000, 30000, "2026-09")
        b = dedup_hash("携程", "产品经理", "上海", 20000, 30000, "2026-09")
        assert a == b

    def test_differs_by_month(self):
        a = dedup_hash("携程", "产品经理", "上海", 20000, 30000, "2026-09")
        b = dedup_hash("携程", "产品经理", "上海", 20000, 30000, "2026-10")
        assert a != b
