"""Projects CRUD — flat workspaces that scope recordings + evaluation config.

RBAC stays global; any config-capable user manages projects. The first
project created becomes the default; one project is always the default
(enforced by a partial unique index).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from voiceqa_shared.audit import log_audit
from voiceqa_shared.db_models import AppSetting, Project, Recording, User

from app.db import get_session
from app.deps import ClientMeta, client_meta
from app.permissions import CONFIG_READ, CONFIG_WRITE, require
from app.queue import celery_client
from app.schemas import (
    EvaluatorDraft,
    EvaluatorGenerateIn,
    ProjectIn,
    ProjectOut,
    ProjectPatch,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])

# Sensible pipeline defaults stamped on every new project so it transcribes
# and evaluates out of the box (good ASR + LLM). Recon/recorder-specific keys
# (filename.parse_regex, recon.*) are intentionally omitted.
NEW_PROJECT_SETTINGS: dict[str, object] = {
    "audio.broker_channel": "left",
    "asr.provider": "tencent",
    "asr.model": "16k_zh_en",
    "asr.language_mode": "auto",
    "asr.adaptation": "off",
    "asr.adaptation_boost": 5,
    "llm.model": "gemini-3.5-flash",
    "retention.days": 365,
    "budget.llm_daily_tokens": 10_000_000,
    "budget.stt_daily_seconds": 180_000,
}


def _out(p: Project, recording_count: int | None = None) -> ProjectOut:
    return ProjectOut(
        id=p.id,
        slug=p.slug,
        name=p.name,
        description=p.description,
        modules=p.modules or {},
        eval_prompt_context=p.eval_prompt_context,
        branding=p.branding or {},
        is_default=p.is_default,
        active=p.active,
        recording_count=recording_count,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    include_inactive: bool = False,
    user: User = Depends(require(CONFIG_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[ProjectOut]:
    stmt = select(Project).order_by(Project.is_default.desc(), Project.name)
    if not include_inactive:
        stmt = stmt.where(Project.active.is_(True))
    projects = (await session.execute(stmt)).scalars().all()
    counts = dict(
        (
            await session.execute(
                select(Recording.project_id, func.count()).group_by(Recording.project_id)
            )
        ).all()
    )
    return [_out(p, counts.get(p.id, 0)) for p in projects]


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectIn,
    user: User = Depends(require(CONFIG_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> ProjectOut:
    dup = (
        await session.execute(select(Project.id).where(Project.slug == payload.slug))
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"project slug {payload.slug!r} already exists")
    first = (await session.execute(select(Project.id).limit(1))).scalar_one_or_none() is None
    project = Project(
        slug=payload.slug,
        name=payload.name,
        description=payload.description,
        modules=payload.modules,
        eval_prompt_context=payload.eval_prompt_context,
        branding=payload.branding,
        is_default=first,
        created_by=user.id,
    )
    session.add(project)
    await session.flush()
    for skey, sval in NEW_PROJECT_SETTINGS.items():
        session.add(AppSetting(project_id=project.id, key=skey, value=sval))
    log_audit(
        session, action="project.create", user_id=user.id, actor_email=user.email,
        object_type="project", object_id=str(project.id), details={"slug": project.slug},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    await session.refresh(project)
    return _out(project, 0)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: uuid.UUID,
    user: User = Depends(require(CONFIG_READ)),
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    count = (
        await session.execute(
            select(func.count()).select_from(Recording).where(Recording.project_id == project_id)
        )
    ).scalar_one()
    return _out(project, count)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectPatch,
    user: User = Depends(require(CONFIG_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> ProjectOut:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    data = payload.model_dump(exclude_unset=True)
    make_default = data.pop("is_default", None)
    for key, value in data.items():
        setattr(project, key, value)
    if make_default:
        # One default at a time (partial unique index) — demote the current one.
        await session.execute(update(Project).where(Project.is_default.is_(True)).values(is_default=False))
        project.is_default = True
    log_audit(
        session, action="project.update", user_id=user.id, actor_email=user.email,
        object_type="project", object_id=str(project.id), details={"slug": project.slug},
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    await session.refresh(project)
    return _out(project)


@router.post("/{project_id}/evaluator/generate", response_model=EvaluatorDraft)
async def generate_evaluator(
    project_id: uuid.UUID,
    payload: EvaluatorGenerateIn,
    user: User = Depends(require(CONFIG_WRITE)),
    session: AsyncSession = Depends(get_session),
    meta: ClientMeta = Depends(client_meta),
) -> EvaluatorDraft:
    """Draft criteria + extraction fields from a description (LLM, in the
    worker). Returns drafts to review/edit — nothing is saved here."""
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    async_result = celery_client.send_task(
        "voiceqa.evaluator.generate_criteria",
        args=[payload.description, str(project_id), project.eval_prompt_context],
        queue="llm",
    )
    try:
        drafts = await run_in_threadpool(lambda: async_result.get(timeout=120, propagate=True))
    except Exception as e:  # surface any worker/LLM failure as a 502
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"criteria generation failed: {e}"
        ) from e
    log_audit(
        session, action="evaluator.generate", user_id=user.id, actor_email=user.email,
        object_type="project", object_id=str(project_id),
        details={
            "criteria": len(drafts.get("criteria", [])),
            "fields": len(drafts.get("extraction_fields", [])),
        },
        ip=meta.ip, user_agent=meta.user_agent,
    )
    await session.commit()
    return EvaluatorDraft(**drafts)
