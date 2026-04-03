"""Classify text blocks on a page using LLM."""

from __future__ import annotations

import logging

from doc2md.analysis.llm_client import OllamaClient
from doc2md.analysis.prompts import format_block_classification
from doc2md.models import Page, TextBlock

logger = logging.getLogger(__name__)


def classify_page(page: Page, page_index: int, llm_client: OllamaClient) -> list[TextBlock]:
    """Classify text blocks on a single page."""
    if not page.raw_text.strip():
        return []

    prompt = format_block_classification(page.raw_text)
    try:
        response = llm_client.generate_json(prompt)
    except Exception:
        logger.warning("Classification failed for page %d, treating as body", page_index)
        return [TextBlock(text=page.raw_text, block_type="body", page_index=page_index)]

    if not isinstance(response, list):
        response = [response]

    blocks = []
    for item in response:
        block_type = item.get("type", "body")
        if block_type not in ("heading", "body", "footnote", "caption", "reference", "index"):
            block_type = "body"

        blocks.append(TextBlock(
            text=item.get("text", ""),
            block_type=block_type,
            page_index=page_index,
            heading_level=item.get("heading_level"),
            footnote_id=str(item["footnote_id"]) if item.get("footnote_id") is not None else None,
        ))

    return blocks


def classify_pages(pages: list[Page], llm_client: OllamaClient) -> list[TextBlock]:
    """Classify all pages and return a flat list of text blocks."""
    all_blocks = []
    for i, page in enumerate(pages):
        blocks = classify_page(page, i, llm_client)
        all_blocks.extend(blocks)
    return all_blocks
