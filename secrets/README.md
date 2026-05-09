# Production secrets

Files in this directory are mounted as Docker secrets by `docker-compose.prod.yml`
and consumed by the API/worker via `pydantic-settings` (`secrets_dir=/run/secrets`)
and by Postgres via `POSTGRES_PASSWORD_FILE`.

Each secret is **one file, no trailing newline**.

| File                | Used by              | How to generate                                                      |
| ------------------- | -------------------- | -------------------------------------------------------------------- |
| `secret_key`        | API (JWT signing)    | `openssl rand -base64 48`                                            |
| `fernet_keys`       | API/worker (KEK)     | `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"` |
| `postgres_password` | Postgres + composing | `openssl rand -base64 32`                                            |
| `database_url`      | API/worker           | `postgresql+asyncpg://unec:<postgres_password>@postgres:5432/unec`   |
| `vapid_private_key` | API/worker (push)    | `docker compose exec api unec gen-vapid` → copy PRIVATE block         |

## Rotating the KEK

`fernet_keys` is a comma-separated list — primary first. To rotate:

1. Generate a new Fernet key.
2. Prepend it: `<new>,<old>` and redeploy. New writes use `<new>`; reads
   try both, so existing data still decrypts.
3. Run a one-off rewrap that re-encrypts every `users.encrypted_dek` with
   the new primary (uses `core.security.kek_rewrap`).
4. Once nothing references `<old>` anymore, drop it from the file.

The data layer is envelope-encrypted (KEK wraps a per-user DEK), so a
KEK rotation only re-encrypts the small DEK column, not the bulk data.
