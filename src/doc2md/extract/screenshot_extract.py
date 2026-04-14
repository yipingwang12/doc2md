"""Screenshot format detection and Libby spread extraction.

Detects Libby two-page spreads and browser screenshots with consistent
chrome. Splits spreads into halves and delegates to shared batched OCR.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from doc2md.extract.chrome_cropper import detect_content_bounds
from doc2md.extract.ocr_extract import _get_image_files, _ocr_batched
from doc2md.models import Page


def is_libby_spread(folder: Path) -> bool:
    """Check if folder contains Libby-style landscape two-page spreads.

    All images must share the same dimensions. The content area (after
    cropping consistent chrome, if any) must be landscape (w > h * 1.5).
    Browser screenshots of single pages are rejected even if the raw
    window is landscape.
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
    bounds = detect_content_bounds(image_files)
    if bounds:
        w = bounds[2] - bounds[0]
        h = bounds[3] - bounds[1]
    return w > h * 1.5


def is_browser_screenshot(folder: Path) -> bool:
    """Check if folder contains browser screenshots with consistent chrome.

    Uniform dimensions + detected static borders = browser capture of
    an e-reader (e.g. Libby in a browser). These are ordered sequential
    captures, so dedup/reorder can be skipped.
    """
    image_files = _get_image_files(folder)
    if len(image_files) < 3:
        return False

    sizes = set()
    for f in image_files:
        with Image.open(f) as img:
            sizes.add(img.size)
        if len(sizes) > 1:
            return False

    return detect_content_bounds(image_files) is not None


def extract_screenshot_spread(folder: Path) -> list[Page]:
    """Extract text from Libby two-page spread screenshots.

    Splits each image at midpoint, batches halves for OCR,
    skips image-only pages, returns pages in reading order.
    """
    image_files = _get_image_files(folder)
    halves = _split_all(image_files)
    return _ocr_batched(halves, auto_number=True)


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
