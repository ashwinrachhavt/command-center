"""Declarative site adapters served to browser devices; never agent skills."""

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from command_center.api.browser_contracts import AdapterDefinition

# Resolved from this module, so the relative repo path works from any cwd.
ADAPTERS_DIR = Path(__file__).resolve().parents[5] / "agents" / "skills" / "adapters"


@lru_cache(maxsize=16)
def _load(platform: str) -> tuple[AdapterDefinition | None, str]:
    """Parse one adapter YAML; the revision is the file-content sha256."""
    path = ADAPTERS_DIR / f"{platform}.yaml"
    if not path.exists():
        return None, ""
    try:
        content = path.read_text()
        data: dict[str, Any] = yaml.safe_load(content)
        data["revision"] = hashlib.sha256(content.encode()).hexdigest()
        adapter = AdapterDefinition.model_validate(data)
        return adapter, adapter.revision
    except Exception:  # invalid YAML or schema: surfaced as a 503, never a crash
        return None, ""


def load_adapter_definition(platform: str) -> AdapterDefinition:
    """Serve one adapter definition or raise for an unknown/invalid platform."""
    adapter, _ = _load(platform)
    if adapter is None:
        raise ValueError(f"No adapter definition is available for {platform}")
    return adapter


def adapter_revision(platform: str) -> str:
    """The content hash pinned onto runs, or empty when unavailable."""
    _, revision = _load(platform)
    return revision
