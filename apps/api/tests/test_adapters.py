"""Adapter YAML round-trips, submit-selector ban, and skill-loader isolation."""

from pathlib import Path

import pytest

from command_center.api.browser_contracts import AdapterDefinition
from command_center.db.adapters import adapter_revision, load_adapter_definition

REPO = Path(__file__).resolve().parents[2]
ADAPTERS = REPO / "agents" / "skills" / "adapters"


def test_greenhouse_yaml_round_trips():
    adapter = load_adapter_definition("greenhouse")
    assert isinstance(adapter, AdapterDefinition)
    assert adapter.platform == "greenhouse"
    assert adapter.match_host.startswith("boards.greenhouse.io")
    kinds = [step.kind for step in adapter.steps]
    assert kinds[0] == "identity"
    assert kinds.index("resume") > kinds.index("identity")  # identity first
    assert kinds.count("validate") >= 1
    assert kinds[-1] == "validate"  # post-Simplify re-validation


def test_adapter_revision_is_stable_content_hash():
    first = adapter_revision("greenhouse")
    second = adapter_revision("greenhouse")
    assert first == second
    assert len(first) == 64


def test_fill_only_adapters_have_no_submit_selectors():
    """The write-side of the never-submits invariant: no submit selector ships."""
    banned = ("submit", "next", "input[type=submit]")
    for path in ADAPTERS.glob("*.yaml"):
        for step in load_adapter_definition(path.stem).steps:
            selector = (step.selector or "").lower()
            for token in banned:
                assert token not in selector, f"{path.name} contains a {token} selector"


def test_unknown_platform_raises():
    with pytest.raises(ValueError, match="No adapter definition"):
        load_adapter_definition("unknown-ats")


def test_skill_loader_never_ingests_adapters(tmp_path, monkeypatch):
    """adapters/*.yaml is invisible to the runtime agent skill loader."""
    import tomllib

    from command_center.agents.config import load_profiles

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "adapters").mkdir()
    (skills_dir / "adapters" / "greenhouse.yaml").write_text("platform: greenhouse\n")
    (skills_dir / "opportunity-work.md").write_text("Synthetic skill content.")
    directives = tmp_path / "directives"
    directives.mkdir()
    (directives / "research.md").write_text("Synthetic directive content.")
    profiles_path = tmp_path / "profiles.toml"
    profiles_path.write_text(
        tomllib.__name__
        and """
[profiles.synthetic]
name = "Synthetic"
description = "Synthetic profile"
provider = "openai"
model = "gpt-test"
tools = []
delegates = []
skills = ["opportunity-work"]
directive = "research"
max_steps = 1
max_output_tokens = 256
"""
    )
    # A profile cannot reference the adapters subdirectory: slugs cannot contain '/'.
    profiles_bad = profiles_path.read_text().replace(
        'skills = ["opportunity-work"]', 'skills = ["adapters/greenhouse"]'
    )
    bad_path = tmp_path / "profiles-bad.toml"
    bad_path.write_text(profiles_bad)
    with pytest.raises(ValueError):
        load_profiles(str(bad_path), skills_dir=str(skills_dir))
    # The valid profile loads and no skill file named greenhouse.yaml is read.
    profiles, _ = load_profiles(str(profiles_path), skills_dir=str(skills_dir))
    assert set(profiles["synthetic"].skill_files) == {"opportunity-work"}
