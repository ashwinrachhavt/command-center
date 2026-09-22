"""One version lifecycle for documents, research, messages, sources and packages."""

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column, object_session

from command_center.db.base import Base, UTCDateTime, utc_now


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('document', 'message', 'research', 'package', 'source')", name="kind"
        ),
        CheckConstraint("sensitivity IN ('public', 'private', 'restricted')", name="sensitivity"),
        CheckConstraint("row_version >= 1", name="row_version"),
        UniqueConstraint("id", "kind"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(300))
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"))
    sensitivity: Mapped[str] = mapped_column(String(20), default="private")
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, onupdate=utc_now)

    __mapper_args__ = {"version_id_col": row_version}

    @classmethod
    def draft(
        cls,
        session: Session,
        *,
        record_id: UUID,
        owner_id: UUID,
        title: str,
        kind: str,
        sensitivity: str,
        text: str,
        document_type_id: UUID | None,
        request_id: UUID,
    ) -> "Artifact":
        if (kind == "document") != (document_type_id is not None):
            raise ValueError("Choose a document type for document artifacts only")
        if document_type_id and session.get(DocumentType, document_type_id) is None:
            raise ValueError("Unknown document type")
        artifact = cls(
            id=record_id,
            owner_id=owner_id,
            created_by_id=owner_id,
            title=title,
            kind=kind,
            sensitivity=sensitivity,
        )
        session.add(artifact)
        session.flush()
        if document_type_id:
            session.add(Document(artifact_id=record_id, document_type_id=document_type_id))
        artifact.append_text(text, version_id=uuid5(record_id, "version:1"), request_id=request_id)
        return artifact

    def revise(self, changes: dict[str, Any], *, request_id: UUID) -> None:
        from command_center.db.crm import record_event

        if self.archived_at or set(changes) - {"title", "sensitivity"}:
            raise ValueError("Only active artifact metadata can be changed")
        if any(value is None for value in changes.values()):
            raise ValueError("Artifact metadata cannot be empty")
        for name, value in changes.items():
            setattr(self, name, value)
        session = object_session(self)
        if session:
            record_event(
                session, self.owner_id, request_id, "artifact.updated", "artifacts", self.id
            )

    def archive(self, *, request_id: UUID) -> None:
        from command_center.db.crm import record_event

        if self.archived_at:
            return
        self.archived_at = utc_now()
        session = object_session(self)
        if session:
            record_event(
                session, self.owner_id, request_id, "artifact.archived", "artifacts", self.id
            )

    def append_text(self, text: str, *, version_id: UUID, request_id: UUID) -> "ArtifactVersion":
        from sqlalchemy import func, select

        from command_center.db.crm import record_event

        session = object_session(self)
        if session is None or self.archived_at:
            raise ValueError("Only an active persisted artifact can receive a version")
        latest = (
            session.scalar(
                select(func.max(ArtifactVersion.version)).where(
                    ArtifactVersion.artifact_id == self.id
                )
            )
            or 0
        )
        version = ArtifactVersion.from_payload(
            artifact_id=self.id,
            version=latest + 1,
            payload={"text": text},
            schema_key="text.v1",
            created_by_id=self.owner_id,
        )
        version.id = version_id
        session.add(version)
        self.updated_at = utc_now()
        record_event(
            session,
            self.owner_id,
            request_id,
            "artifact.version_created",
            "artifacts",
            self.id,
            version=latest + 1,
        )
        return version

    def append_blob(
        self,
        blob: "Blob",
        *,
        media_type: str,
        version_id: UUID,
        request_id: UUID,
    ) -> "ArtifactVersion":
        """Append an exact stored byte snapshot to an active artifact."""
        from sqlalchemy import func, select

        from command_center.db.crm import record_event

        session = object_session(self)
        if session is None or self.archived_at:
            raise ValueError("Only an active persisted artifact can receive a version")
        if not media_type.strip() or blob.id is None or object_session(blob) is not session:
            raise ValueError("Blob metadata and media type must be persisted together")
        latest = (
            session.scalar(
                select(func.max(ArtifactVersion.version)).where(
                    ArtifactVersion.artifact_id == self.id
                )
            )
            or 0
        )
        version = ArtifactVersion.from_blob(
            artifact_id=self.id,
            version=latest + 1,
            blob=blob,
            media_type=media_type,
            created_by_id=self.owner_id,
        )
        version.id = version_id
        session.add(version)
        self.updated_at = utc_now()
        record_event(
            session,
            self.owner_id,
            request_id,
            "artifact.version_created",
            "artifacts",
            self.id,
            version=latest + 1,
            content="blob",
        )
        return version

    def append_payload(
        self,
        payload: dict[str, object],
        *,
        schema_key: str,
        version_id: UUID,
        request_id: UUID,
    ) -> "ArtifactVersion":
        """Append validated structured content through the shared version lifecycle."""
        from sqlalchemy import func, select

        from command_center.db.crm import record_event

        session = object_session(self)
        if session is None or self.archived_at:
            raise ValueError("Only an active persisted artifact can receive a version")
        latest = (
            session.scalar(
                select(func.max(ArtifactVersion.version)).where(
                    ArtifactVersion.artifact_id == self.id
                )
            )
            or 0
        )
        version = ArtifactVersion.from_payload(
            artifact_id=self.id,
            version=latest + 1,
            payload=payload,
            schema_key=schema_key,
            created_by_id=self.owner_id,
        )
        version.id = version_id
        session.add(version)
        self.updated_at = utc_now()
        record_event(
            session,
            self.owner_id,
            request_id,
            "artifact.version_created",
            "artifacts",
            self.id,
            version=latest + 1,
            content="structured",
            schema_key=schema_key,
        )
        return version


class Blob(Base):
    """Immutable byte metadata. Bytes live outside PostgreSQL; no arbitrary filesystem paths."""

    __tablename__ = "blobs"
    __table_args__ = (
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256"),
        CheckConstraint("storage_key = 'sha256/' || sha256", name="storage_key"),
        CheckConstraint("byte_size >= 0", name="byte_size"),
        UniqueConstraint("id", "sha256"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    storage_key: Mapped[str] = mapped_column(String(71), unique=True)
    byte_size: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)


class ArtifactVersion(Base):
    __tablename__ = "artifact_versions"
    __table_args__ = (
        UniqueConstraint("artifact_id", "version"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256"),
        CheckConstraint("(blob_id IS NULL) <> (payload IS NULL)", name="one_content_source"),
        CheckConstraint(
            "(payload IS NULL AND schema_key IS NULL) OR "
            "(payload IS NOT NULL AND schema_key IS NOT NULL AND jsonb_typeof(payload) = 'object')",
            name="structured_schema",
        ),
        ForeignKeyConstraint(["blob_id", "content_sha256"], ["blobs.id", "blobs.sha256"]),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    blob_id: Mapped[UUID | None] = mapped_column(Uuid)
    payload: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    schema_key: Mapped[str | None] = mapped_column(String(100))
    content_sha256: Mapped[str] = mapped_column(String(64))
    media_type: Mapped[str] = mapped_column(String(200))
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    def review(
        self,
        *,
        review_id: UUID,
        reviewer_id: UUID,
        decision: str,
        reason: str,
        request_id: UUID,
    ) -> "ArtifactReview":
        from command_center.db.crm import record_event

        if decision not in {"approved", "rejected", "revoked"} or not reason.strip():
            raise ValueError("A review needs a decision and reason")
        session = object_session(self)
        if session is None:
            raise ValueError("Review a persisted version")
        review = ArtifactReview(
            id=review_id,
            artifact_version_id=self.id,
            reviewer_id=reviewer_id,
            decision=decision,
            reason=reason,
        )
        session.add(review)
        record_event(
            session,
            reviewer_id,
            request_id,
            "artifact.reviewed",
            "artifacts",
            self.artifact_id,
            version=self.version,
            decision=decision,
        )
        return review

    @classmethod
    def from_payload(
        cls,
        *,
        artifact_id: UUID,
        version: int,
        payload: dict[str, object],
        schema_key: str,
        created_by_id: UUID,
    ) -> "ArtifactVersion":
        """Hash a canonical JSON snapshot. The caller supplies schema-validated data."""
        if not schema_key.strip():
            raise ValueError("Structured content requires a versioned schema key")
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
        return cls(
            artifact_id=artifact_id,
            version=version,
            payload=json.loads(canonical),
            schema_key=schema_key,
            content_sha256=hashlib.sha256(canonical).hexdigest(),
            media_type="application/json",
            created_by_id=created_by_id,
        )

    @classmethod
    def from_blob(
        cls,
        *,
        artifact_id: UUID,
        version: int,
        blob: Blob,
        media_type: str,
        created_by_id: UUID,
    ) -> "ArtifactVersion":
        if blob.id is None:
            raise ValueError("Persist blob metadata before referencing it")
        return cls(
            artifact_id=artifact_id,
            version=version,
            blob_id=blob.id,
            content_sha256=blob.sha256,
            media_type=media_type,
            created_by_id=created_by_id,
        )


class DocumentType(Base):
    __tablename__ = "document_types"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)


class Document(Base):
    """A facet of a document artifact, never a second content/version store."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("artifact_kind = 'document'", name="document_kind"),
        ForeignKeyConstraint(["artifact_id", "artifact_kind"], ["artifacts.id", "artifacts.kind"]),
    )

    artifact_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    artifact_kind: Mapped[str] = mapped_column(String(20), default="document")
    document_type_id: Mapped[UUID] = mapped_column(ForeignKey("document_types.id"), index=True)


class ArtifactReview(Base):
    """Review history is append-only. A new version has no inherited review."""

    __tablename__ = "artifact_reviews"
    __table_args__ = (
        CheckConstraint("decision IN ('approved', 'rejected', 'revoked')", name="decision"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    artifact_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("artifact_versions.id"), index=True
    )
    reviewer_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"))
    decision: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)


class ArtifactDerivation(Base):
    __tablename__ = "artifact_derivations"
    __table_args__ = (CheckConstraint("output_version_id <> input_version_id", name="not_self"),)

    output_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("artifact_versions.id"), primary_key=True
    )
    input_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("artifact_versions.id"), primary_key=True
    )
    method: Mapped[str] = mapped_column(String(100))


class TaskArtifact(Base):
    __tablename__ = "task_artifacts"

    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    artifact_id: Mapped[UUID] = mapped_column(
        ForeignKey("artifacts.id"), primary_key=True, index=True
    )
