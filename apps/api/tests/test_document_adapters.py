import asyncio
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from command_center.core.storage import MAX_BLOB_BYTES, BlobStore
from command_center.integrations.docling import DoclingClient, DoclingError


def test_content_addressed_blobs_are_atomic_private_and_verified(tmp_path):
    store = BlobStore(tmp_path / "blobs")
    content = b"Synthetic resume, no personal data."
    with ThreadPoolExecutor(max_workers=4) as pool:
        saved = list(pool.map(store.put, [content] * 8))
    assert len({value.sha256 for value in saved}) == 1
    blob = saved[0]
    assert blob.storage_key == f"sha256/{hashlib.sha256(content).hexdigest()}"
    assert store.read(blob.sha256) == content
    assert os.stat(store.path(blob.sha256)).st_mode & 0o777 == 0o600
    assert len(list((tmp_path / "blobs" / "sha256").iterdir())) == 1
    store.path(blob.sha256).write_bytes(b"Tampered")
    with pytest.raises(ValueError, match="integrity"):
        store.read(blob.sha256)
    with pytest.raises(ValueError, match="integrity"):
        store.put(content)


def test_blob_store_rejects_path_escape_symlinks_and_oversize(tmp_path):
    store = BlobStore(tmp_path / "blobs")
    outside = tmp_path / "outside"
    outside.write_text("Synthetic private bytes")
    for digest in ("../outside", "A" * 64, "/tmp/file"):
        with pytest.raises(ValueError, match="digest"):
            store.read(digest)
    (store.root / "sha256" / ("a" * 64)).symlink_to(outside)
    with pytest.raises(ValueError, match="symbolic"):
        store.read("a" * 64)
    with pytest.raises(ValueError, match="20 MiB"):
        store.put(b"x" * (MAX_BLOB_BYTES + 1))
    linked_root = tmp_path / "link"
    linked_root.symlink_to(store.root, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic"):
        BlobStore(linked_root)


def run_conversion(mocker, respond):
    client_type = httpx.AsyncClient
    mocker.patch(
        "command_center.integrations.docling.httpx.AsyncClient",
        side_effect=lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs),
    )

    async def run():
        client = DoclingClient("http://docling.local:5001", "synthetic-service-key")
        try:
            return await client.convert(b"Synthetic candidate.\nPython", "resume.txt", "text/plain")
        finally:
            await client.close()

    return asyncio.run(run())


def test_docling_uploads_bytes_and_preserves_complete_versioned_result(mocker):
    requests = []

    def respond(request):
        requests.append(request)
        assert request.headers["x-api-key"] == "synthetic-service-key"
        if request.url.path == "/version":
            return httpx.Response(200, json={"docling-serve": "1.34.0"})
        if request.url.path == "/v1/convert/file/async":
            body = request.content
            assert b"Synthetic candidate." in body
            assert b'filename="document.md"' in body
            assert b'name="from_formats"\r\n\r\nmd' in body
            assert b'name="include_images"\r\n\r\nfalse' in body
            assert b'name="to_formats"\r\n\r\njson' in body
            assert b"url_sources" not in body
            return httpx.Response(200, json={"task_id": "conversion-1", "task_status": "pending"})
        if request.url.path == "/v1/status/poll/conversion-1":
            return httpx.Response(200, json={"task_id": "conversion-1", "task_status": "success"})
        assert request.url.path == "/v1/result/conversion-1"
        return httpx.Response(
            200,
            json={
                "status": "success",
                "document": {
                    "md_content": "Synthetic candidate.\nPython",
                    "json_content": {"texts": [{"text": "Python"}]},
                },
            },
        )

    result = run_conversion(mocker, respond)
    assert result.text == "Synthetic candidate.\nPython"
    assert result.document["texts"][0]["text"] == "Python"
    assert result.producer_version == "docling-serve/1.34.0"
    assert len(requests) == 4


@pytest.mark.parametrize("state", ["failure", "partial_success", "skipped", "unknown"])
def test_docling_does_not_publish_incomplete_results(mocker, state):
    def respond(request):
        if request.url.path == "/version":
            return httpx.Response(200, json={"docling-serve": "1.34.0"})
        assert request.url.path == "/v1/convert/file/async"
        return httpx.Response(200, json={"task_id": "conversion-1", "task_status": state})

    with pytest.raises(DoclingError, match="incomplete"):
        run_conversion(mocker, respond)


def test_docling_rejects_unrelated_poll_result_and_hides_provider_errors(mocker):
    def respond(request):
        if request.url.path == "/version":
            return httpx.Response(200, json={"docling-serve": "1.34.0"})
        if request.url.path == "/v1/convert/file/async":
            return httpx.Response(200, json={"task_id": "conversion-1", "task_status": "pending"})
        return httpx.Response(200, json={"task_id": "other-user-task", "task_status": "success"})

    with pytest.raises(DoclingError, match="unrelated"):
        run_conversion(mocker, respond)


def test_docling_enforces_result_size(mocker):
    mocker.patch("command_center.integrations.docling.MAX_RESULT_BYTES", 20)
    with pytest.raises(DoclingError, match="size"):
        run_conversion(mocker, lambda _: httpx.Response(200, content=b"x" * 21))
