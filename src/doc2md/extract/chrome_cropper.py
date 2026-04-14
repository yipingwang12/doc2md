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
