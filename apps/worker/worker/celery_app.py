"""Celery app — Redis broker + result backend.

Queues: `default` (ingest/recon/rollup), `audio` (ffmpeg, CPU-bound),
`stt` (poll-heavy LRO waits), `llm` (Gemini calls). Phase-1 tasks declare
their queue via task options; dev runs one worker on all four
(`make worker.dev` passes -Q default,audio,stt,llm).
"""

from __future__ import annotations

from pathlib import Path

from celery import Celery
from dotenv import load_dotenv

# Load .env into os.environ so tasks that read external credentials
# (Google ADC project etc.) find them. Mirrors apps/api's settings.py.
_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env", override=False)
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

from worker.settings import settings

app = Celery(
    "voiceqa",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "worker.tasks.ping",
        "worker.tasks.ingest",
        "worker.tasks.pipeline",
        "worker.tasks.evaluate",
        "worker.tasks.evaluator",
        "worker.tasks.kb",
        "worker.tasks.batch",
        "worker.tasks.txn",
        "worker.tasks.recon",
        "worker.tasks.maintenance",
        "worker.tasks.monitoring",
    ],
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_default_queue=settings.CELERY_TASK_DEFAULT_QUEUE,
    timezone="UTC",
    enable_utc=True,
    worker_send_task_events=True,
    task_send_sent_event=True,
    # Pipeline tasks are idempotent (they re-read DB state and no-op when
    # their stage output exists), so late acks + redelivery on worker loss
    # are safe and preferred for long-running STT polls.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "voiceqa.pipeline.normalize_audio": {"queue": "audio"},
        "voiceqa.pipeline.transcribe": {"queue": "stt"},
        "voiceqa.pipeline.evaluate": {"queue": "llm"},
        "voiceqa.evaluator.generate_criteria": {"queue": "llm"},
        "voiceqa.kb.ingest_document": {"queue": "llm"},
    },
    beat_schedule={
        "dispatch-waiting-stt": {
            "task": "voiceqa.batch.dispatch_stt_waiting",
            "schedule": 15.0,
        },
        "sweep-stuck-recordings": {
            "task": "voiceqa.batch.sweep_stuck",
            "schedule": 300.0,
        },
        "txn-scheduled-pulls": {
            "task": "voiceqa.txn.scheduled_pulls",
            "schedule": 600.0,
        },
        "monitor-evaluating-cases": {
            "task": "voiceqa.monitor.evaluating_cases",
            "schedule": 1200.0,
        },
        "apply-retention": {
            "task": "voiceqa.maintenance.apply_retention",
            "schedule": 86400.0,  # daily
        },
    },
)
