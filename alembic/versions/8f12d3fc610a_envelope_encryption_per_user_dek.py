"""envelope encryption per-user dek

Revision ID: 8f12d3fc610a
Revises: 29bfe4193df0
Create Date: 2026-05-06 22:17:37.900731

Adds users.encrypted_dek and migrates existing UNEC credentials from
"encrypted directly with KEK" to "encrypted with per-user DEK, where the
DEK itself is KEK-wrapped". Reads the active KEK via core.security so it
honours both FERNET_KEY and FERNET_KEYS configurations.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from cryptography.fernet import Fernet, InvalidToken

from unec.core.security import (
    encrypt_with_dek,
    generate_dek,
    kek_decrypt,
    wrap_dek,
)


# revision identifiers, used by Alembic.
revision: str = '8f12d3fc610a'
down_revision: Union[str, Sequence[str], None] = '29bfe4193df0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('encrypted_dek', sa.LargeBinary(), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT user_id, encrypted_password FROM unec_credentials")
    ).fetchall()

    for user_id, encrypted_password in rows:
        # Decrypt the existing password with the KEK directly (legacy layout).
        try:
            plain = kek_decrypt(bytes(encrypted_password)).decode()
        except RuntimeError:
            # Couldn't decrypt — leave it; deployment must rotate FERNET_KEYS
            # to include the legacy key, then re-run this migration step. We
            # raise so the migration fails loudly rather than silently
            # orphaning a user's credentials.
            raise RuntimeError(
                f"Cannot decrypt unec_credentials for user {user_id} with the "
                "configured FERNET_KEY(S). Set FERNET_KEYS to include the key "
                "that originally encrypted this row, then re-run the migration."
            )

        raw_dek = generate_dek()
        wrapped_dek = wrap_dek(raw_dek)
        new_encrypted_password = encrypt_with_dek(raw_dek, plain)

        bind.execute(
            sa.text("UPDATE users SET encrypted_dek = :dek WHERE id = :uid"),
            {"dek": wrapped_dek, "uid": user_id},
        )
        bind.execute(
            sa.text(
                "UPDATE unec_credentials SET encrypted_password = :pw "
                "WHERE user_id = :uid"
            ),
            {"pw": new_encrypted_password, "uid": user_id},
        )


def downgrade() -> None:
    """Re-encrypt UNEC passwords directly with the KEK and drop the DEK column.

    Will fail if any user's DEK can't be unwrapped (e.g. KEK rotation lost
    the original key).
    """
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT u.id, u.encrypted_dek, c.encrypted_password "
            "FROM users u JOIN unec_credentials c ON c.user_id = u.id"
        )
    ).fetchall()

    for user_id, encrypted_dek, encrypted_password in rows:
        if encrypted_dek is None:
            continue
        raw_dek = kek_decrypt(bytes(encrypted_dek))
        try:
            plain = Fernet(raw_dek).decrypt(bytes(encrypted_password)).decode()
        except InvalidToken as exc:
            raise RuntimeError(
                f"Cannot decrypt password for user {user_id} during downgrade"
            ) from exc
        # Re-encrypt with raw KEK (legacy layout).
        from unec.core.security import kek_encrypt
        legacy_blob = kek_encrypt(plain.encode())
        bind.execute(
            sa.text(
                "UPDATE unec_credentials SET encrypted_password = :pw "
                "WHERE user_id = :uid"
            ),
            {"pw": legacy_blob, "uid": user_id},
        )

    op.drop_column('users', 'encrypted_dek')
