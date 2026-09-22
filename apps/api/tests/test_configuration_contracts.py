import runpy
from pathlib import Path

import pytest
from dotenv import dotenv_values
from pydantic import ValidationError

from command_center.agents.config import load_profiles
from command_center.agents.readiness import wait_until_ready
from command_center.api.browser_contracts import ApplyMessage, FormField

ROOT = Path(__file__).resolve().parents[3]
sync = runpy.run_path(str(ROOT / "scripts/sync_env.py"))["sync"]


def environment(root: Path) -> None:
    (root / "apps/web").mkdir(parents=True)
    (root / ".env.example").write_text((ROOT / ".env.example").read_text())
    (root / ".env").write_text("OPENAI_API_KEY=synthetic-server-only\n")


def test_environment_migrates_legacy_keys_and_projects_only_web_settings(tmp_path):
    environment(tmp_path)
    (tmp_path / "apps/web/.env").write_text("CLERK_SECRET_KEY=synthetic-clerk\n")
    (tmp_path / "apps/web/.env.local").write_text("CC_API_URL=http://localhost:8000\n")
    sync(tmp_path)
    root = dotenv_values(tmp_path / ".env")
    web = dotenv_values(tmp_path / "apps/web/.env.local")
    assert root["CLERK_SECRET_KEY"] == web["CLERK_SECRET_KEY"] == "synthetic-clerk"
    assert "OPENAI_API_KEY" not in web
    assert web["CC_API_URL"] == "http://localhost:8000"
    assert not (tmp_path / "apps/web/.env").exists()
    assert (tmp_path / "apps/web/.env.local").stat().st_mode & 0o777 == 0o600
    sync(tmp_path, check=True)
    (tmp_path / ".env").write_text((tmp_path / ".env").read_text() + "\nCLERK_SECRET_KEY=changed\n")
    with pytest.raises(ValueError, match="stale"):
        sync(tmp_path, check=True)
    sync(tmp_path)
    assert dotenv_values(tmp_path / "apps/web/.env.local")["CLERK_SECRET_KEY"] == "changed"


def test_conflicting_environment_is_not_overwritten_or_disclosed(tmp_path):
    environment(tmp_path)
    (tmp_path / ".env").write_text("CLERK_SECRET_KEY=synthetic-root\n")
    legacy = tmp_path / "apps/web/.env"
    legacy.write_text("CLERK_SECRET_KEY=synthetic-web\n")
    before = legacy.read_text()
    with pytest.raises(ValueError, match="Conflicting CLERK_SECRET_KEY") as error:
        sync(tmp_path)
    assert "synthetic" not in str(error.value)
    assert legacy.read_text() == before


def test_directive_revision_and_traversal(tmp_path):
    (tmp_path / "directives").mkdir()
    directive = tmp_path / "directives/research.md"
    directive.write_text("Synthetic directive one")
    config = tmp_path / "profiles.toml"
    template = '[profiles.test]\nname="Test"\ndescription="Test"\nmodel="test"\ndirective="{}"\n'
    config.write_text(template.format("research"))
    profiles, first = load_profiles(str(config))
    assert profiles["test"].instructions == "Synthetic directive one"
    directive.write_text("Synthetic directive two")
    assert load_profiles(str(config))[1] != first
    config.write_text(template.format("../outside"))
    with pytest.raises(ValueError, match="directive slug"):
        load_profiles(str(config))
    config.write_text(template.format("research") + 'instructions="inline"\n')
    with pytest.raises(ValueError, match="inline instructions"):
        load_profiles(str(config))


def test_readiness_retries_and_fails_closed_without_connection_details(mocker):
    mocker.patch("command_center.agents.readiness.time.sleep")
    probe = mocker.Mock(side_effect=[ConnectionError("secret"), None])
    wait_until_ready(probe)
    assert probe.call_count == 2
    with pytest.raises(RuntimeError, match="deadline") as error:
        wait_until_ready(mocker.Mock(side_effect=ConnectionError("secret")), timeout=0)
    assert "secret" not in str(error.value)


def test_browser_contract_rejects_oversized_options_and_unversioned_messages():
    with pytest.raises(ValidationError):
        FormField(id="f0", label="Role", type="select", options=["x" * 301])
    with pytest.raises(ValidationError):
        ApplyMessage.model_validate({"action": "apply", "command": {}})


def test_combined_directive_and_skills_are_bounded_before_enqueue(tmp_path):
    (tmp_path / "directives").mkdir()
    (tmp_path / "skills").mkdir()
    (tmp_path / "directives/research.md").write_text("d" * 15000)
    (tmp_path / "skills/research.md").write_text("s" * 6000)
    config = tmp_path / "profiles.toml"
    config.write_text(
        '[profiles.test]\nname="Test"\ndescription="Test"\nmodel="test"\n'
        'directive="research"\nskills=["research"]\n'
    )
    with pytest.raises(ValidationError):
        load_profiles(str(config), str(tmp_path / "skills"))
