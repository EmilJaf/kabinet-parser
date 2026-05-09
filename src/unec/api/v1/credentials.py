from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.rate_limit import limiter
from ...db.models import User
from ...services import unec_credentials as creds_service
from ..deps import get_current_user, get_db
from ..schemas import UnecCredentialsIn, UnecCredentialsStatus

router = APIRouter(prefix="/unec/credentials", tags=["unec-credentials"])


@router.put("", response_model=UnecCredentialsStatus)
@limiter.limit("5/15minutes")
async def upsert(
    request: Request,
    payload: UnecCredentialsIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> UnecCredentialsStatus:
    try:
        creds = await creds_service.upsert_credentials(
            session,
            user_id=user.id,
            username=payload.username,
            password=payload.password,
            validate=not payload.skip_validation,
        )
    except creds_service.UnecLoginRejected as exc:
        # Generic message — don't echo UNEC-side errors back to the client.
        # Real cause is in worker logs for the admin via /v1/admin/logs.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="UNEC отклонил логин. Проверь имя/пароль.",
        ) from exc

    return UnecCredentialsStatus(
        configured=True,
        username=creds.username,
        last_login_at=creds.last_login_at,
        updated_at=creds.updated_at,
    )


@router.get("", response_model=UnecCredentialsStatus)
async def status_endpoint(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> UnecCredentialsStatus:
    creds = await creds_service.get_credentials(session, user.id)
    if creds is None:
        return UnecCredentialsStatus(configured=False)
    return UnecCredentialsStatus(
        configured=True,
        username=creds.username,
        last_login_at=creds.last_login_at,
        updated_at=creds.updated_at,
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    await creds_service.delete_credentials(session, user.id)
