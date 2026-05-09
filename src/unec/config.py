import os
from functools import lru_cache
from typing import Annotated

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Only enable Docker-secrets-style file loading when the directory is
# actually mounted; otherwise pydantic-settings emits a warning on every
# import in dev.
_SECRETS_DIR: str | None = "/run/secrets" if os.path.isdir("/run/secrets") else None


class Settings(BaseSettings):
    # secrets_dir lets pydantic-settings load any field from a file under
    # /run/secrets/<field_name> — the standard Docker secrets layout. We
    # pass None in dev (directory not mounted) so there's no startup warning.
    model_config = SettingsConfigDict(
        env_file=".env",
        secrets_dir=_SECRETS_DIR,
        extra="ignore",
    )

    # UNEC scraper (used by CLI and per-user session manager)
    unec_base_url: str = "https://kabinet.unec.edu.az"
    # Personal credentials for the dev CLI; not required when running the API server.
    unec_username: str | None = None
    unec_password: SecretStr | None = None

    # Persistence (host ports differ from container ports to avoid clashes
    # with locally-installed postgres/redis on 5432/6379).
    database_url: str = "postgresql+asyncpg://unec:unec@localhost:5433/unec"
    redis_url: str = "redis://localhost:6380/0"

    # Crypto — KEK (Key Encryption Key).
    # Either set FERNET_KEY (single key, legacy) or FERNET_KEYS (csv, first =
    # primary, rest = read-only fallbacks for rotation). Generate a new key
    # with `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`.
    fernet_key: SecretStr | None = None
    fernet_keys: SecretStr | None = None  # comma-separated, primary first
    # JWT signing secret. Any high-entropy string.
    secret_key: SecretStr | None = None

    # VAPID — Web Push. Public key is shipped to the browser on subscribe;
    # private key signs the server's push messages so the push service trusts
    # us as the origin. vapid_subject is contact info per the spec.
    vapid_public_key: str | None = None
    vapid_private_key: SecretStr | None = None
    vapid_subject: str = "mailto:admin@example.com"
    jwt_algorithm: str = "HS256"
    access_token_ttl_min: int = 30
    refresh_token_ttl_days: int = 30

    # UNEC session lifetime in Redis (PHPSESSID cache before forced re-login)
    unec_session_ttl_min: int = 25

    # CORS origins for the SPA. Override with env var, e.g.
    #   CORS_ORIGINS=http://localhost:5173,https://kabinet.example.com
    # NoDecode prevents pydantic-settings from JSON-parsing the env value;
    # _split_csv_origins below turns the raw string into a list.
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]

    # Auth cookie settings. In dev (local http) we leave Secure off; in prod
    # (HTTPS via Caddy) flip to true via env var so the browser will only send
    # cookies over TLS.
    cookie_secure: bool = False
    cookie_samesite: str = "lax"  # "lax" | "strict" | "none"
    cookie_domain: str | None = None  # None = host-only cookie
    access_cookie_name: str = "kabinet_access"
    refresh_cookie_name: str = "kabinet_refresh"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv_origins(cls, v: object) -> object:
        # pydantic-settings would otherwise try to JSON-decode any str env
        # value for a list field. Accept a comma-separated string instead so
        # CORS_ORIGINS=https://a.com,https://b.com works as expected.
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


# Backwards-compatible alias for the existing CLI helper.
def load_settings() -> Settings:
    return get_settings()
