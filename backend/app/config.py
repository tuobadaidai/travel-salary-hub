from pathlib import Path

from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    db_path: Path = PROJECT_ROOT / "data" / "salary.db"
    raw_dir: Path = PROJECT_ROOT / "data" / "raw"
    seed_dir: Path = PROJECT_ROOT / "data" / "seed"
    collect_min_interval: float = 4.0
    # Apify token（用于 Levels.fyi 采集），从环境变量读取
    apify_token: str = ""
    # USD→CNY 汇率（默认 7.2，可按需调整）
    usd_to_cny: float = 7.2


settings = Settings()
