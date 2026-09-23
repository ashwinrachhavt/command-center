"""Contact-linked follow-ups are facets of immutable message artifacts, never sends."""

from html.parser import HTMLParser
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import ForeignKeyConstraint, Uuid, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from command_center.db.artifacts import Artifact, ArtifactDerivation, ArtifactVersion
from command_center.db.base import Base
from command_center.db.crm import Contact, record_event


class FollowUp(Base):
    __tablename__ = "follow_ups"
    __table_args__ = (
        ForeignKeyConstraint(["artifact_id", "owner_id"], ["artifacts.id", "artifacts.owner_id"]),
        ForeignKeyConstraint(["contact_id", "owner_id"], ["contacts.id", "contacts.owner_id"]),
    )
    artifact_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    contact_id: Mapped[UUID] = mapped_column(Uuid, index=True)

    @classmethod
    def checkpoint(
        cls,
        session: Session,
        *,
        owner_id: UUID,
        contact: Contact,
        artifact: Artifact | None,
        record_id: UUID,
        request_id: UUID,
        content: dict[str, Any],
        based_on_version_id: UUID | None = None,
        source_version_ids: list[UUID] | None = None,
    ) -> tuple[Artifact, ArtifactVersion]:
        if contact.owner_id != owner_id or contact.archived_at:
            raise ValueError("Choose an active contact in this workspace")
        if content["channel"] not in {"linkedin", "email"} or content["format"] not in {
            "text",
            "html",
        }:
            raise ValueError("Choose LinkedIn or email and supported writing content")
        if not plain_text(content["text"], content["format"]).strip():
            raise ValueError("Write a message before saving the follow-up")
        sources = list(source_version_ids or [])
        if len(sources) > 20 or len(set(sources)) != len(sources):
            raise ValueError("Choose at most twenty distinct source versions")
        if sources:
            found = set(
                session.scalars(
                    select(ArtifactVersion.id)
                    .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
                    .where(ArtifactVersion.id.in_(sources), Artifact.owner_id == owner_id)
                )
            )
            if found != set(sources):
                raise ValueError("Source versions must belong to this workspace")
        if artifact is None:
            artifact = Artifact(
                id=record_id,
                owner_id=owner_id,
                created_by_id=owner_id,
                kind="message",
                title=f"Follow-up · {contact.name}",
                sensitivity="private",
            )
            session.add(artifact)
            session.flush()
            session.add(cls(artifact_id=artifact.id, owner_id=owner_id, contact_id=contact.id))
        else:
            facet = session.get(cls, artifact.id)
            if not facet or facet.contact_id != contact.id or facet.owner_id != owner_id:
                raise ValueError("This follow-up belongs to a different contact")
            base = session.scalar(
                select(ArtifactVersion).where(
                    ArtifactVersion.id == based_on_version_id,
                    ArtifactVersion.artifact_id == artifact.id,
                )
            )
            if base is None:
                raise ValueError("Choose the saved version this edit started from")
            sources.append(base.id)
        payload = {**content, "contact_id": str(contact.id), "linkedin_url": contact.linkedin_url}
        version = artifact.append_payload(
            payload,
            schema_key="follow_up.v1",
            version_id=uuid5(record_id, "follow-up-version"),
            request_id=request_id,
        )
        session.flush()
        session.add_all(
            ArtifactDerivation(
                output_version_id=version.id, input_version_id=source, method="follow_up.checkpoint"
            )
            for source in set(sources)
        )
        record_event(
            session,
            owner_id,
            request_id,
            "follow_up.saved",
            "contacts",
            contact.id,
            artifact_id=str(artifact.id),
            version_id=str(version.id),
            channel=content["channel"],
        )
        return artifact, version


class _WritingText(HTMLParser):
    """Extract copyable text without rendering HTML or fetching any resource."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "iframe"}:
            self.hidden += 1
        if not self.hidden and tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "iframe"}:
            self.hidden = max(0, self.hidden - 1)
        if not self.hidden and tag in {"p", "div", "li", "blockquote", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def plain_text(text: str, format: str) -> str:
    if format == "text":
        return text
    parser = _WritingText()
    parser.feed(text)
    parser.close()
    return "".join(parser.parts).rstrip("\n")
