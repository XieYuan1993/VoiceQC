"""Operational monitoring tasks."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from loguru import logger
from sqlalchemy import func, select
from voiceqa_shared.db_models import Evaluation, Recording

from worker.celery_app import app
from worker.db import SessionLocal
from worker.settings import settings

HK = ZoneInfo("Asia/Hong_Kong")
MONITOR_INTERVAL_SECONDS = 20 * 60


@dataclass
class EvaluatingMonitorSnapshot:
    queued: int
    running: int
    completed_recent: int
    failed_recent: int
    blocked: int
    stale_queued: int
    stale_running: int
    timed_out: int

    @property
    def evaluating(self) -> int:
        return self.queued + self.running

    @property
    def processed_recent(self) -> int:
        return self.completed_recent + self.failed_recent


def _feishu_sign(timestamp: str, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}".encode()
    digest = hmac.new(string_to_sign, b"", hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _feishu_payload(text: str) -> dict:
    payload: dict = {
        "msg_type": "text",
        "content": {"text": text},
    }
    secret = settings.FEISHU_WEBHOOK_SECRET.get_secret_value()
    if secret:
        timestamp = str(int(time.time()))
        payload["timestamp"] = timestamp
        payload["sign"] = _feishu_sign(timestamp, secret)
    return payload


def _send_feishu(text: str) -> bool:
    if not settings.FEISHU_WEBHOOK_URL:
        logger.info("Feishu webhook not configured; monitor message: {}", text)
        return False
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(settings.FEISHU_WEBHOOK_URL, json=_feishu_payload(text))
            resp.raise_for_status()
        return True
    except Exception:
        logger.exception("failed to send Feishu monitoring notification")
        return False


def _format_monitor_message(
    *,
    snapshot: EvaluatingMonitorSnapshot,
    interval_seconds: int = MONITOR_INTERVAL_SECONDS,
) -> str:
    now_hkt = datetime.now(UTC).astimezone(HK).strftime("%Y-%m-%d %H:%M:%S %Z")
    eta = _estimate_eta(snapshot, interval_seconds)
    status = "attention needed" if snapshot.blocked else "running" if snapshot.evaluating else "done"
    return "\n".join(
        [
            "VoiceQA evaluating monitor",
            f"Time: {now_hkt}",
            f"Status: {status}",
            f"Queued: {snapshot.queued}",
            f"Running: {snapshot.running}",
            f"Completed in last {interval_seconds // 60} min: {snapshot.completed_recent}",
            f"Failed in last {interval_seconds // 60} min: {snapshot.failed_recent}",
            f"Blocked/stale: {snapshot.blocked}",
            f"ETA: {eta}",
        ]
    )


def _estimate_eta(snapshot: EvaluatingMonitorSnapshot, interval_seconds: int) -> str:
    remaining = snapshot.evaluating
    if remaining <= 0:
        return "done"
    processed = snapshot.processed_recent
    if processed <= 0:
        return "unknown (no recent throughput)"
    minutes = max(1, round((remaining / processed) * (interval_seconds / 60)))
    if minutes < 60:
        return f"~{minutes} min"
    hours = minutes / 60
    return f"~{hours:.1f} h"


def _collect_evaluating_snapshot(now: datetime) -> EvaluatingMonitorSnapshot:
    stale_seconds = max(60, int(settings.EVALUATING_MONITOR_STALE_SECONDS))
    timeout_seconds = max(60, int(settings.RECORDING_EVAL_TIMEOUT_SECONDS))
    since = now - timedelta(seconds=MONITOR_INTERVAL_SECONDS)
    with SessionLocal() as session:
        latest_running = (
            select(
                Evaluation.recording_id.label("recording_id"),
                func.max(Evaluation.created_at).label("running_since"),
            )
            .where(Evaluation.status == "running")
            .group_by(Evaluation.recording_id)
            .subquery()
        )
        rows = (
            session.execute(
                select(
                    Recording,
                    latest_running.c.running_since,
                )
                .outerjoin(latest_running, latest_running.c.recording_id == Recording.id)
                .where(Recording.status == "evaluating")
                .order_by(Recording.updated_at.asc())
            )
            .all()
        )

        stale_queued = 0
        stale_running = 0
        timed_out = 0
        running = 0
        for rec, running_since in rows:
            updated_age = int((now - rec.updated_at).total_seconds())
            running_age = int((now - running_since).total_seconds()) if running_since else None
            if running_since is None and updated_age >= stale_seconds:
                stale_queued += 1
            elif running_age is not None and running_age >= timeout_seconds:
                running += 1
                timed_out += 1
            elif running_age is not None and running_age >= stale_seconds:
                running += 1
                stale_running += 1
            elif running_since is not None:
                running += 1
        completed_recent = session.execute(
            select(func.count())
            .select_from(Recording)
            .where(
                Recording.status == "completed",
                Recording.updated_at >= since,
            )
        ).scalar_one()
        failed_recent = session.execute(
            select(func.count())
            .select_from(Recording)
            .where(
                Recording.status == "failed",
                Recording.failed_stage.in_(("eval", "budget")),
                Recording.updated_at >= since,
            )
        ).scalar_one()
        blocked = stale_queued + stale_running + timed_out
        return EvaluatingMonitorSnapshot(
            queued=max(0, len(rows) - running),
            running=running,
            completed_recent=completed_recent,
            failed_recent=failed_recent,
            blocked=blocked,
            stale_queued=stale_queued,
            stale_running=stale_running,
            timed_out=timed_out,
        )


@app.task(name="voiceqa.monitor.evaluating_cases")
def monitor_evaluating_cases() -> dict:
    now = datetime.now(UTC)
    snapshot = _collect_evaluating_snapshot(now)
    notify_ok = bool(settings.EVALUATING_MONITOR_NOTIFY_OK)
    should_notify = (
        snapshot.evaluating > 0
        or snapshot.processed_recent > 0
        or snapshot.blocked > 0
        or notify_ok
    )
    if should_notify:
        text = _format_monitor_message(snapshot=snapshot)
        sent = _send_feishu(text)
    else:
        sent = False
        logger.info("evaluating monitor idle")
    return {
        "queued": snapshot.queued,
        "running": snapshot.running,
        "completed_recent": snapshot.completed_recent,
        "failed_recent": snapshot.failed_recent,
        "blocked": snapshot.blocked,
        "notified": sent,
    }
