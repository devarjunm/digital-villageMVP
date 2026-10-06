"""Document parsing, cleaning and chunking for the RAG pipeline.

Chunking is heading-aware and size-bounded: it splits on markdown/plain headings
first, then packs paragraphs up to RAG_CHUNK_CHARS with RAG_CHUNK_OVERLAP_CHARS
of overlap so a sentence spanning a boundary is still retrievable. Each chunk
keeps its heading so citations can point at a section, not just a document.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.core.config import settings

HEADING_RE = re.compile(r"^(#{1,6}\s+.+|[A-Z][A-Z0-9 ,\-/&()]{6,})$", re.MULTILINE)
PAGE_NUMBER_RE = re.compile(
    r"^\s*(page\s+\d+|\d+\s*\|\s*page)\s*$", re.IGNORECASE | re.MULTILINE
)
MULTI_BLANK_RE = re.compile(r"\n{3,}")
MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")


@dataclass(slots=True)
class Chunk:
    index: int
    heading: str | None
    content: str
    char_count: int
    token_estimate: int
    content_hash: str


class UnsupportedDocumentError(ValueError):
    pass


def clean_text(text: str) -> str:
    """Normalise whitespace and strip artefacts (page footers, control chars)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    text = PAGE_NUMBER_RE.sub("", text)
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    text = MULTI_SPACE_RE.sub(" ", text)
    text = MULTI_BLANK_RE.sub("\n\n", text)
    return text.strip()


def parse_document(
    *, filename: str | None, content_type: str | None, data: bytes
) -> str:
    """Extract text. Supported: text/plain, text/markdown, text/html (tag strip).
    PDF/DOCX require optional extractors and raise clearly when absent."""
    name = (filename or "").lower()
    if name.endswith((".txt", ".md", ".markdown")) or (content_type or "").startswith(
        "text/plain"
    ):
        return clean_text(data.decode("utf-8", errors="replace"))
    if name.endswith((".html", ".htm")) or (content_type or "").startswith("text/html"):
        raw = data.decode("utf-8", errors="replace")
        raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
        raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
        raw = re.sub(r"</(p|div|li|h[1-6])>", "\n", raw, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", raw)
        import html as html_lib

        return clean_text(html_lib.unescape(text))
    if name.endswith(".pdf"):
        try:
            import pypdf  # optional dependency
        except ImportError as exc:  # pragma: no cover - optional path
            raise UnsupportedDocumentError(
                "PDF ingestion requires the 'pypdf' package. Install backend/requirements-ml.txt extras "
                "or convert the document to text/markdown."
            ) from exc
        import io

        reader = pypdf.PdfReader(io.BytesIO(data))
        return clean_text("\n".join(page.extract_text() or "" for page in reader.pages))
    raise UnsupportedDocumentError(
        "Unsupported document type for ingestion. Supported: .txt, .md, .html, .pdf (with pypdf installed)."
    )


def chunk_text(
    text: str,
    *,
    max_chars: int | None = None,
    overlap_chars: int | None = None,
) -> list[Chunk]:
    max_chars = max_chars or settings.rag_chunk_chars
    overlap_chars = overlap_chars or settings.rag_chunk_overlap_chars
    text = clean_text(text)
    if not text:
        return []

    sections: list[tuple[str | None, str]] = []
    current_heading: str | None = None
    current_lines: list[str] = []
    for line in text.split("\n"):
        if HEADING_RE.match(line.strip()) and len(line.strip()) < 120:
            if current_lines:
                sections.append((current_heading, "\n".join(current_lines).strip()))
                current_lines = []
            current_heading = line.strip().lstrip("#").strip()
            continue
        current_lines.append(line)
    if current_lines:
        sections.append((current_heading, "\n".join(current_lines).strip()))

    chunks: list[Chunk] = []
    index = 0
    for heading, section in sections:
        if not section:
            continue
        paragraphs = [p.strip() for p in section.split("\n\n") if p.strip()]
        buffer = ""
        for paragraph in paragraphs:
            candidate = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
            if len(candidate) <= max_chars:
                buffer = candidate
                continue
            if buffer:
                chunks.append(_make_chunk(index, heading, buffer))
                index += 1
                buffer = _overlap_tail(buffer, overlap_chars)
            # A single paragraph longer than max_chars is hard-split on sentence
            # boundaries so no chunk exceeds the embedding model's window.
            while len(paragraph) > max_chars:
                split_at = paragraph.rfind(". ", 0, max_chars)
                split_at = split_at + 1 if split_at > max_chars * 0.5 else max_chars
                chunks.append(_make_chunk(index, heading, paragraph[:split_at].strip()))
                index += 1
                paragraph = paragraph[split_at:].strip()
                if not paragraph:
                    break
            buffer = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
        if buffer:
            chunks.append(_make_chunk(index, heading, buffer))
            index += 1
    return chunks


def _overlap_tail(text: str, overlap_chars: int) -> str:
    if overlap_chars <= 0 or len(text) <= overlap_chars:
        return ""
    tail = text[-overlap_chars:]
    boundary = tail.find(" ")
    return tail[boundary + 1 :] if boundary > 0 else tail


def _make_chunk(index: int, heading: str | None, content: str) -> Chunk:
    content = content.strip()
    return Chunk(
        index=index,
        heading=heading,
        content=content,
        char_count=len(content),
        token_estimate=max(1, len(content) // 4),
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def source_text_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
