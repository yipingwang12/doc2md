"""Cross-volume index-guided entity search.

Searches linked index files across all volumes, follows markdown links
to chapter files, and extracts paragraphs containing the search term.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from doc2md.assembly.index_linker import _find_index_file, _term_variants, _PP_RE


@dataclass
class SearchHit:
    volume: str
    chapter_dir: str
    chapter_path: Path
    index_term: str
    page_ref: str
    paragraphs: list[str] = field(default_factory=list)


@dataclass
class SearchResult:
    query: str
    hits: list[SearchHit] = field(default_factory=list)


_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_PAGE_HEADING_RE = re.compile(r"^#{1,4}\s+\d+\s*$")


def parse_linked_index_line(line: str) -> tuple[str, list[tuple[str, str]]]:
    """Extract term and markdown links from a linked index line.

    Returns (term, [(page_label, relative_path), ...]).
    """
    if not line.strip():
        return "", []

    links = [(m.group(1), m.group(2)) for m in _LINK_RE.finditer(line)]

    # Term is everything before the first link or trailing page refs
    if links:
        first_link_pos = line.index(f"[{links[0][0]}]")
        term = line[:first_link_pos].rstrip(", ")
    else:
        term = line.strip()

    return term, links


def match_term(query: str, index_term: str) -> bool:
    """Check if query matches an index term using variant expansion."""
    if not query or not index_term:
        return False
    q_variants = _term_variants(query)
    t_variants = _term_variants(index_term)
    for qv in q_variants:
        for tv in t_variants:
            if qv in tv or tv in qv:
                return True
    return False


def extract_paragraphs(
    text: str, query: str, context: int = 0,
) -> list[str]:
    """Extract paragraphs containing any variant of query.

    Strips page-number headings. Returns matching paragraphs plus
    `context` surrounding paragraphs (deduplicated).
    """
    # Strip page-number headings
    lines = text.splitlines()
    filtered = [l for l in lines if not _PAGE_HEADING_RE.match(l.strip())]
    clean = "\n".join(filtered)

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", clean) if p.strip()]

    variants = _term_variants(query)
    match_indices = set()
    for i, para in enumerate(paragraphs):
        para_lower = para.lower()
        if any(v in para_lower for v in variants):
            match_indices.add(i)

    if not match_indices:
        return []

    # Expand with context
    include = set()
    for idx in match_indices:
        for offset in range(-context, context + 1):
            pos = idx + offset
            if 0 <= pos < len(paragraphs):
                include.add(pos)

    return [paragraphs[i] for i in sorted(include)]


def search_volume(
    volume_dir: Path, query: str, context: int = 0,
) -> list[SearchHit]:
    """Search a single volume's linked index for a term."""
    index_file = _find_index_file(volume_dir)
    if not index_file:
        return []

    text = index_file.read_text(encoding="utf-8", errors="replace")

    # Check if index has links at all
    if "](" not in text:
        return []

    volume_name = volume_dir.name
    hits_by_chapter: dict[Path, SearchHit] = {}

    for line in text.splitlines():
        term, links = parse_linked_index_line(line)
        if not links or not match_term(query, term):
            continue

        for page_label, rel_path in links:
            chapter_path = (index_file.parent / rel_path).resolve()
            if not chapter_path.exists():
                continue

            if chapter_path in hits_by_chapter:
                existing = hits_by_chapter[chapter_path]
                if term not in existing.index_term:
                    existing.index_term += f"; {term}"
                if page_label not in existing.page_ref:
                    existing.page_ref += f", {page_label}"
                continue

            chapter_text = chapter_path.read_text(
                encoding="utf-8", errors="replace",
            )
            paragraphs = extract_paragraphs(chapter_text, query, context)
            if not paragraphs:
                continue

            chapter_dir = chapter_path.parent.name
            hit = SearchHit(
                volume=volume_name,
                chapter_dir=chapter_dir,
                chapter_path=chapter_path,
                index_term=term,
                page_ref=page_label,
                paragraphs=paragraphs,
            )
            hits_by_chapter[chapter_path] = hit

    return list(hits_by_chapter.values())


def search_all(
    output_dir: Path, query: str, context: int = 0,
) -> SearchResult:
    """Search across all volumes in the output directory."""
    result = SearchResult(query=query)
    for child in sorted(output_dir.iterdir()):
        if not child.is_dir():
            continue
        hits = search_volume(child, query, context)
        result.hits.extend(hits)
    return result


def _chapter_display_name(dir_name: str) -> str:
    """Convert '100_pp_27_61_islamic_culture' to 'Islamic Culture (pp. 27\u201361)'."""
    m = _PP_RE.search(dir_name)
    if not m:
        label = dir_name.replace("_", " ").strip()
        return label.title() if label else dir_name

    start, end = m.group(1), m.group(2)
    name_part = dir_name[m.end():].strip("_").replace("_", " ")
    title = name_part.title() if name_part else "Chapter"
    return f"{title} (pp. {start}\u2013{end})"


def format_results(result: SearchResult) -> str:
    """Render search results as terminal-friendly grouped output."""
    if not result.hits:
        return f"No results found for '{result.query}'."

    parts = []
    for hit in result.hits:
        chapter_name = _chapter_display_name(hit.chapter_dir)
        header = f"## {hit.volume} > {chapter_name}"
        index_line = f"Index: {hit.index_term}, {hit.page_ref}"
        body = "\n\n".join(hit.paragraphs)
        parts.append(f"{header}\n{index_line}\n\n{body}")

    return "\n\n".join(parts) + "\n"
