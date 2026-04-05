"""Detect chapter boundaries from classified text blocks."""

from __future__ import annotations

import json
import logging

from doc2md.analysis.llm_client import OllamaClient
from doc2md.analysis.prompts import format_chapter_boundary
from doc2md.models import Chapter, TextBlock

logger = logging.getLogger(__name__)


def detect_chapters(blocks: list[TextBlock], llm_client: OllamaClient) -> list[Chapter]:
    """Split blocks into chapters using rule-based detection with LLM fallback."""
    headings = [
        {"index": i, "text": b.text, "level": b.heading_level, "page": b.page_index}
        for i, b in enumerate(blocks)
        if b.block_type == "heading"
    ]

    if not headings:
        return [Chapter(title="Untitled", heading_level=1, blocks=blocks)]

    chapters = _detect_by_rules(blocks, headings)
    if chapters is not None:
        return chapters

    # Rule-based detection was ambiguous — fall back to LLM
    return _detect_by_llm(blocks, headings, llm_client)


def _detect_by_rules(blocks: list[TextBlock], headings: list[dict]) -> list[Chapter] | None:
    """Try to detect chapters from heading levels alone.

    Returns None if the result is ambiguous and LLM should be consulted.
    """
    level_1 = [h for h in headings if h.get("level") == 1]

    # No level-1 headings: single chapter, title = first heading
    if not level_1:
        first_idx = headings[0]["index"]
        remaining = blocks[:first_idx] + blocks[first_idx + 1:]
        return [Chapter(title=headings[0]["text"], heading_level=1, blocks=remaining)]

    # One or more level-1 headings: split into chapters (with front matter if needed)
    chapter_starts = [h["index"] for h in level_1]
    return _build_chapters(blocks, chapter_starts)


def _detect_by_llm(blocks: list[TextBlock], headings: list[dict], llm_client: OllamaClient) -> list[Chapter]:
    """Use LLM to identify chapter boundaries, with rule-based fallbacks."""
    chapter_starts = _llm_boundaries(headings, llm_client)

    if not chapter_starts:
        chapter_starts = [h["index"] for h in headings if h.get("level") == 1]

    if not chapter_starts:
        first_idx = headings[0]["index"]
        remaining = blocks[:first_idx] + blocks[first_idx + 1:]
        return [Chapter(title=headings[0]["text"], heading_level=1, blocks=remaining)]

    return _build_chapters(blocks, chapter_starts)


def _build_chapters(blocks: list[TextBlock], chapter_starts: list[int]) -> list[Chapter]:
    """Build Chapter objects from block indices marking chapter boundaries.

    Consecutive headings with no body content between them are merged into
    a single chapter title (e.g. "Part V" + "CHINA" → "Part V — CHINA").
    """
    # Merge consecutive chapter starts that have only headings between them
    merged_starts = _merge_adjacent_starts(blocks, chapter_starts)

    chapters = []
    for ci, (start_idx, title) in enumerate(merged_starts):
        next_start = merged_starts[ci + 1][0] if ci + 1 < len(merged_starts) else len(blocks)
        # Collect blocks between this start and the next, excluding heading blocks used in the title
        chapter_blocks = [
            b for b in blocks[start_idx:next_start]
            if not (b.block_type == "heading" and b.text in title)
        ]
        chapters.append(Chapter(
            title=title,
            heading_level=blocks[start_idx].heading_level or 1,
            blocks=chapter_blocks,
        ))

    if merged_starts[0][0] > 0:
        front_blocks = blocks[:merged_starts[0][0]]
        chapters.insert(0, Chapter(
            title="Front Matter",
            heading_level=1,
            blocks=front_blocks,
        ))

    return chapters


def _merge_adjacent_starts(blocks: list[TextBlock], chapter_starts: list[int]) -> list[tuple[int, str]]:
    """Merge consecutive chapter starts that have no body content between them.

    Returns list of (start_index, merged_title) tuples.
    """
    if not chapter_starts:
        return []

    merged: list[tuple[int, str]] = []

    for start_idx in chapter_starts:
        title = blocks[start_idx].text

        if merged:
            prev_idx, prev_title = merged[-1]
            # Check if all blocks between prev start and this one are headings
            between = blocks[prev_idx + 1:start_idx]
            if all(b.block_type == "heading" for b in between):
                merged[-1] = (prev_idx, prev_title + " — " + title)
                continue

        merged.append((start_idx, title))

    return merged


def _llm_boundaries(headings: list[dict], llm_client: OllamaClient) -> list[int]:
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
