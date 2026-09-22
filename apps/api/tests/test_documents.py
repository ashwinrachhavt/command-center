"""Document ingestion keeps original bytes and conversion state durable."""

import asyncio
import io
import struct
import threading
import zipfile
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

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
from command_center.db.crm import CandidateProfile
from command_center.db.document_imports import DocumentImport
from command_center.db.models import Actor, Task


@pytest.fixture
def client(settings, engine, tmp_path, mocker):
    from command_center.api import documents as document_api
    from command_center.core.identity import Identity, authenticate
    from command_center.main import create_app

    configured = settings.model_copy(
        update={
            "blob_store_path": tmp_path / "blobs",
            "docling_url": "http://127.0.0.1:5001",
        }
    )
    owner_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=owner_id, kind="human", display_name="Synthetic document owner"))
    app = create_app(configured)
    app.state.document_test_settings = configured
    app.dependency_overrides[authenticate] = lambda: Identity(owner_id, "synthetic")
    dispatch = mocker.patch.object(document_api, "dispatch_import")
    with TestClient(app) as http:
        http.actor_id = owner_id
        http.document_dispatch = dispatch
        yield http


def upload(client, *, key=None, content=b"Synthetic resume text", **data):
    filename = data.pop("filename", "resume.txt")
    upload_media_type = data.pop("upload_media_type", "text/plain")
    document_type_id = data.pop("document_type_id", None)
    if document_type_id is None:
        document_type_id = client.get("/api/v1/document-types").json()[0]["id"]
        for item in client.get("/api/v1/document-types").json():
            if item["slug"] == "resume":
                document_type_id = item["id"]
                break
    return client.post(
        "/api/v1/documents/imports",
        data={
            "title": "Synthetic resume",
            "document_type_id": document_type_id,
            **data,
        },
        files={"file": (filename, content, upload_media_type)},
        headers={"Idempotency-Key": str(key or uuid4())},
    )


def actor(session, name: str = "Synthetic owner") -> Actor:
    row = Actor(id=uuid4(), kind="human", display_name=name)
    session.add(row)
    session.flush()
    return row


def resume_type(session) -> DocumentType:
    row = session.scalar(select(DocumentType).where(DocumentType.slug == "resume"))
    assert row is not None
    return row


def blob(session, content: bytes = b"synthetic resume") -> Blob:
    import hashlib

    digest = hashlib.sha256(content).hexdigest()
    row = Blob(sha256=digest, storage_key=f"sha256/{digest}", byte_size=len(content))
    session.add(row)
    session.flush()
    return row


def document(
    session, owner: Actor, *, title: str = "Synthetic resume"
) -> tuple[Artifact, ArtifactVersion]:
    source = blob(session, f"synthetic resume {owner.id}".encode())
    artifact = Artifact(
        id=uuid4(),
        owner_id=owner.id,
        created_by_id=owner.id,
        title=title,
        kind="document",
        sensitivity="private",
    )
    session.add(artifact)
    session.flush()
    session.add(Document(artifact_id=artifact.id, document_type_id=resume_type(session).id))
    version = artifact.append_blob(
        source,
        media_type="text/plain",
        version_id=uuid4(),
        request_id=uuid4(),
    )
    session.flush()
    return artifact, version


def test_blob_versions_append_immutable_originals(session) -> None:
    owner = actor(session)
    artifact, first = document(session, owner)
    second_blob = blob(session, b"new synthetic resume")

    second = artifact.append_blob(
        second_blob,
        media_type="text/plain",
        version_id=uuid4(),
        request_id=uuid4(),
    )
    session.flush()

    assert first.version == 1
    assert first.payload is None
    assert second.version == 2
    assert second.blob_id == second_blob.id
    assert first.blob_id != second.blob_id


def test_docx_rejects_oversized_declared_archive_expansion() -> None:
    from fastapi import HTTPException

    from command_center.api.documents import inspect_document

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<document />")
    content = bytearray(buffer.getvalue())
    cursor = 0
    while True:
        cursor = content.find(b"PK\x01\x02", cursor)
        if cursor < 0:
            break
        filename_length = struct.unpack_from("<H", content, cursor + 28)[0]
        filename = bytes(content[cursor + 46 : cursor + 46 + filename_length])
        if filename == b"word/document.xml":
            struct.pack_into("<I", content, cursor + 24, 101 * 1024 * 1024)
            break
        cursor += 46 + filename_length

    with pytest.raises(HTTPException, match="archive expands beyond"):
        inspect_document("synthetic.docx", bytes(content))


def test_conversion_lease_fences_cancelled_and_stale_workers(session) -> None:
    owner = actor(session)
    artifact, version = document(session, owner)
    task = Task(owner_id=owner.id, title="Review synthetic extraction")
    session.add(task)
    session.flush()
    job = DocumentImport.queued(
        session,
        import_id=uuid4(),
        owner_id=owner.id,
        artifact_id=artifact.id,
        source_version_id=version.id,
        task_id=task.id,
        filename="resume.txt",
        media_type="text/plain",
        byte_size=version.blob_id and session.get(Blob, version.blob_id).byte_size,
        request_id=uuid4(),
    )
    session.flush()

    claimed = DocumentImport.claim(session, job.id)
    assert claimed is not None and claimed.state == "running" and claimed.lease_id is not None
    old_lease = claimed.lease_id
    claimed.cancel(request_id=uuid4())
    session.flush()
    assert not claimed.accepts(old_lease)

    claimed.retry(request_id=uuid4())
    session.flush()
    reclaimed = DocumentImport.claim(session, job.id)
    assert reclaimed is not None and reclaimed.lease_id != old_lease
    reclaimed.lease_expires_at = utc_now() - timedelta(seconds=1)
    session.flush()
    assert DocumentImport.expire_stale(session) == 1
    assert reclaimed.state == "failed"
    assert not reclaimed.accepts(reclaimed.lease_id)


def test_default_resume_requires_owned_active_blob_backed_resume(session) -> None:
    owner = actor(session)
    stranger = actor(session, "Other synthetic owner")
    artifact, version = document(session, owner)
    other_artifact, other_version = document(session, stranger)
    profile = CandidateProfile(actor_id=owner.id)
    session.add(profile)
    session.flush()

    profile.select_default_resume(version.id, request_id=uuid4())
    session.flush()
    assert profile.default_resume_version_id == version.id

    with pytest.raises(ValueError, match="owned blob-backed resume"):
        profile.select_default_resume(other_version.id, request_id=uuid4())

    artifact.archived_at = utc_now()
    session.flush()
    with pytest.raises(ValueError, match="owned blob-backed resume"):
        profile.select_default_resume(version.id, request_id=uuid4())

    assert other_artifact.owner_id == stranger.id


def test_upload_is_idempotent_and_preserves_original_bytes(client, engine) -> None:
    key = uuid4()
    response = upload(client, key=key)

    assert response.status_code == 202, response.text
    imported = response.json()
    assert imported["state"] == "queued"
    assert imported["filename"] == "resume.txt"
    assert imported["media_type"] == "text/plain"
    assert imported["byte_size"] == len(b"Synthetic resume text")
    assert imported["extraction_version_id"] is None
    assert upload(client, key=key).json()["id"] == imported["id"]
    assert upload(client, key=key, content=b"Changed synthetic text").status_code == 409

    downloaded = client.get(
        f"/api/v1/artifacts/{imported['artifact_id']}/versions/"
        f"{imported['source_version_id']}/download"
    )
    assert downloaded.status_code == 200
    assert downloaded.content == b"Synthetic resume text"
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert downloaded.headers["content-disposition"].startswith("attachment;")

    with Session(engine) as db:
        job = db.get(DocumentImport, imported["id"])
        assert job is not None
        task = db.get(Task, job.task_id)
        assert task is not None and task.state == "open"


def test_default_resume_stays_on_the_exact_selected_original(client) -> None:
    first = upload(client).json()
    selected = client.post(
        "/api/v1/profile/default-resume",
        json={"version_id": first["source_version_id"], "expected_version": 1},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert selected.status_code == 200, selected.text
    artifact = client.get(f"/api/v1/artifacts/{first['artifact_id']}").json()

    second = upload(
        client,
        artifact_id=first["artifact_id"],
        expected_version=artifact["row_version"],
        content=b"A newer synthetic resume",
    )
    assert second.status_code == 202, second.text
    current = client.get("/api/v1/profile/default-resume")
    assert current.status_code == 200
    assert current.json()["version_id"] == first["source_version_id"]
    assert current.json()["version_id"] != second.json()["source_version_id"]

    current_artifact = client.get(f"/api/v1/artifacts/{first['artifact_id']}").json()
    archived = client.post(
        f"/api/v1/artifacts/{first['artifact_id']}/archive",
        json={"expected_version": current_artifact["row_version"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert archived.status_code == 200, archived.text
    assert client.get("/api/v1/profile/default-resume").status_code == 409


def test_upload_validation_cancel_retry_and_owner_isolation(client, engine) -> None:
    invalid = upload(
        client,
        content=b"not a pdf",
        filename="misleading.pdf",
        upload_media_type="application/pdf",
    )
    assert invalid.status_code == 422
    oversized = upload(client, content=b"x" * (20 * 1024 * 1024 + 1))
    assert oversized.status_code == 413

    imported = upload(client).json()
    cancelled = client.post(
        f"/api/v1/documents/imports/{imported['id']}/cancel",
        json={"expected_version": imported["row_version"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert cancelled.status_code == 200 and cancelled.json()["state"] == "cancelled"
    retried = client.post(
        f"/api/v1/documents/imports/{imported['id']}/retry",
        json={"expected_version": cancelled.json()["row_version"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert retried.status_code == 200 and retried.json()["state"] == "queued"

    stranger_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=stranger_id, kind="human", display_name="Other document owner"))
    from command_center.core.identity import Identity, authenticate

    client.app.dependency_overrides[authenticate] = lambda: Identity(stranger_id, "other")
    assert client.get(f"/api/v1/documents/imports/{imported['id']}").status_code == 404
    assert (
        client.get(
            f"/api/v1/artifacts/{imported['artifact_id']}/versions/"
            f"{imported['source_version_id']}/download"
        ).status_code
        == 404
    )


def test_worker_creates_one_derived_version_without_completing_review_task(
    client, engine, monkeypatch
) -> None:
    from command_center.documents import worker

    imported = upload(client).json()

    class SyntheticDocling:
        def __init__(self, base_url: str, api_key: str = "") -> None:
            assert base_url == "http://127.0.0.1:5001"
            assert api_key == ""

        async def convert(self, data: bytes, filename: str, media_type: str):
            assert data == b"Synthetic resume text"
            assert (filename, media_type) == ("resume.txt", "text/plain")
            await asyncio.sleep(0.05)
            with Session(engine) as db:
                running = db.get(DocumentImport, imported["id"])
                assert running is not None and running.state == "running"
                assert running.row_version >= 3  # Independent heartbeat renewed the lease.
            return SimpleNamespace(
                text="Synthetic extracted resume text",
                document={"body": {"children": [{"text": "Synthetic extracted resume text"}]}},
                producer_version="1.34.0",
            )

        async def close(self) -> None:
            return None

    monkeypatch.setattr(worker, "DoclingClient", SyntheticDocling)
    monkeypatch.setattr(worker, "HEARTBEAT_SECONDS", 0.01)
    settings = client.app.state.document_test_settings
    assert worker.perform_document_import(engine, settings, imported["id"])
    assert not worker.perform_document_import(engine, settings, imported["id"])

    with Session(engine) as db:
        job = db.get(DocumentImport, imported["id"])
        assert job is not None and job.state == "completed"
        assert job.extraction_artifact_id is not None
        output = db.get(ArtifactVersion, job.extraction_version_id)
        assert output is not None
        assert output.schema_key == "docling.document.v1"
        assert output.payload == {
            "text": "Synthetic extracted resume text",
            "document": {"body": {"children": [{"text": "Synthetic extracted resume text"}]}},
            "producer_version": "1.34.0",
        }
        derivation = db.scalar(
            select(ArtifactDerivation).where(
                ArtifactDerivation.output_version_id == output.id,
                ArtifactDerivation.input_version_id == job.source_version_id,
            )
        )
        assert derivation is not None and derivation.method == "docling.convert"
        assert db.get(Task, job.task_id).state == "open"
        links = list(db.scalars(select(TaskArtifact).where(TaskArtifact.task_id == job.task_id)))
        assert {link.artifact_id for link in links} == {
            job.artifact_id,
            job.extraction_artifact_id,
        }


def test_retry_dispatches_only_after_the_queued_state_commits(client, engine) -> None:
    imported = upload(client).json()
    cancelled = client.post(
        f"/api/v1/documents/imports/{imported['id']}/cancel",
        json={"expected_version": imported["row_version"]},
        headers={"Idempotency-Key": str(uuid4())},
    ).json()
    observed: list[str] = []

    def observe(import_id) -> None:
        with Session(engine) as db:
            job = db.get(DocumentImport, import_id)
            assert job is not None and job.state == "queued"
            observed.append(str(job.id))

    client.document_dispatch.side_effect = observe
    response = client.post(
        f"/api/v1/documents/imports/{imported['id']}/retry",
        json={"expected_version": cancelled["row_version"]},
        headers={"Idempotency-Key": str(uuid4())},
    )

    assert response.status_code == 200, response.text
    assert observed == [imported["id"]]


def test_cancellation_during_conversion_fences_output_publication(
    client, engine, monkeypatch
) -> None:
    from command_center.documents import worker

    imported = upload(client).json()
    started = threading.Event()
    release = threading.Event()

    class WaitingDocling:
        def __init__(self, base_url: str, api_key: str = "") -> None:
            pass

        async def convert(self, data: bytes, filename: str, media_type: str):
            started.set()
            await asyncio.to_thread(release.wait)
            return SimpleNamespace(
                text="Output that must be fenced after cancellation",
                document={"body": {}},
                producer_version="synthetic",
            )

        async def close(self) -> None:
            return None

    monkeypatch.setattr(worker, "DoclingClient", WaitingDocling)
    execution = threading.Thread(
        target=worker.perform_document_import,
        args=(engine, client.app.state.document_test_settings, imported["id"]),
    )
    execution.start()
    assert started.wait(timeout=2)
    with Session(engine) as db, db.begin():
        job = db.get(DocumentImport, imported["id"])
        assert job is not None and job.state == "running"
        job.cancel(request_id=uuid4())
    release.set()
    execution.join(timeout=2)
    assert not execution.is_alive()

    with Session(engine) as db:
        job = db.get(DocumentImport, imported["id"])
        assert job is not None and job.state == "cancelled"
        assert job.extraction_artifact_id is None and job.extraction_version_id is None
        assert (
            db.scalar(
                select(ArtifactDerivation).where(
                    ArtifactDerivation.input_version_id == job.source_version_id
                )
            )
            is None
        )


def test_expired_lease_cannot_publish_a_completed_conversion(client, engine, monkeypatch) -> None:
    from command_center.documents import worker

    imported = upload(client).json()
    started = threading.Event()
    release = threading.Event()

    class WaitingDocling:
        def __init__(self, base_url: str, api_key: str = "") -> None:
            pass

        async def convert(self, data: bytes, filename: str, media_type: str):
            started.set()
            await asyncio.to_thread(release.wait)
            return SimpleNamespace(
                text="Stale output that must never be persisted",
                document={"body": {}},
                producer_version="synthetic",
            )

        async def close(self) -> None:
            return None

    monkeypatch.setattr(worker, "DoclingClient", WaitingDocling)
    execution = threading.Thread(
        target=worker.perform_document_import,
        args=(engine, client.app.state.document_test_settings, imported["id"]),
    )
    execution.start()
    assert started.wait(timeout=2)
    with Session(engine) as db, db.begin():
        job = db.get(DocumentImport, imported["id"])
        assert job is not None and job.state == "running"
        job.lease_expires_at = utc_now() - timedelta(seconds=1)
        db.flush()
        assert DocumentImport.expire_stale(db) == 1
    release.set()
    execution.join(timeout=2)
    assert not execution.is_alive()

    with Session(engine) as db:
        job = db.get(DocumentImport, imported["id"])
        assert job is not None and job.state == "failed"
        assert job.error == "conversion_lease_expired"
        assert job.extraction_artifact_id is None and job.extraction_version_id is None
