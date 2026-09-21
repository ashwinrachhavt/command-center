import hashlib
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    model: str
    instructions: str = Field(max_length=20000)
    tools: list[
        Literal[
            "workspace_summary",
            "research_search",
            "create_task",
            "draft_artifact",
            "memory_read",
            "memory_append",
        ]
    ] = []
    skills: list[str] = Field(default_factory=list, max_length=10)
    composio_tools: list[ComposioTool] = []
    max_steps: int = Field(default=8, ge=1, le=20)
    max_output_tokens: int = Field(default=2000, ge=256, le=8000)

    @model_validator(mode="after")
    def unique_tools(self) -> "AgentProfile":
        if len({tool.slug for tool in self.composio_tools}) != len(self.composio_tools):
            raise ValueError("Composio tools must be unique")
        return self


def load_profiles(
    path: str, skills_dir: str = "agents/skills"
) -> tuple[dict[str, AgentProfile], str]:
    content = Path(path).read_bytes()
    data = tomllib.loads(content.decode("utf-8"))
    profiles = {key: AgentProfile.model_validate(value) for key, value in data["profiles"].items()}
    revision = hashlib.sha256(content)
    for profile in profiles.values():
        for slug in profile.skills:
            import re

            if not re.fullmatch(r"[a-z0-9-]{1,80}", slug):
                raise ValueError("Skill names must be plain slugs")
            skill = (Path(skills_dir) / f"{slug}.md").read_text()
            if len(skill) > 20000:
                raise ValueError("Skill exceeds the context limit")
            revision.update(slug.encode() + skill.encode())
            profile.instructions += f"\n\nSkill: {slug}\n{skill}"
    return profiles, revision.hexdigest()
