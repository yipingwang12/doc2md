"""Link in-text citations to bibliography entries."""

from __future__ import annotations

import re

from doc2md.models import Chapter, TextBlock

# Pattern for bracketed number citations like [1], [23]
BRACKET_NUM_PATTERN = re.compile(r"\[(\d+)\]")

# Pattern for author-year citations like (Smith, 2020) or (Smith 2020)
AUTHOR_YEAR_PATTERN = re.compile(r"\(([A-Z][a-z]+(?:\s+(?:et\s+al\.?|and\s+[A-Z][a-z]+))?),?\s+(\d{4})\)")


def link_citations(chapter: Chapter) -> Chapter:
    """Extract reference blocks and link citations in body text."""
    references: list[str] = []
    body_blocks: list[TextBlock] = []

    for block in chapter.blocks:
        if block.block_type == "reference":
            references.append(block.text)
        else:
            body_blocks.append(block)

    return Chapter(
        title=chapter.title,
        heading_level=chapter.heading_level,
        blocks=body_blocks,
        footnotes=chapter.footnotes,
        bibliography=chapter.bibliography + references,
    )


def detect_citation_style(text: str) -> str:
    """Detect whether citations use bracket-number or author-year style."""
    bracket_count = len(BRACKET_NUM_PATTERN.findall(text))
    author_year_count = len(AUTHOR_YEAR_PATTERN.findall(text))

    if bracket_count > author_year_count:
        return "bracket_number"
    elif author_year_count > 0:
        return "author_year"
    return "unknown"
