"""Reorder pages by detected page numbers."""

from __future__ import annotations

import logging

from doc2md.analysis.llm_client import OllamaClient
from doc2md.analysis.prompts import format_page_number
from doc2md.models import Page

logger = logging.getLogger(__name__)


def detect_page_numbers(pages: list[Page], llm_client: OllamaClient) -> list[Page]:
    """Use LLM to detect page numbers and assign them to pages."""
    for page in pages:
        if page.page_number is not None:
            continue
        prompt = format_page_number(page.raw_text)
        try:
            response = llm_client.generate_json(prompt)
            num = response.get("page_number")
            if isinstance(num, int) and num > 0:
                page.page_number = num
        except Exception:
            logger.warning("Page number detection failed for %s", page.source_path)
    return pages


def reorder_pages(pages: list[Page]) -> list[Page]:
    """Sort pages by page number, putting unnumbered pages first in original order."""
    numbered = [(i, p) for i, p in enumerate(pages) if p.page_number is not None]
    unnumbered = [(i, p) for i, p in enumerate(pages) if p.page_number is None]

    numbered.sort(key=lambda x: x[1].page_number)
    unnumbered.sort(key=lambda x: x[0])  # preserve original order

    return [p for _, p in unnumbered] + [p for _, p in numbered]


def find_page_gaps(pages: list[Page]) -> list[int]:
    """Find missing page numbers in the sequence."""
    numbers = sorted(p.page_number for p in pages if p.page_number is not None)
    if len(numbers) < 2:
        return []
    gaps = []
    for i in range(len(numbers) - 1):
        for missing in range(numbers[i] + 1, numbers[i + 1]):
            gaps.append(missing)
    return gaps
