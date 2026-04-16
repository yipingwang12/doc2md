"""Merge and deduplicate entity lists from PubTator and BERN2.

PubTator spans take priority over overlapping BERN2 spans.
All canonical type mapping is centralised here.
"""

from __future__ import annotations

from doc2md.papers.models import NamedEntity

_CANONICAL_TYPES: dict[str, str] = {
    "gene": "gene",
    "protein": "gene",
    "disease": "disease",
    "chemical": "chemical",
    "drug": "chemical",
    "species": "species",
    "organism": "species",
    "variant": "variant",
    "mutation": "variant",
    "genomicvariant": "variant",
    "cell_line": "cell_line",
    "cellline": "cell_line",
    "cell_type": "cell_type",
    "celltype": "cell_type",
}


def map_entity_type(raw_type: str) -> str:
    """Normalise a raw type string to a canonical entity type."""
    return _CANONICAL_TYPES.get(raw_type.lower(), "other")


def merge_entity_sources(
    pubtator_entities: list[NamedEntity],
    bern2_entities: list[NamedEntity],
) -> list[NamedEntity]:
    """Merge two entity lists; PubTator exact spans take priority over BERN2.

    For an exact (start, end) match, the PubTator entity is kept.
    Partial overlaps are kept from both sources (conservative).
    """
    pubtator_spans: set[tuple[int, int]] = {(e.start, e.end) for e in pubtator_entities}
    filtered_bern2 = [e for e in bern2_entities if (e.start, e.end) not in pubtator_spans]
    return list(pubtator_entities) + filtered_bern2


def deduplicate_entities(entities: list[NamedEntity]) -> list[NamedEntity]:
    """Remove exact duplicate (entity_id, start, end) entries, preserving order."""
    seen: set[tuple[str, int, int]] = set()
    result: list[NamedEntity] = []
    for e in entities:
        key = (e.entity_id, e.start, e.end)
        if key not in seen:
            seen.add(key)
            result.append(e)
    return result
