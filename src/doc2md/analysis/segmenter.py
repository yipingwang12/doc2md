"""Rule-based page segmentation using PyMuPDF block structure and font metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass

from doc2md.assembly.cleaner import normalize_ligatures
from doc2md.models import TextBlock


@dataclass
class FontProfile:
    """Dominant font sizes detected across a document's pages."""
    body_size: float = 0.0
    body_font: str = ""
    footnote_size: float = 0.0
    heading_sizes: list[float] = None
    heading_fonts: set[str] = None
    repeated_lines: set[str] = None

    def __post_init__(self):
        if self.heading_sizes is None:
            self.heading_sizes = []
        if self.heading_fonts is None:
            self.heading_fonts = set()
        if self.repeated_lines is None:
            self.repeated_lines = set()


def build_font_profile(pages_blocks: list[list[dict]], repeated_lines: set[str] | None = None) -> FontProfile:
    """Detect dominant font sizes and fonts from PyMuPDF block dicts."""
    size_char_counts: dict[float, int] = {}
    font_char_counts: dict[str, int] = {}
    size_font_chars: dict[tuple[float, str], int] = {}

    for blocks in pages_blocks:
        for b in blocks:
            if b.get("type") != 0:
                continue
            for line in b.get("lines", []):
                for span in line.get("spans", []):
                    size = round(span["size"], 1)
                    font = span.get("font", "")
                    n = len(span["text"])
                    size_char_counts[size] = size_char_counts.get(size, 0) + n
                    font_char_counts[font] = font_char_counts.get(font, 0) + n
                    size_font_chars[(size, font)] = size_font_chars.get((size, font), 0) + n

    if not size_char_counts:
        return FontProfile(repeated_lines=repeated_lines or set())

    sorted_sizes = sorted(size_char_counts.items(), key=lambda x: -x[1])
    body_size = sorted_sizes[0][0]

    # Body font: most common font at body size
    body_fonts_at_size = {f: c for (s, f), c in size_font_chars.items() if s == body_size}
    body_font = max(body_fonts_at_size, key=body_fonts_at_size.get) if body_fonts_at_size else ""

    # Heading fonts: fonts used at body size for short blocks that differ from body font
    # These are detected as fonts that appear at body size but are NOT the dominant body font
    heading_fonts: set[str] = set()
    for (size, font), count in size_font_chars.items():
        if abs(size - body_size) < 1.0 and font != body_font and count > 0:
            # Only count as heading font if it has much less text than body font
            # (headings are short, body is long)
            if count < body_fonts_at_size.get(body_font, 0) * 0.3:
                heading_fonts.add(font)

    footnote_size = 0.0
    heading_sizes = []
    for size, _ in sorted_sizes[1:]:
        if size < body_size and size > 5.0:
            if footnote_size == 0.0 or abs(size - footnote_size) < 1.0:
                footnote_size = max(footnote_size, size)
        elif size > body_size:
            heading_sizes.append(size)

    heading_sizes.sort(reverse=True)

    return FontProfile(
        body_size=body_size,
        body_font=body_font,
        footnote_size=footnote_size,
        heading_sizes=heading_sizes,
        heading_fonts=heading_fonts,
        repeated_lines=repeated_lines or set(),
    )


def _line_text(line: dict) -> str:
    """Extract plain text from a single PyMuPDF line dict."""
    return "".join(span["text"] for span in line.get("spans", []))


def _block_text(block: dict) -> str:
    """Extract plain text from a PyMuPDF block dict."""
    if block.get("type") != 0:
        return ""
    parts = [_line_text(line) for line in block.get("lines", [])]
    return normalize_ligatures("\n".join(parts))


def _dominant_size(block: dict) -> float:
    """Return the font size that covers the most characters in a block."""
    size_counts: dict[float, int] = {}
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            size = round(span["size"], 1)
            size_counts[size] = size_counts.get(size, 0) + len(span["text"])
    if not size_counts:
        return 0.0
    return max(size_counts, key=size_counts.get)


def _dominant_font(block: dict) -> str:
    """Return the font name that covers the most characters in a block."""
    font_counts: dict[str, int] = {}
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            font = span.get("font", "")
            font_counts[font] = font_counts.get(font, 0) + len(span["text"])
    if not font_counts:
        return ""
    return max(font_counts, key=font_counts.get)


def _line_starts_with_superscript_number(line: dict) -> str | None:
    """Check if a line starts with a superscript footnote number."""
    spans = line.get("spans", [])
    if not spans:
        return None

    first_span = spans[0]
    text = first_span["text"].strip()
    if not text or not re.match(r"^\d+$", text):
        return None

    for s in spans[1:]:
        if s["text"].strip():
            if first_span["size"] < s["size"] * 0.8:
                return text
            break

    return None


def _split_footnote_block(block: dict) -> list[tuple[str, str]]:
    """Split a footnote block containing multiple footnotes at superscript number boundaries.

    Returns list of (footnote_id, text) tuples.
    """
    lines = block.get("lines", [])
    if not lines:
        return []

    segments: list[tuple[str | None, list[str]]] = []
    current_id = None
    current_lines: list[str] = []

    for line in lines:
        fn_id = _line_starts_with_superscript_number(line)
        if fn_id is not None:
            if current_lines:
                segments.append((current_id, current_lines))
            current_id = fn_id
            current_lines = [normalize_ligatures(_line_text(line))]
        else:
            current_lines.append(normalize_ligatures(_line_text(line)))

    if current_lines:
        segments.append((current_id, current_lines))

    return [(fid or "", "\n".join(lines_)) for fid, lines_ in segments]


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
    re.compile(r"^[\u25CF\u2022\u25E6\u25AA\u25AB\u2023\u2043\s]+$"),  # symbol-only lines
]
_FIGURE_PANEL_RE = re.compile(r"^([A-Za-z]|\d{1,3}/\d{1,3})$")


def _is_boilerplate(text: str) -> bool:
    """Check if text is a page number, URL, preprint watermark, or other boilerplate."""
    stripped = text.strip()
    if _PAGE_NUM_RE.match(stripped):
        return True
    if _URL_RE.search(stripped) and len(stripped) < 150:
        return True
    if any(pat.search(stripped) for pat in _PREPRINT_WATERMARK_RES):
        return True
    return False


def _is_figure_panel_label(text: str) -> bool:
    """Return True if text is a figure panel label (single letter or N/M fraction)."""
    return bool(_FIGURE_PANEL_RE.match(text.strip()))


def _is_all_caps_heading(text: str) -> bool:
    """Check if text is an ALL CAPS section heading."""
    stripped = text.strip()
    if "\n" in stripped:
        return False
    if len(stripped) < 3 or len(stripped) > 120:
        return False
    alpha = [c for c in stripped if c.isalpha()]
    if not alpha:
        return False
    return all(c.isupper() for c in alpha)


_MATH_SYMBOLS_RE = re.compile(r"[α-ωΑ-Ω∑∏∫√≤≥≠±×÷∈∉⊂⊃∪∩→←↔∞]")
_MATH_EXPRESSION_RE = re.compile(
    r"[=\u2212\u02C6\u02DC]"       # =, − (typeset minus), ˆ (hat), ˜ (tilde)
    r"|[α-ωΑ-Ω∑∏∫√≤≥≠±×÷∈∉⊂⊃∪∩→←↔∞]"  # Greek letters and math operators
)


def _is_math_expression(text: str) -> bool:
    """Return True if text looks like a mathematical expression rather than a heading."""
    return bool(_MATH_EXPRESSION_RE.search(text.strip()))


def _is_prose_fragment(line: str) -> bool:
    """Check if a short line looks like a word from prose (not math/tables)."""
    stripped = line.strip()
    if not stripped:
        return False
    if _MATH_SYMBOLS_RE.search(stripped):
        return False
    # Single non-word characters (likely diagram labels)
    if len(stripped) <= 1:
        return False
    # Purely numeric (page numbers, table entries)
    if stripped.replace(".", "").replace(",", "").isdigit():
        return False
    # Must contain at least one letter
    if not any(c.isalpha() for c in stripped):
        return False
    return True


def _rejoin_lines(text: str) -> str:
    """Rejoin single-word lines caused by PyMuPDF extracting centered/indented text.

    Only joins sequences of short lines that look like prose fragments.
    Skips mathematical notation, diagrams, and table-of-contents entries.
    """
    lines = text.split("\n")
    if len(lines) <= 1:
        return text

    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if len(stripped) < 15 and _is_prose_fragment(stripped) and not stripped.endswith((".", "!", "?", ":", ";")):
            short_run = [stripped]
            j = i + 1
            while j < len(lines) and len(lines[j].strip()) < 15 and _is_prose_fragment(lines[j]):
                short_run.append(lines[j].strip())
                j += 1
            if len(short_run) >= 3:
                result.append(" ".join(short_run))
                i = j
                continue
        result.append(line)
        i += 1

    return "\n".join(result)


def _classify_block(
    block: dict,
    profile: FontProfile,
    page_height: float,
) -> list[TextBlock]:
    """Classify a single PyMuPDF block dict into TextBlocks.

    May return multiple TextBlocks if a footnote block contains multiple footnotes.
    """
    text = _block_text(block).strip()
    if not text:
        return []

    if _is_boilerplate(text):
        return []

    # Filter lines repeated across many pages (running headers/footers, author names)
    for line in text.splitlines():
        stripped = line.strip()
        if stripped in profile.repeated_lines:
            text = text.replace(line, "").strip()
    if not text or _is_boilerplate(text):
        return []

    dom_size = _dominant_size(block)
    bbox = block.get("bbox", (0, 0, 0, 0))
    block_y = bbox[1]

    # Heading: larger font than body text
    if dom_size > profile.body_size + 1.0 and len(text) < 200:
        if _is_figure_panel_label(text) or _is_math_expression(text):
            return []
        level = 1
        if profile.heading_sizes:
            for i, hs in enumerate(profile.heading_sizes):
                if abs(dom_size - hs) < 1.0:
                    level = i + 1
                    break
        return [TextBlock(
            text=text,
            block_type="heading",
            page_index=0,
            heading_level=min(level, 3),
        )]

    # Heading: ALL CAPS body-sized text (section headings)
    if _is_all_caps_heading(text) and abs(dom_size - profile.body_size) < 1.5:
        if _is_math_expression(text):
            return []
        return [TextBlock(
            text=text,
            block_type="heading",
            page_index=0,
            heading_level=2,
        )]

    # Heading: body-sized text in a heading font (e.g. AGaramond-Titling)
    if (
        profile.heading_fonts
        and abs(dom_size - profile.body_size) < 1.5
        and len(text) < 120
        and "\n" not in text
    ):
        dom_font = _dominant_font(block)
        if dom_font in profile.heading_fonts:
            if _is_figure_panel_label(text) or _is_math_expression(text):
                return []
            return [TextBlock(
                text=text,
                block_type="heading",
                page_index=0,
                heading_level=2,
            )]

    # Footnote: check for superscript numbers and split if multiple footnotes in one block
    is_footnote_sized = (
        profile.footnote_size > 0
        and abs(dom_size - profile.footnote_size) < 1.0
        and block_y > page_height * 0.4
    )
    first_line_fn = _line_starts_with_superscript_number(block.get("lines", [{}])[0]) if block.get("lines") else None

    if first_line_fn is not None or is_footnote_sized:
        segments = _split_footnote_block(block)
        if segments:
            results = []
            for fn_id, fn_text in segments:
                fn_text = fn_text.strip()
                if not fn_text:
                    continue
                if not fn_id:
                    fn_match = re.match(r"^(\d+)\s+", fn_text)
                    fn_id = fn_match.group(1) if fn_match else None
                results.append(TextBlock(
                    text=fn_text,
                    block_type="footnote",
                    page_index=0,
                    footnote_id=fn_id,
                ))
            if results:
                return results

    # Caption
    if re.match(r"^(Figure|Fig\.|Table|Plate)\s+\d", text, re.IGNORECASE):
        return [TextBlock(text=text, block_type="caption", page_index=0)]

    # Body: rejoin broken lines
    text = _rejoin_lines(text)
    return [TextBlock(text=text, block_type="body", page_index=0)]


def segment_page_blocks(
    blocks: list[dict],
    page_index: int,
    profile: FontProfile,
    page_height: float = 800.0,
) -> list[TextBlock]:
    """Segment a page's PyMuPDF block dicts into classified TextBlocks.

    Consecutive footnote blocks without IDs are merged into the preceding footnote.
    """
    raw: list[TextBlock] = []
    for block in blocks:
        if block.get("type") != 0:
            continue
        text_blocks = _classify_block(block, profile, page_height)
        for tb in text_blocks:
            tb.page_index = page_index
        raw.extend(text_blocks)

    # Merge consecutive footnote continuations into the previous footnote
    result: list[TextBlock] = []
    for tb in raw:
        if (
            tb.block_type == "footnote"
            and tb.footnote_id is None
            and result
            and result[-1].block_type == "footnote"
        ):
            result[-1] = TextBlock(
                text=result[-1].text + "\n" + tb.text,
                block_type="footnote",
                page_index=result[-1].page_index,
                footnote_id=result[-1].footnote_id,
            )
        else:
            result.append(tb)

    return result


def segment_raw_text(raw_text: str, page_index: int) -> list[TextBlock]:
    """Fallback segmentation from raw text (for OCR pages without block structure)."""
    paragraphs = re.split(r"\n\s*\n", raw_text.strip())
    blocks = []
    total = len(paragraphs)

    for i, para in enumerate(paragraphs):
        para = para.strip()
        if not para:
            continue

        if _is_boilerplate(para):
            continue

        if _is_all_caps_heading(para):
            blocks.append(TextBlock(
                text=para, block_type="heading", page_index=page_index, heading_level=2,
            ))
            continue

        fn_match = re.match(r"^(\d+)\s+\S", para)
        if fn_match and i >= total // 2:
            blocks.append(TextBlock(
                text=para, block_type="footnote", page_index=page_index,
                footnote_id=fn_match.group(1),
            ))
            continue

        if re.match(r"^(Figure|Fig\.|Table|Plate)\s+\d", para, re.IGNORECASE):
            blocks.append(TextBlock(text=para, block_type="caption", page_index=page_index))
            continue

        blocks.append(TextBlock(text=para, block_type="body", page_index=page_index))

    return blocks
