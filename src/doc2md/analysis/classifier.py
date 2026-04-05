"""Classify text blocks on a page using rule-based segmentation with LLM fallback."""

from __future__ import annotations

import logging

from doc2md.analysis.llm_client import OllamaClient
from doc2md.analysis.segmenter import (
    FontProfile,
    build_font_profile,
    segment_page_blocks,
    segment_raw_text,
)
from doc2md.models import Page, TextBlock

logger = logging.getLogger(__name__)


def classify_page(page: Page, page_index: int, llm_client: OllamaClient, profile: FontProfile | None = None) -> list[TextBlock]:
    """Classify text blocks on a single page using block structure or raw text fallback."""
    if not page.raw_text.strip():
        return []

    if page.block_dicts and profile:
        return segment_page_blocks(page.block_dicts, page_index, profile, page.page_height or 800.0)

    return segment_raw_text(page.raw_text, page_index)


def classify_pages(pages: list[Page], llm_client: OllamaClient, repeated_lines: set[str] | None = None) -> list[TextBlock]:
    """Classify all pages and return a flat list of text blocks."""
    profile = None
    pages_with_blocks = [p for p in pages if p.block_dicts]
    if pages_with_blocks:
        profile = build_font_profile(
            [p.block_dicts for p in pages_with_blocks],
            repeated_lines=repeated_lines,
        )

    all_blocks = []
    for i, page in enumerate(pages):
        blocks = classify_page(page, i, llm_client, profile)
        all_blocks.extend(blocks)
    return all_blocks
