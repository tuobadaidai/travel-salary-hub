import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from pipeline.cleaning.normalize import classify_job_family
from pipeline.collectors.base import BaseCollector, RejectedItem


class _DummyCollector(BaseCollector):
    def collect(self, **params):
        yield from []


class TestSanitize:
    def setup_method(self):
        self.c = _DummyCollector()

    def test_whitelist_filters(self):
        item = {"position": "产品经理", "company_name": "携程", "foo": "bar", "salary_range": "15-25K"}
        out = self.c.sanitize(item)
        assert out == {"position": "产品经理", "company_name": "携程", "salary_range": "15-25K"}

    def test_rejects_personal_info(self):
        with pytest.raises(RejectedItem):
            self.c.sanitize({"candidate_name": "张三"})
        with pytest.raises(RejectedItem):
            self.c.sanitize({"phone": "13800138000"})
        with pytest.raises(RejectedItem):
            self.c.sanitize({"email": "a@b.com"})


class TestClassifyJobFamily:
    def test_legal(self):
        assert classify_job_family("法务总监") == "functional"
        assert classify_job_family("总法律顾问") == "functional"

    def test_tech(self):
        assert classify_job_family("后端开发工程师") == "tech"

    def test_sales(self):
        assert classify_job_family("大客户销售经理") == "sales"

    def test_none(self):
        assert classify_job_family("宇航员") is None
