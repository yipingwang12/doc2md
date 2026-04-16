"""Strip repeated headers/footers, fix hyphenation, and normalize text."""

from __future__ import annotations

import re
from collections import Counter

from doc2md.models import Page

LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "ﬆ": "st"}

# PDF font encoding maps Semitic transliteration characters (ayin ʿ, alef ʾ)
# to ASCII control codes. Common in Cambridge UP Arabic/Hebrew scholarship PDFs.
_CONTROL_CHAR_MAP = {
    "\x02": "\u02BF",  # STX → ʿ (modifier letter left half ring / ayin)
    "\x03": "\u02BE",  # ETX → ʾ (modifier letter right half ring / alef)
}

# PDF Private Use Area font encoding: U+F7XX → chr(0xXX).
# Common in PDFs using decorative fonts (e.g. AGaramond-Titling) that remap
# standard ASCII characters to PUA codepoints. PyMuPDF extracts these as raw
# Unicode, rendering as boxes in the browser.
_PUA_RE = re.compile(r"[\uF720-\uF77E]+")


def _replace_pua(match: re.Match) -> str:
    return "".join(chr(ord(c) - 0xF700) for c in match.group())


def normalize_ligatures(text: str) -> str:
    """Replace Unicode ligature characters with their ASCII equivalents."""
    for lig, replacement in LIGATURES.items():
        text = text.replace(lig, replacement)
    text = _PUA_RE.sub(_replace_pua, text)
    for ctrl, replacement in _CONTROL_CHAR_MAP.items():
        text = text.replace(ctrl, replacement)
    text = normalize_transliteration(text)
    return text


# Cambridge UP PDFs encode Arabic/Islamic transliteration diacritics using
# standalone characters instead of Unicode combining marks:
#   U+00AF (¯) instead of combining macron U+0304
#   U+002E (.) as dot-below U+0323 before vowels in Arabic names
#   U+0131 (ı) dotless-i often follows a macron, producing ¯ı instead of ī

# Standalone macron between a letter and a vowel: the macron marks the
# following vowel as long (e.g. b¯a → bā).  Capture the next char so we
# can emit it + combining macron in the right order.
_MACRON_RE = re.compile(r"\u00af([A-Za-z\u0131])(?=[A-Za-z\u0131\s,\u02be\u02bf()\u2019]|$)")

# Period used as dot-below: letter + . + vowel/macron (Arabic: Ḥ Ṭ Ṣ Ḍ Ẓ)
_DOT_BELOW_RE = re.compile(r"(?<=[A-Za-z])\.(?=[\u00af\u0131a-z])")


def normalize_transliteration(text: str) -> str:
    """Fix PDF-extracted Arabic/Islamic transliteration diacritics.

    Converts standalone macron (U+00AF) to combining macron (U+0304) on the
    following vowel, period-as-dot-below to combining dot below (U+0323),
    and dotless-i (U+0131) to regular i after combining macron (→ ī).
    """
    text = _DOT_BELOW_RE.sub("\u0323", text)
    text = _MACRON_RE.sub(lambda m: m.group(1) + "\u0304", text)
    # dotless-i with combining macron → ī
    text = text.replace("\u0131\u0304", "\u012b")
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
_PREPRINT_WATERMARK_RES = [
    re.compile(r"CC-BY\s+\d", re.IGNORECASE),
    re.compile(r"not certified by peer review", re.IGNORECASE),
    re.compile(r"bioRxiv\b", re.IGNORECASE),
    re.compile(r"medrxiv\b", re.IGNORECASE),
    re.compile(r"The copyright holder for this preprint", re.IGNORECASE),
    re.compile(r"author/funder", re.IGNORECASE),
    re.compile(r"perpetuity\b", re.IGNORECASE),
    re.compile(r"^\s*[.;]\s*$"),  # standalone punctuation artifacts
]


def _is_watermark_line(line: str) -> bool:
    return any(pat.search(line) for pat in _PREPRINT_WATERMARK_RES)


def strip_preprint_watermarks(pages: list[Page]) -> list[Page]:
    """Remove preprint server watermark lines (bioRxiv, medRxiv, CC-BY notices)."""
    cleaned = []
    for page in pages:
        lines = page.raw_text.splitlines()
        filtered = [l for l in lines if not _is_watermark_line(l)]
        cleaned.append(Page(
            source_path=page.source_path,
            raw_text="\n".join(filtered),
            extraction_method=page.extraction_method,
            page_number=page.page_number,
            block_dicts=page.block_dicts,
            page_height=page.page_height,
        ))
    return cleaned


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
