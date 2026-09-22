from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from command_center.db.artifacts import (
    Artifact,
    ArtifactReview,
    ArtifactVersion,
    Blob,
    Document,
    DocumentType,
)
from command_center.db.models import Actor, AuditEvent, Task


@pytest.fixture
def actor(session: Session) -> Actor:
    person = Actor(kind="human", display_name="Synthetic User")
    session.add(person)
    session.flush()
    return person


@pytest.fixture
def artifact(session: Session, actor: Actor) -> Artifact:
    record = Artifact(
        kind="research", title="Synthetic research", owner_id=actor.id, created_by_id=actor.id
    )
    session.add(record)
    session.flush()
    return record


def version_for(artifact: Artifact, actor: Actor, **overrides) -> ArtifactVersion:
    fields = dict(
        artifact_id=artifact.id,
        version=1,
        payload={"synthetic": True},
        schema_key="synthetic.v1",
        content_sha256="a" * 64,
        media_type="application/json",
        created_by_id=actor.id,
    )
    return ArtifactVersion(**(fields | overrides))


def test_task_completion_and_audit_share_a_transaction(session: Session, actor: Actor) -> None:
    task = Task(owner_id=actor.id, title="Review synthetic source")
    session.add(task)
    session.flush()
    task.complete(actor_id=actor.id, request_id=uuid4())
    session.flush()
    assert task.state == "done"
    assert task.completed_at is not None
    audit = session.scalars(select(AuditEvent).where(AuditEvent.subject_id == task.id)).one()
    assert audit.details == {"from_state": "open", "to_state": "done"}
    assert task.title not in str(audit.details)
    with pytest.raises(ValueError, match="active task"):
        task.complete(actor_id=actor.id, request_id=uuid4())
    task.reopen(actor_id=actor.id, request_id=uuid4())
    session.flush()
    assert task.completed_at is None
    assert (
        session.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.subject_id == task.id)
        )
        == 2
    )


def test_failed_audit_rolls_back_task_change(session: Session, actor: Actor) -> None:
    task = Task(owner_id=actor.id, title="Synthetic rollback")
    session.add(task)
    session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        task.complete(actor_id=uuid4(), request_id=uuid4())
        session.flush()
    session.refresh(task)
    assert task.state == "open"
    assert task.completed_at is None
    assert (
        session.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.subject_id == task.id)
        )
        == 0
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"state": "invented"},
        {"priority": 9},
        {"state": "done"},
        {"title": " "},
        {"due_date": date(2026, 9, 21), "due_at": datetime(2026, 9, 21, tzinfo=UTC)},
    ],
)
def test_task_constraints(session: Session, actor: Actor, fields: dict) -> None:
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(Task(**({"owner_id": actor.id, "title": "Synthetic task"} | fields)))
        session.flush()


def test_naive_instants_are_rejected(session: Session, actor: Actor) -> None:
    with pytest.raises(StatementError, match="timezone"), session.begin_nested():
        session.add(Task(owner_id=actor.id, title="Synthetic", due_at=datetime(2026, 9, 21)))
        session.flush()


def test_optimistic_version_rejects_stale_model(session: Session, actor: Actor) -> None:
    task = Task(owner_id=actor.id, title="Synthetic stale edit")
    session.add(task)
    session.flush()
    with pytest.raises(StaleDataError), session.begin_nested():
        session.execute(
            update(Task).where(Task.id == task.id).values(row_version=2),
            execution_options={"synchronize_session": False},
        )
        task.title = "Stale change"
        session.flush()


def test_document_facet_requires_document_artifact(session: Session, artifact: Artifact) -> None:
    document_type = DocumentType(slug="synthetic-test-resume", name="Resume")
    session.add(document_type)
    session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(Document(artifact_id=artifact.id, document_type_id=document_type.id))
        session.flush()


def test_document_artifact_requires_facet(session: Session, actor: Actor) -> None:
    with pytest.raises(IntegrityError, match="document facet"), session.begin_nested():
        session.add(
            Artifact(kind="document", title="Synthetic", owner_id=actor.id, created_by_id=actor.id)
        )
        session.flush()
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_document_and_facet_can_be_created_atomically(session: Session, actor: Actor) -> None:
    record = Artifact(kind="document", title="Synthetic", owner_id=actor.id, created_by_id=actor.id)
    document_type = DocumentType(slug="synthetic-test-resume", name="Resume")
    session.add_all([record, document_type])
    session.flush()
    session.add(Document(artifact_id=record.id, document_type_id=document_type.id))
    session.flush()
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.parametrize(
    "mutation",
    ["UPDATE artifact_versions SET media_type = 'text/plain'", "DELETE FROM artifact_versions"],
)
def test_artifact_versions_are_immutable(
    session: Session, artifact: Artifact, actor: Actor, mutation: str
) -> None:
    session.add(version_for(artifact, actor))
    session.flush()
    with pytest.raises(IntegrityError, match="append-only"), session.begin_nested():
        session.execute(text(mutation))


def test_version_numbers_are_unique(session: Session, artifact: Artifact, actor: Actor) -> None:
    session.add(version_for(artifact, actor))
    session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(version_for(artifact, actor))
        session.flush()


def test_content_source_and_blob_hash_constraints(
    session: Session, artifact: Artifact, actor: Actor
) -> None:
    blob = Blob(sha256="b" * 64, storage_key="sha256/" + "b" * 64, byte_size=10)
    session.add(blob)
    session.flush()
    # A structured payload and blob cannot both own the same version's content.
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(version_for(artifact, actor, blob_id=blob.id))
        session.flush()
    # A blob-backed version must name that blob's exact content digest.
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(version_for(artifact, actor, blob_id=blob.id, payload=None, schema_key=None))
        session.flush()


def test_audit_events_are_append_only(session: Session, actor: Actor) -> None:
    session.add(
        AuditEvent(
            actor_id=actor.id,
            action="synthetic",
            subject_type="task",
            subject_id=uuid4(),
            request_id=uuid4(),
        )
    )
    session.flush()
    with pytest.raises(IntegrityError, match="append-only"), session.begin_nested():
        session.execute(text("DELETE FROM audit_events"))


def test_payload_versions_compute_stable_hash_and_copy_content(actor: Actor) -> None:
    payload = {"b": [1], "a": "synthetic"}
    first = ArtifactVersion.from_payload(
        artifact_id=uuid4(),
        version=1,
        payload=payload,
        schema_key="synthetic.v1",
        created_by_id=actor.id,
    )
    second = ArtifactVersion.from_payload(
        artifact_id=uuid4(),
        version=2,
        payload={"a": "synthetic", "b": [1]},
        schema_key="synthetic.v1",
        created_by_id=actor.id,
    )
    assert first.content_sha256 == second.content_sha256
    payload["b"].append(2)
    assert first.payload == {"a": "synthetic", "b": [1]}


def test_blob_version_reuses_exact_digest(
    session: Session, artifact: Artifact, actor: Actor
) -> None:
    blob = Blob(sha256="b" * 64, storage_key="sha256/" + "b" * 64, byte_size=10)
    session.add(blob)
    session.flush()
    version = ArtifactVersion.from_blob(
        artifact_id=artifact.id,
        version=1,
        blob=blob,
        media_type="text/plain",
        created_by_id=actor.id,
    )
    session.add(version)
    session.flush()
    assert version.content_sha256 == blob.sha256
    assert version.payload is None


def test_approval_does_not_transfer_to_new_version(
    session: Session, artifact: Artifact, actor: Actor
) -> None:
    first = version_for(artifact, actor)
    second = version_for(artifact, actor, version=2)
    session.add_all([first, second])
    session.flush()
    session.add(
        ArtifactReview(
            artifact_version_id=first.id,
            reviewer_id=actor.id,
            decision="approved",
            reason="Synthetic review",
        )
    )
    session.flush()
    assert (
        session.scalar(
            select(func.count())
            .select_from(ArtifactReview)
            .where(ArtifactReview.artifact_version_id == second.id)
        )
        == 0
    )
