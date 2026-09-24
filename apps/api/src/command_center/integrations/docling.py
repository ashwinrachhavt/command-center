"""Bounded, byte-only conversion through the configured local Docling service."""

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

MAX_RESULT_BYTES = 8 * 1024 * 1024
MAX_EXTRACTED_CHARS = 200_000
CONVERSION_SECONDS = 180


class DoclingError(Exception):
    """Safe public error; never includes source contents or provider response bodies."""


@dataclass(frozen=True)
class ExtractedDocument:
    text: str
    document: dict[str, Any]
    producer_version: str


class DoclingClient:
    def __init__(self, base_url: str, api_key: str = ""):
        self.http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Accept-Encoding": "identity", **({"X-Api-Key": api_key} if api_key else {})},
            timeout=20,
            follow_redirects=False,
            trust_env=False,
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def _json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        async with self.http.stream(method, path, **kwargs) as response:
            if (
                not response.is_success
                or response.headers.get("content-encoding", "identity") != "identity"
            ):
                raise DoclingError("Document conversion service rejected the request")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_RESULT_BYTES:
                    raise DoclingError("Converted document exceeds the supported size")
            try:
                value = json.loads(body)
            except (ValueError, UnicodeError):
                raise DoclingError("Document conversion returned an invalid result") from None
        if not isinstance(value, dict):
            raise DoclingError("Document conversion returned an invalid result")
        return value

    async def convert(self, data: bytes, filename: str, media_type: str) -> ExtractedDocument:
        formats = {
            "application/pdf": "pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
            "text/plain": "md",
            "text/markdown": "md",
            "image/jpeg": "image",
            "image/png": "image",
        }
        if media_type not in formats or not data or len(data) > 20 * 1024 * 1024:
            raise DoclingError("Unsupported source document")
        source_format = formats[media_type]
        # Only bytes are submitted. Filenames cannot select URLs or filesystem locations.
        extension = {"image/jpeg": "jpg", "image/png": "png"}.get(media_type, source_format)
        upload_name = f"document.{extension}"
        try:
            async with asyncio.timeout(CONVERSION_SECONDS):
                versions = await self._json("GET", "/version")
                version = versions.get("docling-serve")
                if not isinstance(version, str) or not re.fullmatch(
                    r"[a-zA-Z0-9.+_-]{1,80}", version
                ):
                    raise DoclingError("Document conversion service did not report its version")
                job = await self._json(
                    "POST",
                    "/v1/convert/file/async",
                    files={"files": (upload_name, data, media_type)},
                    data={
                        "from_formats": [source_format],
                        "to_formats": ["md", "json"],
                        "target_type": "inbody",
                        "image_export_mode": "placeholder",
                        "include_images": "false",
                        "include_page_images": "false",
                        "do_ocr": "true",
                        "force_ocr": "true" if source_format == "image" else "false",
                        "do_picture_description": "false",
                        "do_picture_classification": "false",
                        "do_chart_extraction": "false",
                        "do_code_enrichment": "false",
                        "do_formula_enrichment": "false",
                        "pipeline": "standard",
                        "document_timeout": "120",
                        "abort_on_error": "true",
                    },
                )
                task_id = job.get("task_id")
                if not isinstance(task_id, str) or not re.fullmatch(
                    r"[a-zA-Z0-9_-]{1,100}", task_id
                ):
                    raise DoclingError("Document conversion did not return a valid task")
                while job.get("task_status") in {"pending", "started"}:
                    job = await self._json("GET", f"/v1/status/poll/{task_id}", params={"wait": 2})
                    if job.get("task_id") != task_id:
                        raise DoclingError("Document conversion returned an unrelated task")
                    if job.get("task_status") in {"pending", "started"}:
                        await asyncio.sleep(0.2)
                if job.get("task_status") != "success":
                    raise DoclingError(
                        "Document conversion failed or produced an incomplete result"
                    )
                result = await self._json("GET", f"/v1/result/{task_id}")
                exported = result.get("document")
                if result.get("status") != "success" or not isinstance(exported, dict):
                    raise DoclingError("Document conversion produced an incomplete result")
                text = exported.get("md_content")
                document = exported.get("json_content")
                if not isinstance(text, str) or not text.strip() or not isinstance(document, dict):
                    raise DoclingError("Document conversion did not produce reviewable text")
                if (
                    source_format == "image"
                    and not re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()
                ):
                    raise DoclingError("Document conversion did not produce reviewable text")
                if len(text) > MAX_EXTRACTED_CHARS:
                    raise DoclingError("Extracted text exceeds the supported size")
                return ExtractedDocument(text, document, f"docling-serve/{version}")
        except (httpx.HTTPError, TimeoutError):
            raise DoclingError("Document conversion service is unavailable or timed out") from None
