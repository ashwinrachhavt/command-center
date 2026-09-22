"""Render bounded Markdown through a fixed template with every URL fetch denied."""

import html
import json
import struct
import sys

from markdown_it import MarkdownIt
from weasyprint import HTML
from weasyprint.urls import FatalURLFetchingError

MAX_INPUT = 1024 * 1024
MAX_OUTPUT = 10 * 1024 * 1024

length_bytes = sys.stdin.buffer.read(8)
if len(length_bytes) != 8:
    raise SystemExit(2)
length = struct.unpack(">Q", length_bytes)[0]
if length > MAX_INPUT:
    raise SystemExit(2)
raw = sys.stdin.buffer.read(length)
if len(raw) != length:
    raise SystemExit(2)
try:
    request = json.loads(raw)
except (ValueError, UnicodeError):
    raise SystemExit(2) from None
title = request.get("title") if isinstance(request, dict) else None
markdown = request.get("markdown") if isinstance(request, dict) else None
if (
    request.get("version") != 1
    or not isinstance(title, str)
    or not 0 < len(title.strip()) <= 300
    or not isinstance(markdown, str)
    or len(markdown) > 100_000
):
    raise SystemExit(2)


def deny_fetch(url: str, *args: object, **kwargs: object) -> object:
    del url, args, kwargs
    raise FatalURLFetchingError("External resources are disabled")


body = MarkdownIt("commonmark", {"html": False, "linkify": False}).render(markdown)
document_html = f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
@page {{ size: Letter; margin: 0.7in; }}
body {{ color: #171717; font: 10.5pt/1.45 DejaVu Sans, sans-serif; }}
h1, h2, h3 {{ break-after: avoid; line-height: 1.2; }}
h1 {{ font-size: 20pt; }} h2 {{ font-size: 15pt; }} h3 {{ font-size: 12pt; }}
pre, code {{ font-family: DejaVu Sans Mono, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #d4d4d4; padding: 4pt; vertical-align: top; }}
a {{ color: #174ea6; overflow-wrap: anywhere; }}
img, object, embed, svg {{ display: none !important; }}
</style><title>{html.escape(title)}</title></head>
<body><h1>{html.escape(title)}</h1>{body}</body></html>"""
document = HTML(string=document_html, url_fetcher=deny_fetch).render()
if len(document.pages) > 200:
    raise SystemExit(2)
pdf = document.write_pdf()
if len(pdf) > MAX_OUTPUT or not pdf.startswith(b"%PDF-"):
    raise SystemExit(2)
sys.stdout.buffer.write(pdf)
