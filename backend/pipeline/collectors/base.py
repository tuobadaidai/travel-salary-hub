"""采集器基类：合规红线内建在结构里，违规在结构上不可能。

红线：
1. 不带 Cookie/登录态（Client 不启用 cookie 持久化）
2. 每域名单线程 + 最小间隔（fetch 内建 sleep）
3. 尊重 robots.txt（辅助函数）
4. 字段白名单：出现姓名/手机号/邮箱键名的条目直接 reject
5. 原始响应先落 data/raw/{source}/{date}.jsonl 审计
"""

import json
import re
import time
import urllib.robotparser
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import httpx

from app.config import settings

# 命中即拒的敏感字段（个人简历信息，绝不入库）。company_name 是公司名，合法。
_SENSITIVE_KEY = re.compile(r"^(?!company_name$).*(name|phone|mobile|email|tel|身份证|姓名|电话|邮箱)", re.I)

ALLOWED_FIELDS = {
    "position", "company_name", "company_type", "salary_range",
    "salary_monthly_low", "salary_monthly_high", "months",
    "location", "experience", "education", "source_url",
}


class RejectedItem(Exception):
    pass


class BaseCollector(ABC):
    source_name: str = "base"
    base_url: str = ""
    rate_limit_seconds: float = 4.0

    def __init__(self):
        self.raw_dir = settings.raw_dir / self.source_name
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self._last_fetch_ts = 0.0

    def _rate_limit(self):
        elapsed = time.monotonic() - self._last_fetch_ts
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)
        self._last_fetch_ts = time.monotonic()

    def fetch_page(self, client: httpx.Client, url: str) -> str:
        """限速 + 明确 UA + 无 Cookie 的 GET。"""
        self._rate_limit()
        resp = client.get(
            url,
            headers={"User-Agent": f"travel-salary-hub-collector/0.1 (+internal; respects robots)"},
            timeout=15.0,
        )
        resp.raise_for_status()
        self._dump_raw(url, resp.text)
        return resp.text

    def _dump_raw(self, url: str, body: str):
        today = datetime.now(timezone.utc).date().isoformat()
        path = self.raw_dir / f"{today}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"url": url, "ts": datetime.now(timezone.utc).isoformat(), "body": body[:100000]}, ensure_ascii=False) + "\n")

    def sanitize(self, item: dict) -> dict:
        """字段白名单过滤 + 敏感字段拒绝。"""
        for k in item:
            if _SENSITIVE_KEY.search(k):
                raise RejectedItem(f"sensitive field: {k}")
        return {k: v for k, v in item.items() if k in ALLOWED_FIELDS}

    def check_robots(self, client: httpx.Client, url: str) -> bool:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(f"{self.base_url}/robots.txt")
        try:
            rp.read()
        except Exception:
            return False  # robots 不可读 → 保守不抓
        return rp.can_fetch("travel-salary-hub-collector/0.1", url)

    @abstractmethod
    def collect(self, **params) -> Iterator[dict]:
        """产出 sanitize 后的原始条目 dict（未归一化）。"""
        ...


REGISTRY: dict[str, type[BaseCollector]] = {}


def register(cls: type[BaseCollector]) -> type[BaseCollector]:
    REGISTRY[cls.source_name] = cls
    return cls
