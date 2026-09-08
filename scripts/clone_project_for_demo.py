"""Clone one project's QA workspace into another project.

The clone keeps the source untouched, creates independent database identities,
and optionally copies every referenced audio object to a target-specific prefix.
Existing target recordings are preserved. Project configuration is replaced by
the source configuration so historical QA data and future evaluations agree.
"""

from __future__ import annotations

import argparse
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from dotenv import load_dotenv
from google.cloud import storage
from sqlalchemy import MetaData, Table, create_engine, delete, insert, select, update

CONFIG_TABLES = (
    "eval_criteria",
    "extraction_fields",
    "checklist_items",
    "industry_terms",
)

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")


def _sync_dsn(value: str) -> str:
    return value.replace("+asyncpg", "+psycopg").replace(
        "postgresql://", "postgresql+psycopg://", 1
    )


def _new_id(target_id: uuid.UUID, table: str, old_id: Any) -> uuid.UUID:
    return uuid.uuid5(target_id, f"voiceqa-demo-clone:{table}:{old_id}")


def _rows(connection, table: Table, condition) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(select(table).where(condition)).mappings()]


def _copy_audio_object(client: storage.Client, source_uri: str, destination_key: str) -> str:
    source_bucket_name, _, source_key = source_uri.removeprefix("gs://").partition("/")
    source_bucket = client.bucket(source_bucket_name)
    source_blob = source_bucket.blob(source_key)
    destination_bucket = client.bucket(source_bucket_name)
    destination_blob = destination_bucket.blob(destination_key)
    if not destination_blob.exists(client):
        source_bucket.copy_blob(source_blob, destination_bucket, destination_key)
    return f"gs://{source_bucket_name}/{destination_key}"


def _copy_audio(
    recordings: list[dict[str, Any]],
    *,
    target_slug: str,
    workers: int,
) -> int:
    client = storage.Client()
    jobs: list[tuple[dict[str, Any], str, str]] = []
    for recording in recordings:
        for column, label in (
            ("gcs_uri_raw", "raw"),
            ("gcs_uri_broker", "broker"),
            ("gcs_uri_customer", "customer"),
            ("gcs_uri_mono", "mono"),
        ):
            source_uri = recording.get(column)
            if not source_uri:
                continue
            suffix = PurePosixPath(source_uri).suffix
            destination_key = f"demo-clones/{target_slug}/{recording['id']}/{label}{suffix}"
            jobs.append((recording, column, destination_key))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(_copy_audio_object, client, recording[column], key): (recording, column)
            for recording, column, key in jobs
        }
        for completed, future in enumerate(as_completed(future_map), 1):
            recording, column = future_map[future]
            recording[column] = future.result()
            if completed % 100 == 0 or completed == len(jobs):
                print(f"audio objects copied: {completed}/{len(jobs)}", flush=True)
    return len(jobs)


def clone_project(
    database_url: str,
    source_slug: str,
    target_slug: str,
    *,
    copy_audio: bool,
    audio_workers: int,
    dry_run: bool,
) -> None:
    engine = create_engine(_sync_dsn(database_url), pool_pre_ping=True)
    metadata = MetaData()
    metadata.reflect(bind=engine)
    tables = metadata.tables

    with engine.connect() as connection:
        projects = tables["projects"]
        source = (
            connection.execute(select(projects).where(projects.c.slug == source_slug))
            .mappings()
            .one()
        )
        target = (
            connection.execute(select(projects).where(projects.c.slug == target_slug))
            .mappings()
            .one()
        )
        source_id = source["id"]
        target_id = target["id"]

        batches = _rows(
            connection,
            tables["upload_batches"],
            tables["upload_batches"].c.project_id == source_id,
        )
        batch_ids = [row["id"] for row in batches]
        recordings = (
            _rows(
                connection,
                tables["recordings"],
                tables["recordings"].c.batch_id.in_(batch_ids),
            )
            if batch_ids
            else []
        )
        recording_ids = [row["id"] for row in recordings]
        transcripts = (
            _rows(
                connection,
                tables["transcripts"],
                tables["transcripts"].c.recording_id.in_(recording_ids),
            )
            if recording_ids
            else []
        )
        transcript_ids = [row["id"] for row in transcripts]
        evaluations = (
            _rows(
                connection,
                tables["evaluations"],
                tables["evaluations"].c.recording_id.in_(recording_ids),
            )
            if recording_ids
            else []
        )
        evaluation_ids = [row["id"] for row in evaluations]

        dependent_rows = {
            "transcript_segments": (
                _rows(
                    connection,
                    tables["transcript_segments"],
                    tables["transcript_segments"].c.transcript_id.in_(transcript_ids),
                )
                if transcript_ids
                else []
            ),
            "evaluation_results": (
                _rows(
                    connection,
                    tables["evaluation_results"],
                    tables["evaluation_results"].c.evaluation_id.in_(evaluation_ids),
                )
                if evaluation_ids
                else []
            ),
            "trade_instructions": (
                _rows(
                    connection,
                    tables["trade_instructions"],
                    tables["trade_instructions"].c.recording_id.in_(recording_ids),
                )
                if recording_ids
                else []
            ),
        }

        config_rows = {
            name: _rows(connection, tables[name], tables[name].c.project_id == source_id)
            for name in CONFIG_TABLES
        }
        settings = _rows(
            connection,
            tables["app_settings"],
            tables["app_settings"].c.project_id == source_id,
        )
        kb_documents = _rows(
            connection,
            tables["kb_documents"],
            tables["kb_documents"].c.project_id == source_id,
        )
        kb_document_ids = [row["id"] for row in kb_documents]
        kb_chunks = (
            _rows(
                connection,
                tables["kb_chunks"],
                tables["kb_chunks"].c.document_id.in_(kb_document_ids),
            )
            if kb_document_ids
            else []
        )

    print(f"source: {source['name']} ({source_slug})")
    print(f"target: {target['name']} ({target_slug})")
    print(
        "clone plan: "
        f"{len(batches)} batches, {len(recordings)} recordings, "
        f"{len(transcripts)} transcripts, {len(evaluations)} evaluations, "
        f"{len(dependent_rows['evaluation_results'])} evaluation results, "
        f"{len(dependent_rows['trade_instructions'])} trade instructions"
    )
    if dry_run:
        return

    batch_map = {row["id"]: _new_id(target_id, "upload_batches", row["id"]) for row in batches}
    recording_map = {row["id"]: _new_id(target_id, "recordings", row["id"]) for row in recordings}
    transcript_map = {
        row["id"]: _new_id(target_id, "transcripts", row["id"]) for row in transcripts
    }
    evaluation_map = {
        row["id"]: _new_id(target_id, "evaluations", row["id"]) for row in evaluations
    }
    kb_document_map = {
        row["id"]: _new_id(target_id, "kb_documents", row["id"]) for row in kb_documents
    }

    with engine.connect() as connection:
        duplicate = connection.execute(
            select(tables["upload_batches"].c.id).where(
                tables["upload_batches"].c.id.in_(list(batch_map.values()))
            )
        ).first()
        if duplicate:
            raise RuntimeError("this source project has already been cloned into the target")

    for row in batches:
        row["id"] = batch_map[row["id"]]
        row["project_id"] = target_id
    for row in recordings:
        old_id = row["id"]
        row["id"] = recording_map[old_id]
        row["project_id"] = target_id
        row["batch_id"] = batch_map[row["batch_id"]]
        row["stt_operation_name"] = None
        row["stt_started_at"] = None
    for row in transcripts:
        old_id = row["id"]
        row["id"] = transcript_map[old_id]
        row["recording_id"] = recording_map[row["recording_id"]]
    for row in evaluations:
        old_id = row["id"]
        row["id"] = evaluation_map[old_id]
        row["recording_id"] = recording_map[row["recording_id"]]
    for row in dependent_rows["transcript_segments"]:
        row.pop("id", None)
        row["transcript_id"] = transcript_map[row["transcript_id"]]
    for row in dependent_rows["evaluation_results"]:
        row["id"] = _new_id(target_id, "evaluation_results", row["id"])
        row["evaluation_id"] = evaluation_map[row["evaluation_id"]]
    for row in dependent_rows["trade_instructions"]:
        row["id"] = _new_id(target_id, "trade_instructions", row["id"])
        row["evaluation_id"] = evaluation_map[row["evaluation_id"]]
        row["recording_id"] = recording_map[row["recording_id"]]
    for row in kb_documents:
        old_id = row["id"]
        row["id"] = kb_document_map[old_id]
        row["project_id"] = target_id
    for row in kb_chunks:
        row["id"] = _new_id(target_id, "kb_chunks", row["id"])
        row["document_id"] = kb_document_map[row["document_id"]]
        row["project_id"] = target_id

    copied_objects = 0
    if copy_audio:
        copied_objects = _copy_audio(recordings, target_slug=target_slug, workers=audio_workers)

    with engine.begin() as connection:
        connection.execute(
            update(tables["projects"])
            .where(tables["projects"].c.id == target_id)
            .values(
                modules=source["modules"],
                eval_prompt_context=source["eval_prompt_context"],
            )
        )
        connection.execute(
            delete(tables["app_settings"]).where(tables["app_settings"].c.project_id == target_id)
        )
        cloned_settings = [{**row, "project_id": target_id} for row in settings]
        output_setting = next(
            (row for row in cloned_settings if row["key"] == "asr.output_script"),
            None,
        )
        if output_setting is not None:
            output_setting["value"] = "traditional"
        else:
            cloned_settings.append(
                {
                    "project_id": target_id,
                    "key": "asr.output_script",
                    "value": "traditional",
                    "updated_by": None,
                    "updated_at": datetime.now(UTC),
                }
            )
        connection.execute(insert(tables["app_settings"]), cloned_settings)

        for name in CONFIG_TABLES:
            table = tables[name]
            connection.execute(delete(table).where(table.c.project_id == target_id))
            rows = []
            for source_row in config_rows[name]:
                row = dict(source_row)
                row["id"] = _new_id(target_id, name, row["id"])
                row["project_id"] = target_id
                rows.append(row)
            if rows:
                connection.execute(insert(table), rows)

        connection.execute(
            delete(tables["kb_documents"]).where(tables["kb_documents"].c.project_id == target_id)
        )
        for table_name, rows in (
            ("kb_documents", kb_documents),
            ("kb_chunks", kb_chunks),
            ("upload_batches", batches),
            ("recordings", recordings),
            ("transcripts", transcripts),
            ("transcript_segments", dependent_rows["transcript_segments"]),
            ("evaluations", evaluations),
            ("evaluation_results", dependent_rows["evaluation_results"]),
            ("trade_instructions", dependent_rows["trade_instructions"]),
        ):
            if rows:
                connection.execute(insert(tables[table_name]), rows)

    print(f"clone complete; independent audio objects copied: {copied_objects}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="source project slug")
    parser.add_argument("--target", required=True, help="target project slug")
    parser.add_argument("--copy-audio", action="store_true")
    parser.add_argument("--audio-workers", type=int, default=12)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    clone_project(
        database_url,
        args.source,
        args.target,
        copy_audio=args.copy_audio,
        audio_workers=args.audio_workers,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
