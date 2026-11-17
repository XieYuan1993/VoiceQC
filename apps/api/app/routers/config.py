"""App settings: GET all, PUT one — every key has a validator.

(The module is named config.py, not settings.py, so imports don't shadow
app.settings.)
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared.audit import log_audit
from voiceqa_shared.db_models import AppSetting, User

from app.db import get_session
from app.deps import ClientMeta, client_meta, resolve_project_id
from app.permissions import CONFIG_READ, CONFIG_WRITE, TRANSCRIPTS_READ, require
from app.schemas import SettingOut, SettingPut

router = APIRouter(prefix="/api/settings", tags=["settings"])

LANGUAGE_MODES = {"auto", "yue-Hant-HK", "cmn-Hans-CN", "en-US"}
RECON_COMPONENTS = {"stock", "side", "quantity", "price", "client", "time"}


def _v_language_mode(v: Any) -> None:
    if v not in LANGUAGE_MODES:
        raise ValueError(f"must be one of {sorted(LANGUAGE_MODES)}")


def _v_output_script(v: Any) -> None:
    if v not in ("original", "traditional"):
        raise ValueError("must be 'original' or 'traditional'")


def _v_nonempty_str(v: Any) -> None:
    if not isinstance(v, str) or not v.strip():
        raise ValueError("must be a non-empty string")


def _v_broker_channel(v: Any) -> None:
    if v not in ("left", "right"):
        raise ValueError("must be 'left' or 'right'")


def _v_filename_regex(v: Any) -> None:
    _v_nonempty_str(v)
    try:
        compiled = re.compile(v)
    except re.error as e:
        raise ValueError(f"invalid regex: {e}") from e
    if "broker_ext" not in compiled.groupindex:
        raise ValueError("regex must define a (?P<broker_ext>...) named group")


def _v_pos_int(lo: int = 1, hi: int = 10**12):
    def check(v: Any) -> None:
        if not isinstance(v, int) or isinstance(v, bool) or not (lo <= v <= hi):
            raise ValueError(f"must be an integer in [{lo}, {hi}]")

    return check


def _v_bool(v: Any) -> None:
    if not isinstance(v, bool):
        raise ValueError("must be a boolean")


def _v_recon_weights(v: Any) -> None:
    if not isinstance(v, dict) or not set(v) <= RECON_COMPONENTS:
        raise ValueError(f"must be a dict with keys among {sorted(RECON_COMPONENTS)}")
    for key, val in v.items():
        if not isinstance(val, int | float) or not (0 <= val <= 1):
            raise ValueError(f"{key}: weight must be in [0, 1]")


def _v_recon_thresholds(v: Any) -> None:
    if (
        not isinstance(v, dict)
        or set(v) != {"auto_match", "needs_review"}
        or not all(isinstance(x, int | float) and 0 <= x <= 1 for x in v.values())
        or v["auto_match"] <= v["needs_review"]
    ):
        raise ValueError("needs {auto_match, needs_review} in [0,1] with auto_match > needs_review")


def _v_time_window(v: Any) -> None:
    if (
        not isinstance(v, dict)
        or set(v) != {"before_hours", "after_minutes"}
        or not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in v.values())
    ):
        raise ValueError("needs non-negative integers {before_hours, after_minutes}")


def _v_recon_transaction_filters(v: Any) -> None:
    if not isinstance(v, dict) or set(v) != {"order_statuses", "execution_types"}:
        raise ValueError("needs {order_statuses, execution_types}")
    for key in ("order_statuses", "execution_types"):
        values = v.get(key)
        if not isinstance(values, list) or not all(isinstance(x, str) for x in values):
            raise ValueError(f"{key}: must be a list of strings")


def _v_provider(v: Any) -> None:
    if v not in ("google", "gemini", "qwen", "tencent", "dyna"):
        raise ValueError(
            "must be 'google' (chirp STT), 'gemini' (multimodal), "
            "'qwen' (Qwen3-ASR), 'tencent' (Tencent ASR), or 'dyna' (ASR + Flow)"
        )


def _v_adaptation(v: Any) -> None:
    if v not in ("off", "stock_only", "all"):
        raise ValueError("must be 'off', 'stock_only', or 'all'")


def _v_boost(v: Any) -> None:
    if not isinstance(v, int | float) or isinstance(v, bool) or not (0 <= v <= 20):
        raise ValueError("must be a number in [0, 20]")


def _v_llm_provider(v: Any) -> None:
    if v not in ("gemini", "dashscope"):
        raise ValueError("must be 'gemini' or 'dashscope'")


def _v_correction_replacements(v: Any) -> None:
    if not isinstance(v, list) or len(v) > 500:
        raise ValueError("must be a list with at most 500 correction rules")
    for index, item in enumerate(v):
        if not isinstance(item, dict) or not {"wrong", "correct"} <= set(item):
            raise ValueError(f"rule {index} needs wrong and correct strings")
        if set(item) - {"wrong", "correct", "context"}:
            raise ValueError(f"rule {index} has unknown fields")
        for key in ("wrong", "correct"):
            value = item.get(key)
            if not isinstance(value, str) or not value.strip() or len(value) > 200:
                raise ValueError(f"rule {index} {key} must be a non-empty short string")
        context = item.get("context", "")
        if not isinstance(context, str) or len(context) > 1000:
            raise ValueError(f"rule {index} context must be a string up to 1000 characters")


SUPERVISOR_DEFAULT = {"name": "", "email_enabled": False, "email": "", "sms_enabled": False, "phone": ""}


def _v_supervisor(v):
    if not isinstance(v, dict) or set(v) != set(SUPERVISOR_DEFAULT):
        raise ValueError("invalid supervisor configuration")
    if any(type(v[key]) is not bool for key in ("email_enabled", "sms_enabled")):
        raise ValueError("switches must be boolean")
    if any(not isinstance(v[key], str) or len(v[key]) > 254 for key in ("name", "email", "phone")):
        raise ValueError("invalid contact details")
    if v["email_enabled"] and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", v["email"]):
        raise ValueError("valid email required")
    if v["sms_enabled"] and not re.fullmatch(r"\+?[0-9][0-9 ()-]{5,24}", v["phone"]):
        raise ValueError("valid phone required")


@router.get("/supervisor-notification")
async def supervisor_notification(project_id: uuid.UUID = Depends(resolve_project_id), user: User = Depends(require(TRANSCRIPTS_READ)), session: AsyncSession = Depends(get_session)):
    row = await session.get(AppSetting, (project_id, "notification.supervisor"))
    return row.value if row else dict(SUPERVISOR_DEFAULT)


NAVIGATION_PATHS = {"/dashboard", "/recordings", "/risks", "/review", "/agents", "/batches",
                    "/evaluator", "/amendments", "/transactions", "/recon", "/admin"}


def _v_navigation(value):
    if not isinstance(value, dict) or not set(value) <= NAVIGATION_PATHS:
        raise ValueError("invalid menu paths")
    if any(type(visible) is not bool for visible in value.values()):
        raise ValueError("menu visibility must be boolean")


@router.get("/navigation")
async def navigation(project_id: uuid.UUID = Depends(resolve_project_id),
                     user: User = Depends(require(TRANSCRIPTS_READ)),
                     session: AsyncSession = Depends(get_session)):
    row = await session.get(AppSetting, (project_id, "ui.navigation"))
    return row.value if row else {}


VALIDATORS: dict[str, Any] = {
    "ui.navigation": _v_navigation,
    "notification.supervisor": _v_supervisor,
    "asr.provider": _v_provider,
    "asr.language_mode": _v_language_mode,
    "asr.output_script": _v_output_script,
    "asr.model": _v_nonempty_str,
    "asr.adaptation": _v_adaptation,
    "asr.adaptation_boost": _v_boost,
    "asr.mono_speaker_repair": _v_bool,
    "asr.mono_speaker_repair_model": _v_nonempty_str,
    "asr.post_correction_enabled": _v_bool,
    "asr.audio_review_enabled": _v_bool,
    "asr.post_correction_allow_numeric_changes": _v_bool,
    "asr.post_correction_provider": _v_llm_provider,
    "asr.post_correction_model": _v_nonempty_str,
    "asr.post_correction_replacements": _v_correction_replacements,
    "llm.model": _v_nonempty_str,
    "audio.broker_channel": _v_broker_channel,
    "filename.parse_regex": _v_filename_regex,
    "retention.days": _v_pos_int(1, 3650),
    "budget.llm_daily_tokens": _v_pos_int(),
    "budget.stt_daily_seconds": _v_pos_int(),
    "recon.weights": _v_recon_weights,
    "recon.thresholds": _v_recon_thresholds,
    "recon.time_window": _v_time_window,
    "recon.phone_only": _v_bool,
}


@router.get("", response_model=list[SettingOut])
async def list_settings(
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(CONFIG_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[SettingOut]:
    rows = (
        await session.execute(
            select(AppSetting)
            .where(
                AppSetting.project_id == project_id,
                AppSetting.key != "recon.transaction_filters",
            )
            .order_by(AppSetting.key)
        )
    ).scalars().all()
    result = [SettingOut(key=r.key, value=r.value, updated_at=r.updated_at) for r in rows]
    if not any(row.key == "asr.audio_review_enabled" for row in rows):
        result.append(SettingOut(key="asr.audio_review_enabled", value=False, updated_at=datetime.now(UTC)))
    return result


@router.put("/{key}", response_model=SettingOut)
async def put_setting(
    key: str,
    payload: SettingPut,
    project_id: uuid.UUID = Depends(resolve_project_id),
    user: User = Depends(require(CONFIG_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> SettingOut:
    validator = VALIDATORS.get(key)
    if validator is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown setting key {key!r}")
    try:
        validator(payload.value)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{key}: {e}") from e

    row = await session.get(AppSetting, (project_id, key))
    old = row.value if row is not None else None
    if row is None:
        row = AppSetting(project_id=project_id, key=key, value=payload.value, updated_by=user.id)
        session.add(row)
    else:
        row.value = payload.value
        row.updated_by = user.id
    log_audit(
        session, action="settings.update", user_id=user.id, actor_email=user.email,
        object_type="setting", object_id=key, details={"old": old, "new": payload.value},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    # updated_at is a server-side onupdate value — expired after the UPDATE;
    # refresh explicitly or the attribute read triggers sync IO (MissingGreenlet).
    await session.refresh(row)
    return SettingOut(key=row.key, value=row.value, updated_at=row.updated_at)
