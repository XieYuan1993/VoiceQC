"""/api/me — the signed-in user."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from voiceqa_shared.db_models import User

from app.deps import current_user
from app.schemas import MeResponse

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/me", response_model=MeResponse)
async def get_me(user: User = Depends(current_user)) -> MeResponse:
    return MeResponse(id=user.id, email=user.email, name=user.name, role=user.role)
