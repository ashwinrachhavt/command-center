import runpy
from pathlib import Path
from uuid import UUID

import pytest
from dotenv import dotenv_values
from pydantic import ValidationError

from command_center.agents.config import load_profiles
from command_center.agents.readiness import wait_until_ready
from command_center.api.browser_contracts import (
    ApplyMessage,
    FileTransfer,
    FillCreate,
    FormField,
    InspectMessage,
    SnapshotCreate,
)

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
    FormField(
        id="f0",
        label="Country",
        type="select",
        options=[f"country-{index}" for index in range(300)],
        value_state="empty",
    )
    with pytest.raises(ValidationError):
        FormField(
            id="f0",
            label="Country",
            type="select",
            options=[f"country-{index}" for index in range(301)],
            value_state="empty",
        )
    with pytest.raises(ValidationError):
        ApplyMessage.model_validate({"action": "apply", "command": {}})


def test_browser_number_contract_requires_normalized_finite_constraints():
    field = FormField.model_validate(
        {
            "id": "f0",
            "label": "Years of experience",
            "type": "number",
            "value_state": "empty",
            "numeric_constraints": {
                "minimum": ".1",
                "maximum": "1.1e1",
                "step": "0.2",
                "step_base": ".1",
            },
        }
    )
    assert field.numeric_constraints is not None
    assert field.numeric_constraints.step == "0.2"

    invalid_constraints = [
        {"minimum": "NaN", "maximum": None, "step": "1", "step_base": "0"},
        {"minimum": "+1", "maximum": None, "step": "1", "step_base": "0"},
        {"minimum": "1.", "maximum": None, "step": "1", "step_base": "0"},
        {"minimum": "1e999", "maximum": None, "step": "1", "step_base": "0"},
        {"minimum": None, "maximum": None, "step": "0", "step_base": "0"},
        {"minimum": "2", "maximum": "1", "step": "any", "step_base": "2"},
        {"minimum": None, "maximum": None, "step": "Infinity", "step_base": "0"},
    ]
    for constraints in invalid_constraints:
        with pytest.raises(ValidationError):
            FormField.model_validate(
                {
                    "id": "f0",
                    "label": "Years",
                    "type": "number",
                    "value_state": "empty",
                    "numeric_constraints": constraints,
                }
            )
    with pytest.raises(ValidationError):
        FormField.model_validate(
            {"id": "f0", "label": "Years", "type": "number", "value_state": "empty"}
        )
    with pytest.raises(ValidationError):
        FormField.model_validate(
            {
                "id": "f0",
                "label": "Name",
                "type": "text",
                "value_state": "empty",
                "numeric_constraints": {
                    "minimum": None,
                    "maximum": None,
                    "step": "1",
                    "step_base": "0",
                },
            }
        )


def test_browser_v2_contract_preserves_value_metadata_and_rejects_v1():
    field = FormField.model_validate(
        {
            "id": "f2",
            "label": "Authorization",
            "type": "radio",
            "required": True,
            "options": ["yes", "no"],
            "option_labels": {"yes": "Yes", "no": "No"},
            "value_state": "present",
            "autocomplete": "off",
        }
    )
    snapshot = SnapshotCreate.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000002",
            "protocol_version": 2,
            "page_url": "https://example.com/apply",
            "title": "Synthetic application",
            "fields": [field.model_dump()],
        }
    )
    assert snapshot.protocol_version == 2
    assert field.value_state == "present"
    assert field.option_labels["yes"] == "Yes"
    with pytest.raises(ValidationError):
        FormField.model_validate(
            {
                **field.model_dump(),
                "option_labels": {"maybe": "Maybe"},
            }
        )
    with pytest.raises(ValidationError):
        InspectMessage.model_validate({"version": 1, "action": "inspect"})
    with pytest.raises(ValidationError):
        SnapshotCreate.model_validate(
            {
                "id": "00000000-0000-0000-0000-000000000002",
                "protocol_version": 1,
                "page_url": "https://example.com/apply",
                "title": "Legacy",
                "fields": [],
            }
        )


def test_fill_contract_requires_disjoint_requested_fields_and_explicit_replacements():
    version_id = "00000000-0000-0000-0000-000000000004"
    base = {
        "snapshot_id": "00000000-0000-0000-0000-000000000003",
        "fields": {"f0": "Synthetic person"},
        "uploads": {"f1": version_id},
        "replace_fields": ["f0"],
    }
    assert FillCreate.model_validate(base).uploads["f1"] == UUID(version_id)
    with pytest.raises(ValidationError):
        FillCreate.model_validate({"snapshot_id": base["snapshot_id"]})
    with pytest.raises(ValidationError):
        FillCreate.model_validate({**base, "uploads": {"f0": version_id}})
    with pytest.raises(ValidationError):
        FillCreate.model_validate({**base, "replace_fields": ["f9"]})


def test_file_transfer_validates_exact_bytes_size_and_digest():
    import base64
    import hashlib

    content = b"synthetic resume bytes"
    payload = {
        "version_id": "00000000-0000-0000-0000-000000000005",
        "filename": "resume.txt",
        "media_type": "text/plain",
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "data_base64": base64.b64encode(content).decode(),
    }
    assert FileTransfer.model_validate(payload).size_bytes == len(content)
    with pytest.raises(ValidationError):
        FileTransfer.model_validate({**payload, "sha256": "0" * 64})


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
