"""apps/api Settings — extends the shared base.

Side effect: imports `dotenv` and loads `.env` from the repo root into
os.environ so downstream code that reads os.environ directly (e.g. Google
SDKs in Phase 1) finds the values. pydantic-settings only fills the
Settings object, not os.environ.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import SettingsConfigDict
from voiceqa_shared.settings import SharedSettings

# Repo root = apps/api/app/settings.py -> parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env", override=False)
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


class Settings(SharedSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    API_PORT: int = 7870
    ALLOWED_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:3020"])


settings = Settings()
