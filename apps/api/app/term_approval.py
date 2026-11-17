"""Submission state and atomic publication of approved correction rules."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import text
from voiceqa_shared.db_models import AppSetting


def mark_pending(term, user):
    term.active = False
    term.approval_status = "pending"
    term.submitted_by = user.email
    term.submitted_at = datetime.now(UTC)
    term.reviewed_by = None
    term.reviewed_at = None


def require_admin(user):
    if user.role != "admin":
        raise HTTPException(403, "Only administrators can approve or reject terms")


async def lock_terms(session, project_id):
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"transcript-hotwords:{project_id}"},
    )


def merge_rules(existing, pending):
    rules = list(existing)
    for rule in pending:
        if any(
            item["wrong"] == rule["wrong"] and item["correct"] != rule["correct"] for item in rules
        ):
            raise HTTPException(409, "A different correction already exists for this word")
        if not any(
            item["wrong"] == rule["wrong"] and item["correct"] == rule["correct"] for item in rules
        ):
            rules.append(rule)
    if len(rules) > 500:
        raise HTTPException(400, "This project already has 500 correction annotations")
    return rules


async def publish_rules(session, term, user):
    if not term.pending_rules:
        return
    setting = await session.get(AppSetting, (term.project_id, "asr.post_correction_replacements"))
    rules = merge_rules(setting.value or [] if setting else [], term.pending_rules)
    if setting:
        setting.value, setting.updated_by = rules, user.id
    else:
        session.add(
            AppSetting(
                project_id=term.project_id,
                key="asr.post_correction_replacements",
                value=rules,
                updated_by=user.id,
            )
        )
