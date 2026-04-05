"""Extract text from Libby two-page spread screenshots.

Splits each screenshot into left/right halves, batches through Surya OCR,
and skips image-only pages with few detected bounding boxes.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from doc2md.extract.ocr_extract import _get_predictors, detect_only
from doc2md.models import Page

logger = logging.getLogger(__name__)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"}
MIN_BBOXES = 3
BATCH_SIZE = 16


def is_libby_spread(folder: Path) -> bool:
    """Check if folder contains Libby-style landscape two-page spreads.

    All images must share the same dimensions and be landscape (w > h * 1.5).
    """
    image_files = _get_image_files(folder)
    if not image_files:
        return False

    sizes = set()
    for f in image_files:
        with Image.open(f) as img:
            sizes.add(img.size)
        if len(sizes) > 1:
            return False

    w, h = sizes.pop()
    return w > h * 1.5


def extract_screenshot_spread(folder: Path) -> list[Page]:
    """Extract text from Libby two-page spread screenshots.

    Splits each image at midpoint, batches halves for OCR,
    skips image-only pages, returns pages in reading order.
    """
    image_files = _get_image_files(folder)
    halves = _split_all(image_files)
    return _ocr_batched(halves)


def _get_image_files(folder: Path) -> list[Path]:
    """Return image files sorted by filename."""
    return sorted(
        f for f in folder.iterdir()
        if f.suffix.lower() in IMAGE_EXTS
    )


def _split_image(image_path: Path) -> list[tuple[Image.Image, Path]]:
    """Split a screenshot into left and right halves."""
    img = Image.open(image_path)
    mid = img.width // 2
    left = img.crop((0, 0, mid, img.height))
    right = img.crop((mid, 0, img.width, img.height))
    return [(left, image_path), (right, image_path)]


def _split_all(image_files: list[Path]) -> list[tuple[Image.Image, Path]]:
    """Split all screenshots, returning (half_image, source_path) pairs in order."""
    halves = []
    for f in image_files:
        halves.extend(_split_image(f))
    return halves


def _ocr_batched(halves: list[tuple[Image.Image, Path]]) -> list[Page]:
    """Run detection + recognition on half-page images in batches."""
    rec_predictor, det_predictor = _get_predictors()
    pages = []
    page_num = 1

    for batch_start in range(0, len(halves), BATCH_SIZE):
        batch = halves[batch_start:batch_start + BATCH_SIZE]
        images = [h[0] for h in batch]
        sources = [h[1] for h in batch]

        # Detection pass to find image-only pages
        det_results = det_predictor(images)
        to_recognize = []
        to_recognize_idx = []
        for i, det in enumerate(det_results):
            if len(det.bboxes) >= MIN_BBOXES:
                to_recognize.append(images[i])
                to_recognize_idx.append(i)

        # Recognition pass on text pages only
        rec_texts = {}
        if to_recognize:
            rec_results = rec_predictor(to_recognize, det_predictor=det_predictor)
            for j, idx in enumerate(to_recognize_idx):
                lines = [line.text for line in rec_results[j].text_lines]
                rec_texts[idx] = "\n".join(lines)

        # Build Page objects
        for i in range(len(batch)):
            text = rec_texts.get(i, "")
            pages.append(Page(
                source_path=sources[i],
                raw_text=text,
                extraction_method="surya",
                page_number=page_num,
            ))
            page_num += 1

    return pages
