"""Export HTTP contracts without database access or credentials."""

import json
from pathlib import Path

from command_center.core.config import Settings
from command_center.main import create_app

settings = Settings(
    _env_file=None,
    environment="test",
    api_token="synthetic-openapi-token-not-a-real-credential",
    database_url="postgresql+psycopg://unused:unused@localhost/unused",
)
path = Path(".local/openapi.json")
path.parent.mkdir(exist_ok=True)
path.write_text(json.dumps(create_app(settings).openapi(), indent=2) + "\n")
print("Exported API contracts to .local/openapi.json")
