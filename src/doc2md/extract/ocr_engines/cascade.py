"""Cascade OCR engine with per-page quality gating.

Runs a primary engine on all items, then re-runs only the items whose
quality check failed through the next engine, and so on. The final
stage in a cascade is typically given a `None` quality check, meaning
its output is accepted unconditionally.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PIL import Image

from doc2md.extract.ocr_engines.base import OcrEngine, OcrResult

QualityCheck = Callable[[OcrResult], bool]


def default_quality_check(
    result: OcrResult,
    *,
    min_confidence: float = 0.60,
    min_lines: int = 3,
    max_non_printable_ratio: float = 0.30,
) -> bool:
    """Default per-page quality gate.

    Returns True if the result looks good enough to keep. Rejects on:
    - mean confidence below `min_confidence`
    - fewer than `min_lines` recognized lines
    - more than `max_non_printable_ratio` non-printable characters in the text
    """
    if result.confidence < min_confidence:
        return False
    if result.line_count < min_lines:
        return False
    text = result.page.raw_text
    if text:
        non_printable = sum(
            1 for c in text if not c.isprintable() and c not in "\n\r\t"
        )
        if non_printable / len(text) > max_non_printable_ratio:
            return False
    return True


class CascadeEngine:
    """Run multiple OCR engines in order with per-page fallback.

    Construct with a list of `(engine, quality_check)` stages. The
    quality_check of the last stage may be `None`, meaning its output is
    accepted unconditionally. Any earlier stage with `quality_check=None`
    will short-circuit the cascade at that point.
    """

    name = "cascade"

    def __init__(self, stages: list[tuple[OcrEngine, QualityCheck | None]]):
        if not stages:
            raise ValueError("CascadeEngine requires at least one stage")
        self.stages = stages

    def ocr_batch(
        self,
        items: list[tuple[Image.Image, Path]],
        *,
        auto_number: bool = False,
    ) -> list[OcrResult]:
        if not items:
            return []

        # Stage 0: run primary engine on all items (no page numbering yet)
        engine, _check = self.stages[0]
        results = engine.ocr_batch(items, auto_number=False)

        # Walk remaining stages, re-running only items whose previous
        # stage's check said "not good enough".
        for stage_idx in range(1, len(self.stages)):
            prev_check = self.stages[stage_idx - 1][1]
            if prev_check is None:
                # Previous stage accepts unconditionally → no fallback
                break

            failed_indices = [
                i for i, r in enumerate(results) if not prev_check(r)
            ]
            if not failed_indices:
                break

            fallback_engine, _ = self.stages[stage_idx]
            fallback_items = [items[i] for i in failed_indices]
            fallback_results = fallback_engine.ocr_batch(
                fallback_items, auto_number=False
            )
            for j, i in enumerate(failed_indices):
                results[i] = fallback_results[j]

        # Apply page numbering at the very end so it's sequential across
        # whichever engine produced each page.
        if auto_number:
            for n, r in enumerate(results, start=1):
                r.page.page_number = n

        return results


def build_default_cascade(
    folder: Path | None = None,
    *,
    columns: list[tuple[int, int]] | None = None,
    lang: str = "eng",
    min_confidence: float = 0.60,
) -> CascadeEngine:
    """Convenience factory: build a cascade of Tesseract → Apple Vision → Surya.

    Column preprocessing behavior:
    - If `columns` is given, use it directly.
    - Else if `folder` is given, detect columns from the folder's images
      (and chrome bounds).
    - Else no column preprocessing (e.g. Libby spreads where each split
      half is already a single column).

    Only stages whose Python dependency is importable are included. Surya
    is always present as the final unconditional fallback.
    """
    from doc2md.extract.ocr_engines.surya import SuryaEngine

    if columns is None and folder is not None:
        from doc2md.extract.chrome_cropper import (
            detect_column_bounds,
            detect_content_bounds,
        )
        from doc2md.extract.ocr_extract import _get_image_files

        image_files = _get_image_files(folder)
        content_bounds = detect_content_bounds(image_files)
        columns = detect_column_bounds(image_files, content_bounds=content_bounds)

    stages: list[tuple[OcrEngine, QualityCheck | None]] = []

    def check(r: OcrResult) -> bool:
        return default_quality_check(r, min_confidence=min_confidence)

    if _is_importable("pytesseract"):
        from doc2md.extract.ocr_engines.tesseract import TesseractEngine
        stages.append((TesseractEngine(columns=columns, lang=lang), check))

    if _is_importable("ocrmac"):
        from doc2md.extract.ocr_engines.apple_vision import AppleVisionEngine
        stages.append((AppleVisionEngine(columns=columns), check))

    # Surya is always the final stage, accepted unconditionally.
    stages.append((SuryaEngine(), None))

    return CascadeEngine(stages)


def _is_importable(module_name: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(module_name) is not None
