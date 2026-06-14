"""Data models for the academic paper pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field

from doc2md.models import Chapter, Page


@dataclass
class PaperMetadata:
    pmid: str | None = None
    doi: str | None = None
    title: str = ""
    authors: list[str] = field(default_factory=list)
    journal: str = ""
    year: int | None = None


@dataclass
class NamedEntity:
    text: str
    entity_type: str   # gene | disease | chemical | species | variant | cell_line | cell_type | other
    entity_id: str     # normalised ID: e.g. NCBIGene:672, MeSH:D001943
    source: str        # "pubtator" | "bern2"
    section_label: str = ""   # abstract | introduction | methods | results | discussion | references
    start: int = 0     # char offset within section text
    end: int = 0
    context: str = ""  # surrounding sentence(s)


@dataclass
class PaperDocument:
    source_name: str
    metadata: PaperMetadata = field(default_factory=PaperMetadata)
    pages: list[Page] = field(default_factory=list)
    chapters: list[Chapter] = field(default_factory=list)
    entities: list[NamedEntity] = field(default_factory=list)


@dataclass
class EntityOccurrence:
    paper_source: str
    section: str
    context: str


@dataclass
class EntityIndex:
    entity_id: str
    entity_type: str
    display_name: str
    occurrences: list[EntityOccurrence] = field(default_factory=list)
