"""Domain coverage for exact research inputs, editable lineage and PDF derivatives."""

import hashlib
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from command_center.api.research_executions import enforce_task_scope
from command_center.db.agents import AgentRun
from command_center.db.artifacts import (
    Artifact,
    ArtifactDerivation,
    ArtifactVersion,
    Blob,
    Document,
    DocumentType,
)
from command_center.db.conversations import AgentSession
from command_center.db.errors import RecordNotFound
from command_center.db.evidence import SourceRecord
from command_center.db.models import Actor, Task
from command_center.db.pdf_exports import PdfExport
from command_center.db.research_executions import ResearchExecution


def owner(session, name="Synthetic owner"):
    value = Actor(id=uuid4(), kind="human", display_name=name)
    session.add(value)
    session.flush()
    return value


def text_artifact(session, actor, title="Synthetic source", kind="source"):
    artifact = Artifact.draft(
        session,
        record_id=uuid4(),
        owner_id=actor.id,
        title=title,
        kind=kind,
        sensitivity="public" if kind == "source" else "private",
        text="Synthetic evidence",
        document_type_id=None,
        request_id=uuid4(),
    )
    session.flush()
    version = session.scalar(
        select(ArtifactVersion).where(ArtifactVersion.artifact_id == artifact.id)
    )
    assert version is not None
    return artifact, version


def test_research_execution_pins_owned_inputs_and_validates_citations(session) -> None:
    actor = owner(session)
    stranger = owner(session, "Other owner")
    task = Task(owner_id=actor.id, title="Prepare synthetic interview brief")
    session.add(task)
    source_artifact, source_version = text_artifact(session, actor)
    _, foreign_version = text_artifact(session, stranger)
    session.add(
        SourceRecord(
            artifact_version_id=source_version.id,
            provider="synthetic",
            account_scope="public",
            locator="https://example.com/source",
            extraction_method="fixture",
        )
    )
    session.flush()

    with pytest.raises(RecordNotFound, match="unavailable"):
        ResearchExecution.create(
            session,
            record_id=uuid4(),
            owner_id=actor.id,
            task_id=task.id,
            script="print('{}')",
            input_version_ids=[foreign_version.id],
            output_title="Synthetic brief",
            document_type_slug="research",
            policy_snapshot={"image": "sha256:" + "a" * 64},
            request_id=uuid4(),
        )

    execution = ResearchExecution.create(
        session,
        record_id=uuid4(),
        owner_id=actor.id,
        task_id=task.id,
        script="print('{}')",
        input_version_ids=[source_version.id],
        output_title="Synthetic brief",
        document_type_slug="research",
        policy_snapshot={"image": "sha256:" + "a" * 64},
        request_id=uuid4(),
    )
    session.flush()
    claimed = ResearchExecution.claim(session, execution.id)
    assert claimed is execution and execution.lease_id is not None

    with pytest.raises(ValueError, match="selected public source"):
        execution.complete(
            execution.lease_id,
            text="Synthetic brief",
            citations=[{"source_version_id": str(uuid4()), "label": "Invented"}],
            request_id=uuid4(),
        )

    output = execution.complete(
        execution.lease_id,
        text="Synthetic brief",
        citations=[{"source_version_id": str(source_version.id), "label": "Synthetic evidence"}],
        request_id=uuid4(),
    )
    session.flush()
    assert output.payload["citations"][0]["source_version_id"] == str(source_version.id)
    inputs = set(
        session.scalars(
            select(ArtifactDerivation.input_version_id).where(
                ArtifactDerivation.output_version_id == output.id
            )
        )
    )
    assert inputs == {source_version.id, execution.script_version_id}
    assert source_artifact.owner_id == actor.id


def test_human_edit_retains_research_metadata_and_parent_lineage(session) -> None:
    actor = owner(session)
    document_type = session.scalar(select(DocumentType).where(DocumentType.slug == "research"))
    assert document_type is not None
    artifact = Artifact(
        owner_id=actor.id,
        created_by_id=actor.id,
        title="Synthetic research",
        kind="document",
        sensitivity="private",
    )
    session.add(artifact)
    session.flush()
    session.add(Document(artifact_id=artifact.id, document_type_id=document_type.id))
    base = artifact.append_payload(
        {"text": "Original", "citations": [{"source_version_id": str(uuid4()), "label": "A"}]},
        schema_key="research.document.v1",
        version_id=uuid4(),
        request_id=uuid4(),
    )
    session.flush()

    edited = artifact.revise_text(
        "Human edit", based_on_version_id=base.id, version_id=uuid4(), request_id=uuid4()
    )
    session.flush()

    assert edited.payload["text"] == "Human edit"
    assert edited.payload["citations"] == base.payload["citations"]
    assert session.get(ArtifactDerivation, (edited.id, base.id)).method == "human.edit"


def test_pdf_export_creates_separate_blob_artifact_from_selected_version(session) -> None:
    actor = owner(session)
    document_type = session.scalar(select(DocumentType).where(DocumentType.slug == "research"))
    assert document_type is not None
    artifact = Artifact.draft(
        session,
        record_id=uuid4(),
        owner_id=actor.id,
        title="Synthetic research",
        kind="document",
        sensitivity="private",
        text="Selected text",
        document_type_id=document_type.id,
        request_id=uuid4(),
    )
    session.flush()
    source = session.scalar(
        select(ArtifactVersion).where(ArtifactVersion.artifact_id == artifact.id)
    )
    assert source is not None
    export = PdfExport.create(
        session,
        record_id=uuid4(),
        owner_id=actor.id,
        artifact_id=artifact.id,
        version_id=source.id,
        renderer_revision="sha256:" + "a" * 64,
        task_id=None,
        request_id=uuid4(),
    )
    session.flush()
    PdfExport.claim(session, export.id)
    pdf = b"%PDF-1.7\nsynthetic"
    digest = hashlib.sha256(pdf).hexdigest()
    blob = Blob(sha256=digest, storage_key=f"sha256/{digest}", byte_size=len(pdf))
    session.add(blob)
    session.flush()

    assert export.lease_id is not None
    output = export.complete(export.lease_id, blob=blob, request_id=uuid4())
    session.flush()

    assert output.artifact_id != artifact.id
    assert output.media_type == "application/pdf"
    assert session.get(ArtifactDerivation, (output.id, source.id)).method == "pdf.weasyprint.v1"


def test_agent_research_is_limited_to_its_conversation_task(session) -> None:
    actor = owner(session)
    task = Task(owner_id=actor.id, title="Scoped synthetic research")
    other_task = Task(owner_id=actor.id, title="Unrelated synthetic research")
    session.add_all([task, other_task])
    session.flush()
    conversation = AgentSession(
        owner_id=actor.id,
        title=task.title,
        task_id=task.id,
        opportunity_id=None,
    )
    session.add(conversation)
    session.flush()
    run = AgentRun(
        owner_id=actor.id,
        title="Synthetic research run",
        prompt="Research synthetic evidence",
        profile="research",
        config_snapshot={},
        checkpoint={},
        state="running",
        session_id=conversation.id,
        input_sequence=0,
        consumed_sequence=0,
    )
    session.add(run)
    session.flush()

    enforce_task_scope(session, owner_id=actor.id, run_id=run.id, task_id=task.id)
    with pytest.raises(HTTPException) as denied:
        enforce_task_scope(session, owner_id=actor.id, run_id=run.id, task_id=other_task.id)
    assert denied.value.status_code == 403
