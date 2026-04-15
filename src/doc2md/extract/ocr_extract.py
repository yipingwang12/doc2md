"""Extract text from images/scanned PDFs using a pluggable OCR engine.

The default engine is `SuryaEngine`. `extract_screenshots()` accepts
an optional `engine` kwarg so callers can pass a different engine (or
a cascade of engines) without touching this module.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image
from surya.recognition import DetectionPredictor, FoundationPredictor, RecognitionPredictor

from doc2md.extract.chrome_cropper import crop_image, detect_content_bounds
from doc2md.models import Page

if TYPE_CHECKING:
    from doc2md.extract.ocr_engines.base import OcrEngine

logger = logging.getLogger(__name__)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"}
MIN_BBOXES = 3
BATCH_SIZE = 16

_foundation: FoundationPredictor | None = None
_det_predictor: DetectionPredictor | None = None
_rec_predictor: RecognitionPredictor | None = None


def _get_predictors() -> tuple[RecognitionPredictor, DetectionPredictor]:
    global _foundation, _det_predictor, _rec_predictor
    if _rec_predictor is None:
        _foundation = FoundationPredictor()
        _det_predictor = DetectionPredictor()
        _rec_predictor = RecognitionPredictor(_foundation)
    return _rec_predictor, _det_predictor


def _get_image_files(folder: Path) -> list[Path]:
    """Return image files sorted by filename."""
    return sorted(f for f in folder.iterdir() if f.suffix.lower() in IMAGE_EXTS)


def detect_only(image: Image.Image) -> int:
    """Run detection only, return number of bounding boxes found."""
    _, det_predictor = _get_predictors()
    results = det_predictor([image])
    return len(results[0].bboxes)


def _ocr_pil(image: Image.Image) -> str:
    """Run OCR on a PIL Image, return extracted text."""
    rec_predictor, det_predictor = _get_predictors()
    predictions = rec_predictor([image], det_predictor=det_predictor)
    lines = [line.text for line in predictions[0].text_lines]
    return "\n".join(lines)


def ocr_image(image_path: Path) -> str:
    """Run OCR on a single image file, return extracted text."""
    image = Image.open(image_path)
    return _ocr_pil(image)


def extract_screenshots(
    folder: Path,
    *,
    auto_number: bool = False,
    engine: "OcrEngine | None" = None,
) -> list[Page]:
    """Extract text from all images in a folder using an OCR engine.

    Detects and crops browser chrome before OCR. When `auto_number=True`,
    pages get sequential page numbers. Defaults to `SuryaEngine` if no
    engine is passed.
    """
    image_files = _get_image_files(folder)
    bounds = detect_content_bounds(image_files)

    items: list[tuple[Image.Image, Path]] = []
    failed: list[Page] = []
    for img_path in image_files:
        try:
            image = Image.open(img_path)
            if bounds:
                image = crop_image(image, bounds)
            items.append((image, img_path))
        except Exception:
            logger.warning("Failed to open %s", img_path)
            failed.append(Page(
                source_path=img_path,
                raw_text="",
                extraction_method="surya_failed",
            ))

    if engine is None:
        from doc2md.extract.ocr_engines import build_default_cascade
        engine = build_default_cascade(folder)

    results = engine.ocr_batch(items, auto_number=auto_number)
    pages = [r.page for r in results]
    pages.extend(failed)
    pages.sort(key=lambda p: p.source_path)
    return pages
