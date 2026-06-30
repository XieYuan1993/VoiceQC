"""apps/worker settings — extends the shared base."""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict
from voiceqa_shared.settings import SharedSettings


class WorkerSettings(SharedSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    CELERY_TASK_DEFAULT_QUEUE: str = "default"


settings = WorkerSettings()
