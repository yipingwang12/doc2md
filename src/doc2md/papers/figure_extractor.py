"""Extract figure images from academic paper PDFs.

Two strategies:
- Raster: embedded images via page.get_images() + doc.extract_image()
- Vector fallback: render image-type blocks via page.get_pixmap() clip
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import fitz  # PyMuPDF

_CAPTION_RE = re.compile(r"^(figure|fig\.)\s+(S?\d+[A-Za-z]?)", re.IGNORECASE)
_MIN_SIZE_PTS = 150.0
_CAPTION_SEARCH_DIST = 150.0


def _caption_figure_id(text: str) -> str | None:
    """Return figure ID from caption text, or None if not a caption."""
    m = _CAPTION_RE.match(text.strip())
    if not m:
        return None
    return m.group(2)


def _find_caption(page: fitz.Page, img_bbox: fitz.Rect) -> tuple[str | None, str | None]:
    """Find nearest caption below img_bbox within _CAPTION_SEARCH_DIST pts.

    Returns (figure_id, full_caption_text).
    """
    blocks = page.get_text("blocks")
    candidates = []
    for b in blocks:
        x0, y0, x1, y1, text, *_ = b
        if y0 < img_bbox.y1:
            continue
        if y0 > img_bbox.y1 + _CAPTION_SEARCH_DIST:
            continue
        text = text.strip()
        if _CAPTION_RE.match(text):
            candidates.append((y0, text))
    if not candidates:
        return None, None
    candidates.sort(key=lambda t: t[0])
    caption_text = candidates[0][1]
    return _caption_figure_id(caption_text), caption_text


def _extract_raster(
    doc: fitz.Document,
    page: fitz.Page,
    output_dir: Path,
    page_num: int,
    dpi: int,
) -> list[dict]:
    """Extract embedded raster images from page."""
    figures = []
    seen_xrefs: set[int] = set()
    for img_info in page.get_images(full=True):
        xref = img_info[0]
        if xref in seen_xrefs:
            continue
        seen_xrefs.add(xref)

        img_data = doc.extract_image(xref)
        if not img_data:
            continue
        w = img_data.get("width", 0)
        h = img_data.get("height", 0)
        if w < _MIN_SIZE_PTS or h < _MIN_SIZE_PTS:
            continue

        # Locate bbox on page via get_image_rects
        rects = page.get_image_rects(xref)
        bbox = rects[0] if rects else fitz.Rect(0, 0, w, h)

        ext = img_data.get("ext", "png")
        figures.append({
            "_bbox": bbox,
            "_data": img_data["image"],
            "_ext": ext,
            "_page": page_num,
        })
    return figures


def _extract_vector_fallback(
    page: fitz.Page,
    output_dir: Path,
    page_num: int,
    dpi: int,
) -> list[dict]:
    """Render image-type blocks on pages where raster extraction found nothing."""
    figures = []
    blocks = page.get_text("rawdict")["blocks"]
    for b in blocks:
        if b.get("type") != 1:
            continue
        bbox = fitz.Rect(b["bbox"])
        if bbox.width < _MIN_SIZE_PTS or bbox.height < _MIN_SIZE_PTS:
            continue
        scale = dpi / 72
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat, clip=bbox)
        figures.append({
            "_bbox": bbox,
            "_pixmap": pix,
            "_ext": "png",
            "_page": page_num,
        })
    return figures


def extract_figures_from_pdf(
    pdf_path: Path,
    pages: list,
    output_dir: Path,
    dpi: int = 150,
) -> list[dict]:
    """Extract figures from pdf_path; write images under output_dir/figures/.

    Args:
        pdf_path: Source PDF.
        pages: Page objects from the pipeline (used for page count reference).
        output_dir: Per-paper output dir (e.g. results/papers/smith_2024/).
        dpi: Render DPI for vector fallback.

    Returns:
        List of figure dicts with keys: figure_id, image_path, caption, page.
    """
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf_path))
    results: list[dict] = []
    idx_counter: dict[int, int] = {}  # page → count for fallback IDs

    for page_num in range(len(doc)):
        page = doc[page_num]

        raw_figures = _extract_raster(doc, page, figures_dir, page_num, dpi)
        if not raw_figures:
            raw_figures = _extract_vector_fallback(page, figures_dir, page_num, dpi)

        page_idx = idx_counter.get(page_num, 0)
        for fig in raw_figures:
            bbox = fig["_bbox"]
            figure_id, caption = _find_caption(page, bbox)
            if figure_id is None:
                figure_id = f"p{page_num + 1}i{page_idx}"
            ext = fig["_ext"]
            img_filename = f"figure_{figure_id}.{ext}"
            img_path = figures_dir / img_filename

            if "_data" in fig:
                img_path.write_bytes(fig["_data"])
            else:
                fig["_pixmap"].save(str(img_path))

            results.append({
                "figure_id": figure_id,
                "image_path": f"figures/{img_filename}",
                "caption": caption or "",
                "page": page_num + 1,
            })
            page_idx += 1
        idx_counter[page_num] = page_idx

    doc.close()
    return results


def write_figures_json(figures: list[dict], output_dir: Path) -> None:
    """Write figures.json to output_dir."""
    out = output_dir / "figures.json"
    out.write_text(json.dumps(figures, indent=2, ensure_ascii=False))
