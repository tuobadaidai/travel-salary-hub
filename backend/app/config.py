from pathlib import Path

from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    db_path: Path = PROJECT_ROOT / "data" / "salary.db"
    raw_dir: Path = PROJECT_ROOT / "data" / "raw"
    seed_dir: Path = PROJECT_ROOT / "data" / "seed"
    collect_min_interval: float = 4.0


settings = Settings()
