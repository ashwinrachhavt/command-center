"""Create private local configuration without overwriting existing settings."""

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(content)


def main() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        password = secrets.token_hex(24)
        token = secrets.token_hex(32)
        content = (ROOT / ".env.example").read_text()
        content = content.replace(
            "CC_API_TOKEN=GENERATE_WITH_BOOTSTRAP", f"CC_API_TOKEN={token}"
        )
        content = content.replace("GENERATE_WITH_BOOTSTRAP", password)
        write_private(env_path, content)
        print("Created .env with generated local credentials (mode 0600).")
    else:
        print("Preserved existing .env.")

    web_env = ROOT / "apps/web/.env.local"
    if not web_env.exists():
        # Keep host development configuration server-only; never use NEXT_PUBLIC_ for secrets.
        values = dict(
            line.split("=", 1)
            for line in env_path.read_text().splitlines()
            if "=" in line and not line.startswith("#")
        )
        write_private(
            web_env,
            f"CC_API_URL=http://127.0.0.1:{values.get('API_PORT', '8000')}\n",
        )
        print("Created apps/web/.env.local (mode 0600).")

    clerk_env = ROOT / "apps/web/.env"
    if not clerk_env.exists():
        write_private(clerk_env, (ROOT / "apps/web/.env.example").read_text())
        print("Created apps/web/.env. Add Clerk keys, then run make auth-sync.")


if __name__ == "__main__":
    main()
