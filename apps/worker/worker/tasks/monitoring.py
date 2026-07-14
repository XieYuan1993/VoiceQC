"""Operational monitoring tasks."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
from loguru import logger
from sqlalchemy import func, select
from voiceqa_shared.db_models import Evaluation, Recording, UploadBatch

from worker.celery_app import app
from worker.db import SessionLocal
from worker.settings import settings

HK = ZoneInfo("Asia/Hong_Kong")


@dataclass
class EvaluatingIssue:
    recording_id: str
    filename: str
    batch_name: str
    age_minutes: int
    updated_minutes: int
    issue: str
    error: str | None


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
    total_evaluating: int,
    stale_seconds: int,
    timeout_seconds: int,
    issues: list[EvaluatingIssue],
) -> str:
    now_hkt = datetime.now(UTC).astimezone(HK).strftime("%Y-%m-%d %H:%M:%S %Z")
    if not issues:
        return (
            "VoiceQA evaluating monitor\n"
            f"Time: {now_hkt}\n"
            f"Status: OK\n"
            f"Evaluating recordings: {total_evaluating}"
        )

    lines = [
        "VoiceQA evaluating monitor",
        f"Time: {now_hkt}",
        f"Status: attention needed ({len(issues)} issue(s))",
        f"Evaluating recordings: {total_evaluating}",
        f"Warn threshold: {stale_seconds // 60} min; timeout: {timeout_seconds // 60} min",
        "",
        "Top affected recordings:",
    ]
    for item in issues[:10]:
        line = (
            f"- {item.issue}: {item.filename} | batch={item.batch_name} | "
            f"age={item.age_minutes}m | updated={item.updated_minutes}m | id={item.recording_id}"
        )
        if item.error:
            line += f" | error={item.error[:160]}"
        lines.append(line)
    if len(issues) > 10:
        lines.append(f"... and {len(issues) - 10} more")
    return "\n".join(lines)


def _collect_evaluating_issues(now: datetime) -> tuple[int, list[EvaluatingIssue]]:
    stale_seconds = max(60, int(settings.EVALUATING_MONITOR_STALE_SECONDS))
    timeout_seconds = max(60, int(settings.RECORDING_EVAL_TIMEOUT_SECONDS))
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
                    UploadBatch.name,
                    UploadBatch.trade_date,
                    latest_running.c.running_since,
                )
                .join(UploadBatch, Recording.batch_id == UploadBatch.id)
                .outerjoin(latest_running, latest_running.c.recording_id == Recording.id)
                .where(Recording.status == "evaluating")
                .order_by(Recording.updated_at.asc())
            )
            .all()
        )

        issues: list[EvaluatingIssue] = []
        for rec, batch_name, batch_date, running_since in rows:
            updated_age = int((now - rec.updated_at).total_seconds())
            running_age = int((now - running_since).total_seconds()) if running_since else None
            issue = None
            age_seconds = updated_age
            if running_since is None and updated_age >= stale_seconds:
                issue = "queued/no running evaluation"
            elif running_age is not None and running_age >= timeout_seconds:
                issue = "timed out running evaluation"
                age_seconds = running_age
            elif running_age is not None and running_age >= stale_seconds:
                issue = "stale running evaluation"
                age_seconds = running_age
            if issue is None:
                continue
            issues.append(
                EvaluatingIssue(
                    recording_id=str(rec.id),
                    filename=rec.original_filename,
                    batch_name=batch_name or str(batch_date),
                    age_minutes=max(0, age_seconds // 60),
                    updated_minutes=max(0, updated_age // 60),
                    issue=issue,
                    error=rec.error,
                )
            )
        return len(rows), issues


@app.task(name="voiceqa.monitor.evaluating_cases")
def monitor_evaluating_cases() -> dict:
    now = datetime.now(UTC)
    total, issues = _collect_evaluating_issues(now)
    notify_ok = bool(settings.EVALUATING_MONITOR_NOTIFY_OK)
    if issues or notify_ok:
        text = _format_monitor_message(
            total_evaluating=total,
            stale_seconds=max(60, int(settings.EVALUATING_MONITOR_STALE_SECONDS)),
            timeout_seconds=max(60, int(settings.RECORDING_EVAL_TIMEOUT_SECONDS)),
            issues=issues,
        )
        sent = _send_feishu(text)
    else:
        sent = False
        logger.info("evaluating monitor OK: {} evaluating recording(s)", total)
    return {"evaluating": total, "issues": len(issues), "notified": sent}
