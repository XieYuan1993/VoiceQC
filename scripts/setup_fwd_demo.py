"""Create or update the lightweight FWD insurance demo workspace."""

from __future__ import annotations

import argparse
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import MetaData, create_engine, delete, insert, select, update

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")


def _sync_dsn(value: str) -> str:
    return value.replace("+asyncpg", "+psycopg").replace(
        "postgresql://", "postgresql+psycopg://", 1
    )


def setup(database_url: str, slug: str, name: str) -> None:
    engine = create_engine(_sync_dsn(database_url), pool_pre_ping=True)
    metadata = MetaData()
    metadata.reflect(bind=engine, only=("projects", "app_settings", "recordings"))
    projects = metadata.tables["projects"]
    settings = metadata.tables["app_settings"]
    recordings = metadata.tables["recordings"]

    modules = {"trade_reconciliation": False, "transcription_only": True}
    branding = {
        "app_name": "FWD Speech Analytics",
        "industry": "insurance",
        "demo_mode": True,
    }
    context = (
        "Hong Kong life insurance customer-service quality assurance demo. "
        "Use Traditional Chinese (Hong Kong) terminology and Arabic numerals."
    )

    swapped_channels = 0
    with engine.begin() as connection:
        project_id = connection.execute(
            select(projects.c.id).where(projects.c.slug == slug)
        ).scalar_one_or_none()
        if project_id is None:
            project_id = uuid.uuid4()
            connection.execute(
                insert(projects).values(
                    id=project_id,
                    slug=slug,
                    name=name,
                    description="FWD insurance speech analytics demonstration workspace.",
                    modules=modules,
                    eval_prompt_context=context,
                    branding=branding,
                    is_default=False,
                    active=True,
                )
            )
        else:
            connection.execute(
                update(projects)
                .where(projects.c.id == project_id)
                .values(
                    name=name,
                    description="FWD insurance speech analytics demonstration workspace.",
                    modules=modules,
                    eval_prompt_context=context,
                    branding=branding,
                    active=True,
                )
            )

        previous_broker_channel = connection.execute(
            select(settings.c.value).where(
                settings.c.project_id == project_id,
                settings.c.key == "audio.broker_channel",
            )
        ).scalar_one_or_none()
        if previous_broker_channel != "right":
            swap_result = connection.execute(
                update(recordings)
                .where(
                    recordings.c.project_id == project_id,
                    recordings.c.gcs_uri_broker.is_not(None),
                    recordings.c.gcs_uri_customer.is_not(None),
                )
                .values(
                    gcs_uri_broker=recordings.c.gcs_uri_customer,
                    gcs_uri_customer=recordings.c.gcs_uri_broker,
                )
            )
            swapped_channels = swap_result.rowcount

        setting_values = {
            "audio.broker_channel": "right",
            "asr.adaptation": "all",
            "asr.adaptation_boost": 7,
            "asr.model": "16k_zh_en",
            "asr.output_script": "traditional",
            "asr.language_mode": "auto",
            "asr.mono_speaker_repair": True,
            "asr.post_correction_enabled": True,
            "asr.post_correction_allow_numeric_changes": False,
            "asr.post_correction_provider": "dashscope",
            "asr.post_correction_model": "qwen3.7-max",
            "asr.provider": "tencent",
        }
        connection.execute(
            delete(settings).where(
                settings.c.project_id == project_id,
                settings.c.key.in_(setting_values),
            )
        )
        connection.execute(
            insert(settings),
            [
                {"project_id": project_id, "key": key, "value": value}
                for key, value in setting_values.items()
            ],
        )

    print(
        f"FWD demo workspace ready: {name} ({slug}); "
        f"corrected {swapped_channels} existing stereo recording(s)"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", default="fwd-insurance-demo")
    parser.add_argument("--name", default="FWD Insurance Demo")
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    setup(database_url, args.slug, args.name)


if __name__ == "__main__":
    main()
