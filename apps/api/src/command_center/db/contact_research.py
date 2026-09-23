"""Evidence attached to a contact draft, without overwriting the address book."""

import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from command_center.db.artifacts import Artifact, ArtifactVersion, TaskArtifact
from command_center.db.evidence import SourceRecord


class ContactCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_version_id: UUID
    quote: str = Field(min_length=10, max_length=1500)


class ContactResearch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity: Literal["matched", "uncertain"]
    company: str = Field(default="", max_length=250)
    role: str = Field(default="", max_length=250)
    summary: str = Field(min_length=1, max_length=2000)
    caveats: str = Field(default="", max_length=1500)
    identity_evidence: list[ContactCitation] = Field(default_factory=list, max_length=5)
    employment_evidence: list[ContactCitation] = Field(default_factory=list, max_length=5)

    def validate_sources(
        self, db: Session, *, owner_id: UUID, task_id: UUID, source_version_ids: list[UUID]
    ) -> None:
        if self.identity == "matched" and not self.identity_evidence:
            raise ValueError("A matched identity needs captured evidence")
        if (self.company.strip() or self.role.strip()) and (
            self.identity != "matched" or not self.employment_evidence
        ):
            raise ValueError("A current company or role needs identity and employment evidence")
        if self.identity == "uncertain" and not self.caveats.strip():
            raise ValueError("Explain what prevents an identity match")
        citations = [*self.identity_evidence, *self.employment_evidence]
        ids = {citation.source_version_id for citation in citations}
        if not ids.issubset(source_version_ids):
            raise ValueError("Include each research citation in the draft's source versions")
        rows = db.execute(
            select(ArtifactVersion.id, ArtifactVersion.payload)
            .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
            .join(SourceRecord, SourceRecord.artifact_version_id == ArtifactVersion.id)
            .join(TaskArtifact, TaskArtifact.artifact_id == Artifact.id)
            .where(
                ArtifactVersion.id.in_(ids),
                Artifact.owner_id == owner_id,
                Artifact.kind == "source",
                Artifact.sensitivity == "public",
                Artifact.archived_at.is_(None),
                TaskArtifact.task_id == task_id,
            )
        )
        passages = {row.id: re.sub(r"\s+", " ", str(row.payload.get("text", ""))) for row in rows}
        for citation in citations:
            quote = re.sub(r"\s+", " ", citation.quote).strip()
            if len(quote) < 10 or quote not in passages.get(citation.source_version_id, ""):
                raise ValueError(
                    "Research quotes must occur in public sources captured for this task"
                )
