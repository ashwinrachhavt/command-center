"""Generate missing local Langfuse credentials without printing or replacing secrets."""

import os
import secrets
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    path = ROOT / ".env"
    existing = dotenv_values(path)
    values = {
        "CC_LANGFUSE_ENABLED": "true",
        "LANGFUSE_BASE_URL": "http://localhost:3003",
        "CC_LANGFUSE_DOCKER_URL": "http://host.docker.internal:3003",
        "LANGFUSE_PUBLIC_KEY": f"pk-lf-{uuid4()}",
        "LANGFUSE_SECRET_KEY": f"sk-lf-{secrets.token_hex(32)}",
        "CC_LANGFUSE_USER_EMAIL": "admin@command-center.local",
        **{
            f"CC_LANGFUSE_{name}": secrets.token_hex(32)
            for name in (
                "DB_PASSWORD",
                "AUTH_SECRET",
                "SALT",
                "ENCRYPTION_KEY",
                "REDIS_PASSWORD",
                "STORAGE_PASSWORD",
                "USER_PASSWORD",
            )
        },
    }
    for key, value in values.items():
        if not existing.get(key) or key == "CC_LANGFUSE_ENABLED":
            set_key(path, key, value, quote_mode="never")
    os.chmod(path, 0o600)
    print("Langfuse settings ready in root .env; existing values preserved.")
    print(
        "UI: http://localhost:3003; login: CC_LANGFUSE_USER_EMAIL / CC_LANGFUSE_USER_PASSWORD."
    )


if __name__ == "__main__":
    main()
