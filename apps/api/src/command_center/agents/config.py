import hashlib
import re
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ModelProvider = Literal["openai", "gemini", "mistral", "cohere"]


class ComposioTool(BaseModel):
    model_config = ConfigDict(extra="forbid")
    toolkit: str = Field(pattern=r"^[a-z0-9_]+$")
    slug: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    version: str = Field(min_length=4, pattern=r"^[0-9]{8}_[0-9]+$")
    read_only: Literal[True]


class AgentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str
    provider: ModelProvider = "openai"
    model: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$",
    )
    instructions: str = Field(max_length=20000)
    tools: list[str] = []
    skills: list[str] = Field(default_factory=list, max_length=10)
    skill_files: dict[str, str] = Field(default_factory=dict, max_length=10)
    composio_tools: list[ComposioTool] = []
    specialists: dict[str, "AgentProfile"] = Field(default_factory=dict, max_length=4)
    max_steps: int = Field(default=8, ge=1, le=20)
    max_output_tokens: int = Field(default=2000, ge=256, le=8000)
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    max_tool_calls: int = Field(default=32, ge=1, le=128)
    tool_call_limits: dict[str, int] = Field(default_factory=dict, max_length=32)
    max_parallel_tools: int = Field(default=4, ge=1, le=8)
    max_context_chars: int = Field(default=80000, ge=10000, le=200000)
    # Leave cleanup time before Celery's 840-second soft limit.
    max_duration_seconds: int = Field(default=600, ge=30, le=780)

    @model_validator(mode="after")
    def unique_tools(self) -> "AgentProfile":
        from command_center.agents.mcp_policy import catalog_tool_names
        from command_center.core.capabilities import CAPABILITIES

        if set(self.tools) - (set(CAPABILITIES) | catalog_tool_names() | {"ask_user"}):
            raise ValueError("Unknown tool grant")
        if any(
            name not in self.tools or not 1 <= limit <= 128
            for name, limit in self.tool_call_limits.items()
        ):
            raise ValueError("Tool limits need a granted tool and a positive bounded count")
        if self.composio_tools:
            raise ValueError(
                "Use typed connected account, context and proposal tools; "
                "raw Composio grants cannot bypass account selection and spending controls"
            )
        if len(self.instructions) + sum(map(len, self.skill_files.values())) > 20000:
            raise ValueError("Combined directive and skills exceed the context limit")
        if any(not re.fullmatch(r"[a-z0-9-]{1,80}", slug) for slug in self.skill_files):
            raise ValueError("Skill names must be plain slugs")
        if len({tool.slug for tool in self.composio_tools}) != len(self.composio_tools):
            raise ValueError("Composio tools must be unique")
        for role, specialist in self.specialists.items():
            if not re.fullmatch(r"[a-z0-9-]{1,80}", role) or specialist.specialists:
                raise ValueError("Specialists require a plain role and cannot delegate further")
            if set(specialist.tools) - set(self.tools):
                raise ValueError("Specialist tools must be a subset of the lead's tools")
            if any(tool not in self.composio_tools for tool in specialist.composio_tools):
                raise ValueError("Specialist Composio grants must be included in the lead's grants")
        return self


def load_profiles(
    path: str, skills_dir: str = "agents/skills"
) -> tuple[dict[str, AgentProfile], str]:
    content = Path(path).read_bytes()
    data = tomllib.loads(content.decode("utf-8"))
    revision = hashlib.sha256(content)
    profiles = {}
    delegated = {}
    for key, value in data["profiles"].items():
        delegated[key] = value.pop("delegates", [])
        directive = value.pop("directive", "")
        if "instructions" in value or not re.fullmatch(r"[a-z0-9-]{1,80}", directive):
            raise ValueError("Profiles require a directive slug, not inline instructions")
        directory = (Path(path).parent / "directives").resolve()
        directive_path = (directory / f"{directive}.md").resolve()
        if directive_path.parent != directory:
            raise ValueError("Directive must stay in the directives directory")
        instructions = directive_path.read_text()
        revision.update(directive.encode() + instructions.encode())
        profiles[key] = AgentProfile.model_validate({**value, "instructions": instructions})
    for profile in profiles.values():
        for slug in profile.skills:
            if not re.fullmatch(r"[a-z0-9-]{1,80}", slug):
                raise ValueError("Skill names must be plain slugs")
            skill = (Path(skills_dir) / f"{slug}.md").read_text()
            if len(skill) > 20000:
                raise ValueError("Skill exceeds the context limit")
            revision.update(slug.encode() + skill.encode())
            profile.skill_files[slug] = skill
    profiles = {
        key: AgentProfile.model_validate(value.model_dump()) for key, value in profiles.items()
    }
    for key, roles in delegated.items():
        if not isinstance(roles, list) or len(set(roles)) != len(roles):
            raise ValueError("Delegated roles must be unique")
        if any(role not in profiles or role == key or delegated[role] for role in roles):
            raise ValueError(
                "Delegation must name configured specialists without nested delegation"
            )
        profiles[key] = AgentProfile.model_validate(
            {**profiles[key].model_dump(), "specialists": {role: profiles[role] for role in roles}}
        )
    return profiles, revision.hexdigest()
