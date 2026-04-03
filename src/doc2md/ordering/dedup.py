"""Page deduplication using hash, fuzzy matching, and LLM fallback."""

from __future__ import annotations

import logging
from difflib import SequenceMatcher

from doc2md.analysis.llm_client import OllamaClient
from doc2md.analysis.prompts import format_duplicate_detection
from doc2md.models import Page

logger = logging.getLogger(__name__)

FUZZY_THRESHOLD = 0.85


def deduplicate(pages: list[Page], llm_client: OllamaClient | None = None) -> list[Page]:
    """Remove duplicate pages using a tiered strategy."""
    if not pages:
        return []

    # Stage 1: exact hash dedup
    seen_hashes: dict[str, int] = {}
    unique_pages: list[Page] = []
    for page in pages:
        if page.content_hash not in seen_hashes:
            seen_hashes[page.content_hash] = len(unique_pages)
            unique_pages.append(page)
        else:
            logger.info("Exact duplicate removed: %s", page.source_path)

    # Stage 2: fuzzy dedup on adjacent pages (sorted by source path)
    if len(unique_pages) <= 1:
        return unique_pages

    result: list[Page] = [unique_pages[0]]
    for i in range(1, len(unique_pages)):
        prev = result[-1]
        curr = unique_pages[i]
        similarity = SequenceMatcher(None, prev.raw_text, curr.raw_text).ratio()

        if similarity >= FUZZY_THRESHOLD:
            # Keep the page with more text
            if len(curr.raw_text) > len(prev.raw_text):
                result[-1] = curr
            logger.info("Fuzzy duplicate removed (%.2f): %s", similarity, curr.source_path)
        elif similarity >= 0.7 and llm_client is not None:
            # Borderline — ask LLM
            is_dup = _llm_duplicate_check(llm_client, prev.raw_text, curr.raw_text)
            if is_dup:
                if len(curr.raw_text) > len(prev.raw_text):
                    result[-1] = curr
                logger.info("LLM confirmed duplicate: %s", curr.source_path)
            else:
                result.append(curr)
        else:
            result.append(curr)

    return result


def _llm_duplicate_check(client: OllamaClient, text_a: str, text_b: str) -> bool:
    """Use LLM to determine if two pages are duplicates."""
    prompt = format_duplicate_detection(text_a, text_b)
    try:
        response = client.generate_json(prompt)
        return response.get("is_duplicate", False)
    except Exception:
        logger.warning("LLM duplicate check failed, treating as non-duplicate")
        return False
