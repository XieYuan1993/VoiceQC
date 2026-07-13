"""Thin Celery producer — the API enqueues by task NAME only; task code
lives exclusively in apps/worker."""

from __future__ import annotations

from celery import Celery, signature

from app.settings import settings

celery_client = Celery(broker=settings.REDIS_URL, backend=settings.REDIS_URL)
celery_client.conf.update(
    task_serializer="json",
    accept_content=["json"],
)

_QUEUES = {
    "voiceqa.pipeline.normalize_audio": "audio",
    "voiceqa.pipeline.transcribe": "stt",
    "voiceqa.pipeline.evaluate": "llm",
    "voiceqa.kb.ingest_document": "llm",
}


def send(task_name: str, *args) -> None:
    celery_client.send_task(task_name, args=list(args), queue=_QUEUES.get(task_name, "default"))


def send_pipeline_chain(
    recording_id: str,
    *,
    from_stage: str = "convert",
    asr_provider: str | None = None,
    asr_model: str | None = None,
) -> None:
    """Dispatch the per-recording pipeline starting at the given stage.

    Stages chain themselves downstream (transcribe dispatches evaluate),
    so each entry point only needs to start at the right place.
    """

    def sig(task_name: str):
        args = [recording_id]
        if task_name == "voiceqa.pipeline.transcribe":
            args.extend([asr_provider, asr_model])
        return signature(
            task_name,
            args=args,
            app=celery_client,
            immutable=True,
            queue=_QUEUES[task_name],
        )

    if from_stage == "eval":
        sig("voiceqa.pipeline.evaluate").apply_async()
    elif from_stage == "stt":
        sig("voiceqa.pipeline.transcribe").apply_async()
    else:
        (sig("voiceqa.pipeline.normalize_audio") | sig("voiceqa.pipeline.transcribe")).apply_async()
