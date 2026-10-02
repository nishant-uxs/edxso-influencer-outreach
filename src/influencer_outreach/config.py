"""Application settings loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    niche: str = "technology"
    platform: str = "youtube"
    min_followers: int = 5_000
    max_followers: int = 100_000
    min_engagement_rate: float = 0.01
    discovery_limit: int = 60

    brand_name: str = "EDXSO"
    brand_value_prop: str = (
        "AI-powered creator collaboration tools for tech educators and builders"
    )
    collab_type: str = "UGC content creation"

    youtube_api_key: str = ""

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    # Comma-separated OpenAI-compatible fallbacks (used on 429/404)
    openai_fallback_models: str = "gemini-2.5-flash-lite,gemini-flash-latest,gemini-2.5-flash"

    data_dir: Path = Field(default_factory=lambda: ROOT / "data")
    database_path: Path = Field(default_factory=lambda: ROOT / "data" / "outreach.db")
    log_level: str = "INFO"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def outreach_dir(self) -> Path:
        return self.data_dir / "outreach"

    def ensure_dirs(self) -> None:
        for path in (self.raw_dir, self.processed_dir, self.outreach_dir):
            path.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
