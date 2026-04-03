"""Strip repeated headers/footers and fix hyphenation."""

from __future__ import annotations

import re
from collections import Counter

from doc2md.models import Page


def detect_repeated_lines(pages: list[Page], min_occurrences: int = 3) -> set[str]:
    """Find text lines that appear on multiple pages (likely headers/footers)."""
    first_lines: list[str] = []
    last_lines: list[str] = []

    for page in pages:
        lines = page.raw_text.strip().splitlines()
        if lines:
            first_lines.append(lines[0].strip())
            last_lines.append(lines[-1].strip())

    repeated = set()
    for line, count in Counter(first_lines).items():
        if count >= min_occurrences and line:
            repeated.add(line)
    for line, count in Counter(last_lines).items():
        if count >= min_occurrences and line:
            repeated.add(line)

    return repeated


def strip_headers_footers(pages: list[Page], repeated: set[str]) -> list[Page]:
    """Remove repeated header/footer lines from pages."""
    if not repeated:
        return pages

    cleaned = []
    for page in pages:
        lines = page.raw_text.splitlines()
        filtered = [l for l in lines if l.strip() not in repeated]
        cleaned.append(Page(
            source_path=page.source_path,
            raw_text="\n".join(filtered),
            extraction_method=page.extraction_method,
            page_number=page.page_number,
        ))
    return cleaned


def fix_hyphenation(text: str) -> str:
    """Join words split by end-of-line hyphenation."""
    return re.sub(r"(\w)-\n(\w)", r"\1\2", text)


def join_broken_sentences(text_a: str, text_b: str) -> str:
    """Join two page texts if a sentence spans the page break."""
    a = text_a.rstrip()
    b = text_b.lstrip()

    if not a or not b:
        return a + "\n" + b

    # If page A ends mid-sentence (no terminal punctuation) and page B starts lowercase
    if a[-1] not in ".!?:;\"'" and b[0].islower():
        return a + " " + b

    return a + "\n\n" + b
