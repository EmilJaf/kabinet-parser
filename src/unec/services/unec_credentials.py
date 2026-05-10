from __future__ import annotations

import uuid

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..core.security import (
    decrypt_with_dek,
    encrypt_with_dek,
    generate_dek,
    unwrap_dek,
    wrap_dek,
)
from ..db.models import (
    ExamSyncState,
    GradesSyncState,
    ScheduleSyncState,
    UnecCredentials,
    User,
)
from ..scraper.client import AuthError as UnecAuthError
from ..scraper.client import UnecClient


class UnecCredentialsError(Exception):
    pass


class UnecLoginRejected(UnecCredentialsError):
    """The supplied UNEC username/password failed against the live cabinet."""


async def _validate_against_cabinet(username: str, password: str) -> None:
    settings = get_settings()
    async with UnecClient(base_url=settings.unec_base_url) as client:
        try:
            await client.login(username, password)
        except UnecAuthError as exc:
            raise UnecLoginRejected(str(exc)) from exc


async def _ensure_dek(session: AsyncSession, user: User) -> bytes:
    """Return the user's raw DEK, generating one on first use."""
    if user.encrypted_dek is None:
        raw = generate_dek()
        user.encrypted_dek = wrap_dek(raw)
        session.add(user)
        return raw
    return unwrap_dek(user.encrypted_dek)


async def upsert_credentials(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    username: str,
    password: str,
    validate: bool = True,
) -> UnecCredentials:
    if validate:
        await _validate_against_cabinet(username, password)

    user = await session.get(User, user_id)
    if user is None:
        raise UnecCredentialsError(f"user {user_id} not found")

    raw_dek = await _ensure_dek(session, user)
    encrypted = encrypt_with_dek(raw_dek, password)

    existing = await session.get(UnecCredentials, user_id)
    if existing is None:
        creds = UnecCredentials(user_id=user_id, username=username, encrypted_password=encrypted)
        session.add(creds)
    else:
        existing.username = username
        existing.encrypted_password = encrypted
        creds = existing

    await session.commit()
    await session.refresh(creds)
    return creds


async def get_credentials(session: AsyncSession, user_id: uuid.UUID) -> UnecCredentials | None:
    return await session.get(UnecCredentials, user_id)


async def get_decrypted_password(session: AsyncSession, user_id: uuid.UUID) -> tuple[str, str] | None:
    creds = await get_credentials(session, user_id)
    if creds is None:
        return None
    user = await session.get(User, user_id)
    if user is None or user.encrypted_dek is None:
        # Should not happen — credentials always come with a DEK.
        return None
    raw_dek = unwrap_dek(user.encrypted_dek)
    return creds.username, decrypt_with_dek(raw_dek, creds.encrypted_password)


async def delete_credentials(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Unlink UNEC creds AND wipe the per-user sync_state rows.

    Wiping sync_state means a re-link triggers the InitialSyncBanner
    again (the SPA detects status==None on every section). Stored
    Lessons/Subjects/Marks/Exams are left in place — they'll get
    refreshed by the next sync, no point destroying user data on a
    casual unlink.
    """
    creds = await get_credentials(session, user_id)
    if creds is None:
        return False
    await session.delete(creds)
    for model in (ScheduleSyncState, GradesSyncState, ExamSyncState):
        await session.execute(delete(model).where(model.user_id == user_id))
    await session.commit()
    return True
