"""Detect and crop consistent browser chrome from screenshot folders.

Compares pixel variance across a sample of images. Regions that are
identical across all screenshots (browser UI, OS panels, scrollbars)
have near-zero variance and get cropped out before OCR.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def detect_content_bounds(
    image_files: list[Path],
    sample_size: int = 8,
    std_threshold: float = 15.0,
    min_content_ratio: float = 0.95,
) -> tuple[int, int, int, int] | None:
    """Detect static browser chrome borders and return content crop box.

    Samples images, computes per-pixel std across samples. Rows/columns
    with low std are chrome. Returns (left, top, right, bottom) suitable
    for PIL crop(), or None if no significant chrome detected.
    """
    if len(image_files) < 3:
        return None

    indices = _sample_indices(len(image_files), sample_size)
    arrays = []
    for i in indices:
        img = Image.open(image_files[i]).convert("RGB")
        arrays.append(np.array(img))

    # All images must share dimensions
    shape = arrays[0].shape
    if any(a.shape != shape for a in arrays[1:]):
        return None

    stack = np.stack(arrays, axis=0)  # (N, H, W, 3)
    std_map = stack.std(axis=0).mean(axis=2)  # (H, W)

    h, w = std_map.shape
    row_std = std_map.mean(axis=1)  # (H,)
    col_std = std_map.mean(axis=0)  # (W,)

    top = _find_edge(row_std, std_threshold)
    bottom = _find_edge(row_std, std_threshold, from_end=True) + 1
    left = _find_edge(col_std, std_threshold)
    right = _find_edge(col_std, std_threshold, from_end=True) + 1

    # Degenerate bounds — detection failed
    if top >= bottom or left >= right:
        return None

    content_area = (bottom - top) * (right - left)
    total_area = h * w

    # Content fills nearly the whole image — no meaningful chrome
    if content_area > min_content_ratio * total_area:
        return None

    # Content too small — detection likely wrong
    if content_area < 0.5 * total_area:
        return None

    logger.info(
        "Chrome detected: crop (%d, %d, %d, %d) from %dx%d",
        left, top, right, bottom, w, h,
    )
    return (left, top, right, bottom)


def crop_image(image: Image.Image, bounds: tuple[int, int, int, int]) -> Image.Image:
    """Crop image to content bounds (left, top, right, bottom)."""
    return image.crop(bounds)


def detect_column_bounds(
    image_files: list[Path],
    content_bounds: tuple[int, int, int, int] | None = None,
    *,
    sample_size: int = 8,
    std_threshold: float = 8.0,
    min_col_width: int = 100,
    min_gutter_width: int = 20,
) -> list[tuple[int, int]]:
    """Detect vertical column boundaries in a set of screenshot pages.

    Samples pages, crops to content_bounds if given, computes per-x-column
    variance across samples, and identifies maximal runs of high-variance
    columns (text) separated by low-variance gaps (gutters).

    Returns a list of (left, right) x-ranges in the content coordinate
    space. For single-column content, returns one tuple spanning the full
    content width. For fewer than 3 images, mixed dimensions, or no
    detectable text, also returns a single full-width tuple.
    """
    full_width_fallback = _full_width_column(image_files, content_bounds)
    if len(image_files) < 3:
        return full_width_fallback

    indices = _sample_indices(len(image_files), sample_size)
    arrays = []
    for i in indices:
        img = Image.open(image_files[i]).convert("RGB")
        arr = np.array(img)
        if content_bounds:
            left, top, right, bottom = content_bounds
            arr = arr[top:bottom, left:right]
        arrays.append(arr)

    shape = arrays[0].shape
    if any(a.shape != shape for a in arrays[1:]):
        return full_width_fallback

    stack = np.stack(arrays, axis=0)  # (N, H, W, 3)
    # Per-pixel std across samples, averaged over RGB channels, then
    # averaged over rows → one variance value per x-column.
    col_std = stack.std(axis=0).mean(axis=2).mean(axis=0)  # (W,)

    width = len(col_std)
    is_text = col_std > std_threshold

    # Maximal runs of text columns
    runs: list[tuple[int, int]] = []
    in_run = False
    run_start = 0
    for x in range(width):
        if is_text[x] and not in_run:
            in_run = True
            run_start = x
        elif not is_text[x] and in_run:
            in_run = False
            runs.append((run_start, x))
    if in_run:
        runs.append((run_start, width))

    # Merge runs separated by gutters smaller than min_gutter_width
    merged: list[tuple[int, int]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] < min_gutter_width:
            merged[-1] = (merged[-1][0], run[1])
        else:
            merged.append(run)

    # Drop runs too narrow to be real columns
    columns = [(l, r) for l, r in merged if r - l >= min_col_width]
    if not columns:
        return [(0, width)]

    logger.info(
        "Columns detected: %s (content width %d)",
        columns, width,
    )
    return columns


def split_image_into_columns(
    image: Image.Image,
    columns: list[tuple[int, int]],
) -> list[Image.Image]:
    """Split an image vertically into per-column crops.

    Each tuple in `columns` is an (left, right) x-range in the image's
    coordinate space. Returns one PIL image per column, full height.
    """
    return [image.crop((left, 0, right, image.height)) for left, right in columns]


def _full_width_column(
    image_files: list[Path],
    content_bounds: tuple[int, int, int, int] | None,
) -> list[tuple[int, int]]:
    """Fallback: return a single column spanning the full content width."""
    if content_bounds:
        return [(0, content_bounds[2] - content_bounds[0])]
    if not image_files:
        return [(0, 0)]
    with Image.open(image_files[0]) as img:
        return [(0, img.size[0])]


def _sample_indices(total: int, sample_size: int) -> list[int]:
    """Return evenly-spaced indices into a list of length total."""
    n = min(sample_size, total)
    return list(np.linspace(0, total - 1, n, dtype=int))


def _find_edge(profile: np.ndarray, threshold: float, from_end: bool = False) -> int:
    """Find first index exceeding threshold, scanning from start or end."""
    indices = range(len(profile))
    if from_end:
        indices = reversed(indices)
    for i in indices:
        if profile[i] > threshold:
            return i
    return 0 if not from_end else len(profile) - 1
