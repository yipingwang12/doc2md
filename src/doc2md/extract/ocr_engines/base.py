"""OCR engine protocol and result types.

Every engine (Surya, Tesseract, Apple Vision, ...) implements the same
`ocr_batch()` interface so `extract_screenshots()` can stay agnostic of
which engine is running.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from PIL import Image

from doc2md.models import Page


@dataclass
class OcrResult:
    """A single page's OCR output plus a quality signal.

    `confidence` is the mean per-line confidence on an engine-specific
    0..1 scale — it's comparable across pages from the same engine but
    not yet calibrated across engines.
    """

    page: Page
    confidence: float
    line_count: int


@runtime_checkable
class OcrEngine(Protocol):
    """Protocol for a pluggable OCR engine.

    Implementations process a batch of (image, source_path) tuples and
    return one `OcrResult` per item in the same order. When
    `auto_number` is True the engine assigns sequential `page_number`
    values starting at 1.
    """

    name: str

    def ocr_batch(
        self,
        items: list[tuple[Image.Image, Path]],
        *,
        auto_number: bool = False,
    ) -> list[OcrResult]:
        ...
