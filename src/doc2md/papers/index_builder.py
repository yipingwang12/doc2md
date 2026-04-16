"""Cross-paper entity inverted index.

Builds and maintains {entity_id → EntityIndex} from a list of PaperDocuments.
Supports incremental updates: load → merge → write.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from doc2md.papers.models import EntityIndex, EntityOccurrence, PaperDocument


def build_entity_index(paper_docs: list[PaperDocument]) -> dict[str, EntityIndex]:
    """Build inverted index keyed by normalised entity_id."""
    index: dict[str, EntityIndex] = {}
    for doc in paper_docs:
        for entity in doc.entities:
            if entity.entity_id not in index:
                index[entity.entity_id] = EntityIndex(
                    entity_id=entity.entity_id,
                    entity_type=entity.entity_type,
                    display_name=entity.text,
                )
            occ = EntityOccurrence(
                paper_source=doc.source_name,
                section=entity.section_label,
                context=entity.context,
            )
            entry = index[entity.entity_id]
            if not _occurrence_exists(entry.occurrences, occ):
                entry.occurrences.append(occ)
    return index


def _occurrence_exists(occurrences: list[EntityOccurrence], occ: EntityOccurrence) -> bool:
    return any(o.paper_source == occ.paper_source and o.section == occ.section for o in occurrences)


def merge_into_index(
    existing: dict[str, EntityIndex],
    new_entries: dict[str, EntityIndex],
) -> dict[str, EntityIndex]:
    """Merge new index entries into existing, deduplicating occurrences."""
    merged = {k: v for k, v in existing.items()}
    for entity_id, new_entry in new_entries.items():
        if entity_id not in merged:
            merged[entity_id] = new_entry
        else:
            for occ in new_entry.occurrences:
                if not _occurrence_exists(merged[entity_id].occurrences, occ):
                    merged[entity_id].occurrences.append(occ)
    return merged


def write_entity_index_json(index: dict[str, EntityIndex], path: Path) -> None:
    """Serialise entity index to JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    serialisable = {k: asdict(v) for k, v in index.items()}
    path.write_text(json.dumps(serialisable, indent=2, ensure_ascii=False))


def load_entity_index(path: Path) -> dict[str, EntityIndex]:
    """Load entity_index.json; return empty dict if file absent."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    result: dict[str, EntityIndex] = {}
    for entity_id, v in data.items():
        occurrences = [EntityOccurrence(**o) for o in v.get("occurrences", [])]
        result[entity_id] = EntityIndex(
            entity_id=v["entity_id"],
            entity_type=v["entity_type"],
            display_name=v["display_name"],
            occurrences=occurrences,
        )
    return result


def write_entity_index_md(index: dict[str, EntityIndex], path: Path) -> None:
    """Render entity index as Markdown: grouped by type, sorted by display name."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Entity Index\n"]

    if not index:
        path.write_text("# Entity Index\n\n*No entities indexed.*\n")
        return

    # Group by entity type
    by_type: dict[str, list[EntityIndex]] = {}
    for entry in index.values():
        by_type.setdefault(entry.entity_type, []).append(entry)

    for etype in sorted(by_type):
        lines.append(f"\n## {etype.replace('_', ' ').title()}\n")
        for entry in sorted(by_type[etype], key=lambda e: e.display_name.lower()):
            papers = sorted({o.paper_source for o in entry.occurrences})
            paper_list = ", ".join(f"`{p}`" for p in papers)
            lines.append(f"- **{entry.display_name}** (`{entry.entity_id}`) — {paper_list}\n")

    path.write_text("".join(lines))
