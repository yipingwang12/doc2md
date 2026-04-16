"""Two-column PDF layout reflow using PyMuPDF bounding boxes."""

from __future__ import annotations

from pathlib import Path

import fitz

from doc2md.models import Page

# A block spanning more than this fraction of page width is treated as full-width
_FULL_WIDTH_RATIO = 0.6
# The column gutter must fall between these fractions of page width
_GUTTER_MIN_RATIO = 0.30
_GUTTER_MAX_RATIO = 0.70
# Minimum gap width (as fraction of page) to count as a gutter
_MIN_GAP_RATIO = 0.05


def detect_column_split(blocks: list[dict], page_width: float) -> float | None:
    """Return x-coordinate of column gutter midpoint, or None for single-column pages.

    Looks for a horizontal gap in block right-edges / left-edges that falls
    between 30–70% of page width and is at least 5% of page width wide.
    """
    if len(blocks) < 2:
        return None

    text_blocks = [b for b in blocks if b.get("type") == 0]
    if not text_blocks:
        return None

    # Collect x-extents of blocks that don't span the full page width
    right_edges: list[float] = []
    left_edges: list[float] = []
    for b in text_blocks:
        x0, _, x1, _ = b["bbox"]
        width = x1 - x0
        if width / page_width >= _FULL_WIDTH_RATIO:
            continue
        right_edges.append(x0)
        left_edges.append(x1)

    if not right_edges:
        return None

    # Sort right-edges of left-column blocks and left-edges of right-column blocks.
    # A gutter shows up as a gap: max(right side of left col) to min(left side of right col).
    right_edges_sorted = sorted(right_edges)
    left_edges_sorted = sorted(left_edges)

    # Find the widest gap in x-starts that sits in the middle of the page
    candidates = []
    for i in range(len(left_edges_sorted) - 1):
        gap_start = left_edges_sorted[i]
        gap_end = right_edges_sorted[i + 1]
        if gap_end <= gap_start:
            continue
        gap_width = gap_end - gap_start
        midpoint = (gap_start + gap_end) / 2
        mid_ratio = midpoint / page_width
        if (_GUTTER_MIN_RATIO <= mid_ratio <= _GUTTER_MAX_RATIO
                and gap_width / page_width >= _MIN_GAP_RATIO):
            candidates.append((gap_width, midpoint))

    if not candidates:
        return None

    _, best_mid = max(candidates)
    return best_mid


def reorder_blocks_two_column(blocks: list[dict], split_x: float) -> list[dict]:
    """Re-sort blocks into two-column reading order (left column then right).

    Full-width blocks (spanning the split) are placed first in their original
    relative order. Within each column, blocks are sorted by y0 ascending.
    Non-text blocks (images, drawings) are kept at their original relative position.
    """
    if not blocks:
        return []

    full_width: list[tuple[int, dict]] = []
    left_col: list[tuple[float, dict]] = []
    right_col: list[tuple[float, dict]] = []
    non_text: list[tuple[int, dict]] = []

    for i, b in enumerate(blocks):
        if b.get("type") != 0:
            non_text.append((i, b))
            continue
        x0, y0, x1, _ = b["bbox"]
        if x0 < split_x and x1 > split_x:
            full_width.append((i, b))
        elif x1 <= split_x:
            left_col.append((y0, b))
        else:
            right_col.append((y0, b))

    ordered = [b for _, b in sorted(full_width, key=lambda t: t[0])]
    ordered += [b for _, b in sorted(left_col)]
    ordered += [b for _, b in sorted(right_col)]

    # Re-insert non-text blocks at their original relative positions
    for orig_idx, nb in sorted(non_text):
        insert_at = min(orig_idx, len(ordered))
        ordered.insert(insert_at, nb)

    return ordered


def extract_two_column_pages(pdf_path: Path) -> list[Page]:
    """Extract pages with two-column reflow applied where detected.

    For single-column pages, falls back to standard block order.
    Returns the same Page objects as extract_pages, but with raw_text
    assembled in reading order for two-column layouts.
    """
    pages = []
    doc = fitz.open(pdf_path)
    try:
        for i in range(len(doc)):
            page = doc[i]
            page_dict = page.get_text("dict", sort=True)
            page_width = page_dict.get("width", 595.0)
            blocks = page_dict.get("blocks", [])

            split_x = detect_column_split(blocks, page_width)
            if split_x is not None:
                blocks = reorder_blocks_two_column(blocks, split_x)

            # Reconstruct raw_text from reordered blocks
            lines = []
            for b in blocks:
                if b.get("type") != 0:
                    continue
                for line in b.get("lines", []):
                    line_text = "".join(s["text"] for s in line.get("spans", []))
                    if line_text.strip():
                        lines.append(line_text)
            raw_text = "\n".join(lines)

            pages.append(Page(
                source_path=pdf_path,
                raw_text=raw_text,
                extraction_method="pymupdf",
                page_number=i + 1,
                block_dicts=blocks,
                page_height=page_dict.get("height", 842.0),
            ))
    finally:
        doc.close()
    return pages
