"""Data models shared across all pipeline stages."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Page:
    source_path: Path
    raw_text: str
    extraction_method: str  # "pymupdf" | "surya"
    page_number: int | None = None
    content_hash: str = ""
    block_dicts: list[dict] | None = None  # PyMuPDF block dicts for structured extraction
    page_height: float = 0.0

    def __post_init__(self):
        if not self.content_hash:
            self.content_hash = hashlib.sha256(self.raw_text.encode()).hexdigest()


@dataclass
class TextBlock:
    text: str
    block_type: str  # heading | body | footnote | caption | reference | index
    page_index: int
    heading_level: int | None = None
    footnote_id: str | None = None
    citation_key: str | None = None
    section_label: str | None = None  # abstract | introduction | methods | results | discussion | references


@dataclass
class Chapter:
    title: str
    heading_level: int
    blocks: list[TextBlock] = field(default_factory=list)
    footnotes: dict[str, str] = field(default_factory=dict)
    bibliography: list[str] = field(default_factory=list)


@dataclass
class Document:
    source_name: str
    pages: list[Page] = field(default_factory=list)
    chapters: list[Chapter] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
