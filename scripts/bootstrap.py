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


if __name__ == "__main__":
    main()
