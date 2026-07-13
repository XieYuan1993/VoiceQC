"""Settings shared by apps/api and apps/worker.

Per-app settings (e.g. apps/api's CORS origins) extend this base class.
Ported from Voicebot-Platform's voicebot_shared/settings.py.
"""

from __future__ import annotations

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Anything else (staging, prod, production, ...) trips the placeholder-secret
# guard below. Set ENV=development in your .env for local work.
_DEV_ENVS = frozenset({"dev", "development", "local", "test"})

# Known placeholder values that must never reach a real deployment.
# `.env.example` ships these strings as hints; `make bootstrap` replaces them
# with generated secrets for local dev.
_PLACEHOLDER_VALUES: dict[str, frozenset[str]] = {
    "NEXTAUTH_SECRET": frozenset(
        {
            "change-me-in-env",
            "replace-me-with-openssl-rand-base64-32",
        }
    ),
    "INTERNAL_API_SECRET": frozenset(
        {
            "change-me-in-env",
            "replace-me-internal-secret",
        }
    ),
    "APP_ENCRYPTION_KEY": frozenset(
        {
            "change-me-in-env",
            "replace-me-with-openssl-rand-base64-32",
        }
    ),
}


class SharedSettings(BaseSettings):
    """Settings used by all Python services."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # Deployment environment. `development` (or dev/local/test) enables the
    # local-friendly defaults below; anything else triggers the placeholder
    # guard in `_block_placeholder_secrets`.
    ENV: str = Field(
        default="development",
        description="development | staging | production",
    )

    # Postgres — the async DSN used by SQLAlchemy + asyncpg.
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://voiceqa:voiceqa@localhost:55433/voiceqa",
        description="Async DSN: postgresql+asyncpg://...",
    )

    # The non-async DSN that Alembic + raw psycopg use (Alembic env.py converts
    # this on the fly, but seed scripts and ad-hoc tools may want it directly).
    @property
    def database_url_sync(self) -> str:
        return self.DATABASE_URL.replace("+asyncpg", "").replace(
            "postgresql+psycopg://", "postgresql://"
        )

    # Redis broker / cache.
    REDIS_URL: str = "redis://localhost:56380/0"

    # Auth.js shared secret — same value used by apps/web's NextAuth; the api
    # uses it to decrypt the session-cookie JWE.
    NEXTAUTH_SECRET: SecretStr = SecretStr("change-me-in-env")
    # Web app base URL — used in password-reset email links.
    NEXTAUTH_URL: str = "http://localhost:3020"

    # Shared secret between apps/web's Credentials authorize() and apps/api's
    # /api/auth/verify-credentials endpoint.
    INTERNAL_API_SECRET: SecretStr = SecretStr("change-me-in-env")

    # AES-256-GCM key for secrets stored in the DB (Phase 4: SSO client
    # secret, txn API credentials).
    APP_ENCRYPTION_KEY: SecretStr = SecretStr("change-me-in-env")

    # SMTP — password-reset emails (MailHog in dev).
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1026
    SMTP_USER: str = ""
    SMTP_PASS: SecretStr = SecretStr("")
    MAIL_FROM: str = "VoiceQA <noreply@voiceqa.local>"

    # Google Cloud (Phase 1+). STT runs in asia-southeast1 (no HK region);
    # the GCS audio bucket lives in asia-east2 (HK). See DESIGN.md §1.
    GOOGLE_CLOUD_PROJECT: str = ""
    GOOGLE_STT_LOCATION: str = "asia-southeast1"
    VERTEX_LLM_LOCATION: str = "asia-southeast1"
    GCS_BUCKET_AUDIO: str = "quam-voiceqa-dev"
    GOOGLE_STT_MODEL: str = "chirp_2"
    VERTEX_LLM_MODEL: str = "gemini-3.5-flash"

    # LLM provider for call evaluation: "dashscope" (Qwen) or "gemini" (Vertex AI).
    LLM_PROVIDER: str = "dashscope"
    # If set, the worker tries LLM_PROVIDER first and falls back to this provider
    # on connectivity / timeout errors (e.g. LLM_FALLBACK_PROVIDER=dashscope).
    LLM_FALLBACK_PROVIDER: str = ""
    # DashScope LLM model (used when LLM_PROVIDER=dashscope or as fallback).
    DASHSCOPE_LLM_MODEL: str = "qwen3.7-max"

    # Qwen / Alibaba Cloud Model Studio (DashScope) — optional ASR provider.
    DASHSCOPE_API_KEY: SecretStr = SecretStr("")
    DASHSCOPE_BASE_URL: str = ""

    # Tencent Cloud ASR (CreateRecTask / DescribeTaskStatus). The Tencent
    # "普方英大模型" engine is EngineModelType=16k_zh_en.
    TENCENT_SECRET_ID: SecretStr = SecretStr("")
    TENCENT_SECRET_KEY: SecretStr = SecretStr("")
    TENCENT_ASR_REGION: str = "ap-guangzhou"
    # Optional public API base URL used to let Tencent ASR download private GCS
    # audio through VoiceQA instead of pulling Google Storage directly.
    ASR_AUDIO_PROXY_BASE_URL: str = ""

    # Recording pipeline stage timeouts. The worker's sweep task marks stale
    # in-flight recordings failed so operators can retry/rerun them.
    RECORDING_CONVERT_TIMEOUT_SECONDS: int = 30 * 60
    RECORDING_STT_TIMEOUT_SECONDS: int = 30 * 60
    RECORDING_EVAL_TIMEOUT_SECONDS: int = 60 * 60
    RECORDING_QUEUE_REDISPATCH_SECONDS: int = 24 * 60 * 60
    RECORDING_RESUME_STALE_SECONDS: int = 5 * 60
    RECORDING_RESUME_MAX_ATTEMPTS: int = 1
    STT_MAX_IN_FLIGHT: int = 3

    LOG_LEVEL: str = "INFO"

    @model_validator(mode="after")
    def _block_placeholder_secrets(self) -> SharedSettings:
        if self.ENV.lower() in _DEV_ENVS:
            return self
        bad: list[str] = []
        for field, placeholders in _PLACEHOLDER_VALUES.items():
            value = getattr(self, field, None)
            raw = (
                value.get_secret_value()
                if isinstance(value, SecretStr)
                else str(value)
                if value is not None
                else ""
            )
            if raw in placeholders:
                bad.append(field)
        if bad:
            raise ValueError(
                f"Refusing to start in ENV={self.ENV!r} with placeholder values "
                f"for: {', '.join(bad)}. Set these env vars to real secrets, "
                "or set ENV=development for local work."
            )
        return self
