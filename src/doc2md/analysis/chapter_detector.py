"""Detect chapter boundaries from classified text blocks."""

from __future__ import annotations

import json
import logging

from doc2md.analysis.llm_client import OllamaClient
from doc2md.analysis.prompts import format_chapter_boundary
from doc2md.models import Chapter, TextBlock

logger = logging.getLogger(__name__)


def detect_chapters(blocks: list[TextBlock], llm_client: OllamaClient) -> list[Chapter]:
    """Split blocks into chapters based on LLM-detected boundaries."""
    headings = [
        {"index": i, "text": b.text, "level": b.heading_level, "page": b.page_index}
        for i, b in enumerate(blocks)
        if b.block_type == "heading"
    ]

    if not headings:
        return [Chapter(title="Untitled", heading_level=1, blocks=blocks)]

    chapter_starts = _detect_boundaries(headings, llm_client)

    if not chapter_starts:
        # Fallback: use level-1 headings
        chapter_starts = [h["index"] for h in headings if h.get("level") == 1]

    if not chapter_starts:
        return [Chapter(title=headings[0]["text"], heading_level=1, blocks=blocks)]

    chapters = []
    for ci, start_idx in enumerate(chapter_starts):
        end_idx = chapter_starts[ci + 1] if ci + 1 < len(chapter_starts) else len(blocks)
        heading = blocks[start_idx]
        chapter_blocks = blocks[start_idx + 1:end_idx]
        chapters.append(Chapter(
            title=heading.text,
            heading_level=heading.heading_level or 1,
            blocks=chapter_blocks,
        ))

    # Prepend blocks before first chapter as front matter
    if chapter_starts[0] > 0:
        front_blocks = blocks[:chapter_starts[0]]
        chapters.insert(0, Chapter(
            title="Front Matter",
            heading_level=1,
            blocks=front_blocks,
        ))

    return chapters


def _detect_boundaries(headings: list[dict], llm_client: OllamaClient) -> list[int]:
    """Use LLM to identify which headings are chapter boundaries."""
    prompt = format_chapter_boundary(json.dumps(headings))
    try:
        response = llm_client.generate_json(prompt)
        if not isinstance(response, list):
            return []
        return [
            headings[item["heading_index"]]["index"]
            for item in response
            if item.get("is_chapter_start") is True
            and isinstance(item.get("heading_index"), int)
            and 0 <= item["heading_index"] < len(headings)
        ]
    except Exception:
        logger.warning("Chapter boundary detection failed, using heading levels")
        return []
