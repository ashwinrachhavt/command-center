"""Document requests pin source/fact versions and never complete or submit applications."""

import hashlib
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_application_context import job_description
from test_application_preparations import client as client
from test_application_preparations import (
    fact,
    post,
    prepare,
    review_fact,
    shared_page,
    upload_resume,
)

from command_center.core.capabilities import issue_run_token
from command_center.core.identity import Identity, authenticate
from command_center.db.agents import AgentRun
from command_center.db.application_materials import ApplicationMaterial
from command_center.db.applications import ApplicationTrack
from command_center.db.artifacts import (
    Artifact,
    ArtifactDerivation,
    ArtifactVersion,
    Blob,
    Document,
    DocumentType,
    TaskArtifact,
)
from command_center.db.base import utc_now
from command_center.db.browser import application_file, application_file_options
from command_center.db.document_imports import DocumentImport
from command_center.db.errors import RecordConflict
from command_center.db.models import Actor, Task
from command_center.db.pdf_exports import PdfExport
from command_center.db.profile_facts import ProfileFact


@pytest.mark.parametrize("kind", ["resume", "cover-letter"])
def test_only_owned_typed_originals_and_completed_pdf_exports_are_attachable(session, kind):
    actor = Actor(id=uuid4(), kind="human", display_name="Synthetic document owner")
    session.add(actor)
    session.flush()
    doc_type = session.scalar(select(DocumentType).where(DocumentType.slug == kind))
    document = Artifact.draft(
        session,
        record_id=uuid4(),
        owner_id=actor.id,
        title="Synthetic application document",
        kind="document",
        sensitivity="private",
        text="Selected synthetic document content",
        document_type_id=doc_type.id,
        request_id=uuid4(),
    )
    session.flush()
    source = session.scalar(
        select(ArtifactVersion).where(ArtifactVersion.artifact_id == document.id)
    )
    export = PdfExport.create(
        session,
        record_id=uuid4(),
        owner_id=actor.id,
        artifact_id=document.id,
        version_id=source.id,
        renderer_revision="sha256:" + "a" * 64,
        task_id=None,
        request_id=uuid4(),
    )
    session.flush()
    PdfExport.claim(session, export.id)
    data = b"%PDF-1.7\nsynthetic application material fixture"
    digest = hashlib.sha256(data).hexdigest()
    blob = Blob(sha256=digest, storage_key=f"sha256/{digest}", byte_size=len(data))
    session.add(blob)
    session.flush()
    output = export.complete(export.lease_id, blob=blob, request_id=uuid4())
    session.flush()
    metadata = application_file(session, actor.id, output.id, kind=kind)
    assert metadata["sha256"] == digest and metadata["media_type"] == "application/pdf"
    assert metadata["filename"].endswith(".pdf")
    assert (
        application_file_options(session, actor.id, kind=kind)["items"][0]["version_id"]
        == output.id
    )
    with pytest.raises(RecordConflict):
        application_file(session, uuid4(), output.id, kind=kind)
    with pytest.raises(RecordConflict):
        application_file(
            session,
            actor.id,
            output.id,
            kind="resume" if kind == "cover-letter" else "cover-letter",
        )
    # A typed blob alone is insufficient: it must be an import or completed export.
    arbitrary = document.append_blob(
        blob, media_type="application/pdf", version_id=uuid4(), request_id=uuid4()
    )
    session.flush()
    with pytest.raises(RecordConflict):
        application_file(session, actor.id, arbitrary.id, kind=kind)
    session.get(Artifact, output.artifact_id).archived_at = utc_now()
    session.flush()
    assert application_file_options(session, actor.id, kind=kind)["items"] == []


def material_inputs(client, engine, *, extract=True, approve=True):
    snapshot, _ = shared_page(client)
    preparation = prepare(client, snapshot, job_context=job_description())
    context = client.get(f"/api/v1/applications/{preparation['task_id']}/job-context").json()
    resume_id = upload_resume(client, b"Synthetic Applicant. Built accessible tools.")
    if extract:
        with Session(engine) as db, db.begin():
            imported = db.scalar(
                select(DocumentImport).where(DocumentImport.source_version_id == UUID(resume_id))
            )
            job = DocumentImport.claim(db, imported.id)
            source = Artifact(
                id=uuid4(),
                owner_id=client.actor_id,
                created_by_id=client.actor_id,
                title="Synthetic extracted resume",
                kind="source",
                sensitivity="private",
            )
            db.add(source)
            db.flush()
            version = source.append_text(
                "Synthetic Applicant. Built accessible tools.",
                version_id=uuid4(),
                request_id=uuid4(),
            )
            db.flush()
            job.complete(
                job.lease_id,
                extraction_artifact_id=source.id,
                extraction_version_id=version.id,
                request_id=uuid4(),
            )
    personal = fact(client, "experience", "Built accessible tools.")
    if approve:
        personal = review_fact(client, personal)
    return (
        preparation,
        {
            "kind": "cover-letter",
            "job_version_id": context["version_id"],
            "resume_version_id": resume_id,
        },
        personal,
    )


def claim(client, engine, material):
    with Session(engine) as db, db.begin():
        run = AgentRun.claim(db, UUID(material["run_id"]))
        assert run is not None
        token = issue_run_token(client.app.state.settings, run.id, run.lease_id)
    client.app.dependency_overrides.pop(authenticate)
    return {"Authorization": "Bearer " + token}


def human(client):
    client.app.dependency_overrides[authenticate] = client.human_identity


def test_material_worker_reads_real_sources_and_saves_through_scoped_mcp(
    client, engine, agent_server, scripted_model, mocker
):
    from langchain_core.messages import AIMessage

    from command_center.agents.worker import perform_next
    from command_center.db.spending import SpendingPolicy, SpendingRateCard

    preparation, body, personal = material_inputs(client, engine)
    with Session(engine) as db, db.begin():
        card = SpendingRateCard.create(
            db,
            owner_id=client.actor_id,
            name="Synthetic material rates",
            source_label="Synthetic fixture",
            request_id=uuid4(),
            rates={
                "models": [
                    {
                        "provider": "openai",
                        "model": "gpt-5-mini",
                        "input_per_million_micros": 0,
                        "output_per_million_micros": 0,
                        "fixed_micros": 1,
                    }
                ],
                "tools": [],
            },
        )
        policy = db.get(SpendingPolicy, client.actor_id)
        SpendingPolicy.configure(
            db,
            owner_id=client.actor_id,
            rate_card_id=card.id,
            monthly_limit_micros=1_000_000,
            default_work_limit_micros=1_000_000,
            active=True,
            request_id=uuid4(),
            expected_version=policy.row_version if policy else None,
        )
    response = post(client, f"applications/{preparation['task_id']}/materials", body)
    assert response.status_code == 202, response.text
    material = response.json()
    with Session(engine) as db:
        resume_text = db.get(ApplicationMaterial, UUID(material["id"])).resume_text_version_id

    def tool(name, args, call_id):
        return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])

    model = scripted_model(
        [
            tool(
                "application_material_context", {"material_id": material["id"]}, "material-context"
            ),
            tool("document_read", {"version_id": body["job_version_id"]}, "job-source"),
            tool("document_read", {"version_id": str(resume_text)}, "resume-source"),
            tool(
                "save_application_material",
                {
                    "material_id": material["id"],
                    "text": "Dear team, I built accessible tools.",
                    "fact_revision_ids": [personal["active"]["id"]],
                },
                "material-output",
            ),
            AIMessage(content="Your editable cover letter is saved."),
        ]
    )
    mocker.patch("command_center.agents.worker.create_chat_model", return_value=model)
    assert perform_next(engine, agent_server, UUID(material["run_id"]))
    with Session(engine) as db:
        run = db.get(AgentRun, UUID(material["run_id"]))
        assert run.state == "completed", run.error_code
        assert len(run.tool_steps()) == 4
        assert all(step["state"] == "output-available" for step in run.tool_steps())
        saved = db.get(ApplicationMaterial, UUID(material["id"]))
        assert saved.output_version_id is not None
        assert db.get(Task, saved.task_id).state == "open"


@pytest.mark.parametrize("kind", ["resume", "cover-letter"])
def test_material_request_retries_pins_sources_and_saves_one_editable_document(
    client, engine, kind
):
    preparation, body, personal = material_inputs(client, engine)
    body["kind"] = kind
    route = f"applications/{preparation['task_id']}/materials"
    key = uuid4()
    created = post(client, route, body, key=key)
    assert created.status_code == 202, created.text
    material = created.json()
    assert post(client, route, body, key=key).json() == material
    assert post(client, route, body).status_code == 409
    # New checkpoints cannot alter an existing generation request's source.
    context = client.get(f"/api/v1/applications/{preparation['task_id']}/job-context").json()
    checkpoint = post(
        client,
        f"artifacts/{context['artifact_id']}/versions",
        {
            "based_on_version_id": context["version_id"],
            "expected_version": context["expected_version"],
            "text": "Changed requirements for future requests.",
        },
    )
    assert checkpoint.status_code == 201
    headers = claim(client, engine, material)
    data = client.get(f"/api/v1/application-materials/{material['id']}/context", headers=headers)
    assert data.status_code == 200, data.text
    source = data.json()["sources"][0]
    assert source["version_id"] == body["job_version_id"]
    assert data.json()["facts"][0]["revision_id"] == personal["active"]["id"]
    output = {
        "text": "# Synthetic Applicant\n\nI built accessible tools.",
        "fact_revision_ids": [personal["active"]["id"]],
    }
    output_route = f"application-materials/{material['id']}/output"
    output_key = uuid4()
    saved = post(client, output_route, output, key=output_key, headers=headers)
    assert saved.status_code == 200, saved.text
    assert (
        post(client, output_route, output, key=output_key, headers=headers).json() == saved.json()
    )
    assert post(client, output_route, output, headers=headers).status_code == 409
    with Session(engine) as db:
        record = db.get(ApplicationMaterial, UUID(material["id"]))
        assert db.get(Task, record.task_id).state == "open"
        assert db.get(ApplicationTrack, record.task_id).status == "preparing"
        assert db.get(TaskArtifact, (record.task_id, record.output_artifact_id))
        document = db.get(Document, record.output_artifact_id)
        assert db.get(DocumentType, document.document_type_id).slug == kind
        sources = set(
            db.scalars(
                select(ArtifactDerivation.input_version_id).where(
                    ArtifactDerivation.output_version_id == record.output_version_id
                )
            )
        )
        assert sources == {
            record.job_version_id,
            record.resume_version_id,
            record.resume_text_version_id,
        }
        assert db.get(ArtifactVersion, record.output_version_id).payload["text"] == output["text"]
        assert record.used_fact_revision_ids == output["fact_revision_ids"]
        assert (
            db.scalar(
                select(func.count())
                .select_from(ApplicationMaterial)
                .where(ApplicationMaterial.task_id == record.task_id)
            )
            == 1
        )
    human(client)
    assert client.get(f"/api/v1/{route}").json()["items"][0]["output"] == saved.json()["output"]


def test_material_rejects_unready_sources_and_stale_description(client, engine):
    preparation, body, _ = material_inputs(client, engine, extract=False)
    route = f"applications/{preparation['task_id']}/materials"
    assert post(client, route, body).status_code == 409
    preparation, body, _ = material_inputs(client, engine, approve=False)
    # The previous setup's fact is active; revoke it so this actor has no approved profile.
    with Session(engine) as db, db.begin():
        for item in db.scalars(select(ProfileFact).where(ProfileFact.owner_id == client.actor_id)):
            item.active_revision_id = None
    route = f"applications/{preparation['task_id']}/materials"
    assert "approve" in post(client, route, body).json()["detail"]
    assert post(client, route, {**body, "job_version_id": str(uuid4())}).status_code == 409


def test_material_is_owned_run_scoped_and_rechecks_fact_approval(client, engine):
    preparation, body, personal = material_inputs(client, engine)
    route = f"applications/{preparation['task_id']}/materials"
    material = post(client, route, body).json()
    output_route = f"application-materials/{material['id']}/output"
    output = {"text": "Supported synthetic draft", "fact_revision_ids": [personal["active"]["id"]]}
    assert post(client, output_route, output).status_code == 403
    other_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=other_id, kind="human", display_name="Synthetic unrelated owner"))
    client.app.dependency_overrides[authenticate] = lambda: Identity(other_id, "synthetic")
    assert client.get(f"/api/v1/{route}").status_code == 404
    assert client.get(f"/api/v1/application-materials/{material['id']}/context").status_code == 404
    client.app.dependency_overrides[authenticate] = lambda: Identity(
        client.actor_id, "synthetic", run_id=uuid4()
    )
    assert client.get(f"/api/v1/application-materials/{material['id']}/context").status_code == 403
    human(client)
    headers = claim(client, engine, material)
    assert post(client, route, body, headers=headers).status_code == 403
    assert (
        post(
            client, output_route, {**output, "fact_revision_ids": [str(uuid4())]}, headers=headers
        ).status_code
        == 422
    )
    with Session(engine) as db, db.begin():
        db.get(ProfileFact, UUID(personal["id"])).active_revision_id = None
    assert post(client, output_route, output, headers=headers).status_code == 409
    context = client.get(
        f"/api/v1/application-materials/{material['id']}/context", headers=headers
    ).json()
    assert context["facts"] == [] and context["unavailable_fact_count"] == 1
    with Session(engine) as db, db.begin():
        db.get(AgentRun, UUID(material["run_id"])).finish("cancelled")
    assert post(client, output_route, output, headers=headers).status_code == 401
