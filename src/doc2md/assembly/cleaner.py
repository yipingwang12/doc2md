"""Strip repeated headers/footers, fix hyphenation, and normalize text."""

from __future__ import annotations

import re
from collections import Counter

from doc2md.models import Page

LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "ﬆ": "st"}


def normalize_ligatures(text: str) -> str:
    """Replace Unicode ligature characters with their ASCII equivalents."""
    for lig, replacement in LIGATURES.items():
        text = text.replace(lig, replacement)
    return text


def detect_repeated_lines(pages: list[Page], min_occurrences: int = 3, check_lines: int = 3) -> set[str]:
    """Find text lines that appear on multiple pages (likely headers/footers)."""
    candidate_lines: list[str] = []

    for page in pages:
        lines = page.raw_text.strip().splitlines()
        if lines:
            for line in lines[:check_lines]:
                candidate_lines.append(line.strip())
            for line in lines[-check_lines:]:
                candidate_lines.append(line.strip())

    repeated = set()
    for line, count in Counter(candidate_lines).items():
        if count >= min_occurrences and line:
            repeated.add(line)

    return repeated


_PAGE_NUM_RE = re.compile(r"^\s*\d{1,4}\s*$")
_URL_RE = re.compile(r"https?://\S+")


def detect_boilerplate_lines(pages: list[Page]) -> set[str]:
    """Detect standalone page numbers and URL lines as boilerplate."""
    boilerplate = set()
    for page in pages:
        lines = page.raw_text.strip().splitlines()
        for line in lines[:3] + lines[-3:]:
            stripped = line.strip()
            if _PAGE_NUM_RE.match(stripped):
                boilerplate.add(stripped)
            if _URL_RE.search(stripped) and len(stripped) < 150:
                boilerplate.add(stripped)
    return boilerplate


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
            block_dicts=page.block_dicts,
            page_height=page.page_height,
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
