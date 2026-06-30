"""App settings: GET all, PUT one — every key has a validator.

(The module is named config.py, not settings.py, so imports don't shadow
app.settings.)
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared.audit import log_audit
from voiceqa_shared.db_models import AppSetting, User

from app.db import get_session
from app.deps import ClientMeta, client_meta, resolve_project_id
from app.permissions import CONFIG_READ, CONFIG_WRITE, require
from app.schemas import SettingOut, SettingPut

router = APIRouter(prefix="/api/settings", tags=["settings"])

LANGUAGE_MODES = {"auto", "yue-Hant-HK", "cmn-Hans-CN", "en-US"}
RECON_COMPONENTS = {"stock", "side", "quantity", "price", "client", "time"}


def _v_language_mode(v: Any) -> None:
    if v not in LANGUAGE_MODES:
        raise ValueError(f"must be one of {sorted(LANGUAGE_MODES)}")


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


def _v_provider(v: Any) -> None:
    if v not in ("google", "gemini", "qwen"):
        raise ValueError("must be 'google' (chirp STT), 'gemini' (multimodal), or 'qwen' (Qwen3-ASR)")


def _v_adaptation(v: Any) -> None:
    if v not in ("off", "stock_only", "all"):
        raise ValueError("must be 'off', 'stock_only', or 'all'")


def _v_boost(v: Any) -> None:
    if not isinstance(v, int | float) or isinstance(v, bool) or not (0 <= v <= 20):
        raise ValueError("must be a number in [0, 20]")


VALIDATORS: dict[str, Any] = {
    "asr.provider": _v_provider,
    "asr.language_mode": _v_language_mode,
    "asr.model": _v_nonempty_str,
    "asr.adaptation": _v_adaptation,
    "asr.adaptation_boost": _v_boost,
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
            select(AppSetting).where(AppSetting.project_id == project_id).order_by(AppSetting.key)
        )
    ).scalars().all()
    return [SettingOut(key=r.key, value=r.value, updated_at=r.updated_at) for r in rows]


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
