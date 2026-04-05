"""Extract text from images/scanned PDFs using Surya OCR."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image
from surya.recognition import DetectionPredictor, FoundationPredictor, RecognitionPredictor

from doc2md.models import Page

logger = logging.getLogger(__name__)

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


def detect_only(image: Image.Image) -> int:
    """Run detection only, return number of bounding boxes found."""
    _, det_predictor = _get_predictors()
    results = det_predictor([image])
    return len(results[0].bboxes)


def ocr_image(image_path: Path) -> str:
    """Run OCR on a single image file, return extracted text."""
    rec_predictor, det_predictor = _get_predictors()
    image = Image.open(image_path)
    predictions = rec_predictor([image], det_predictor=det_predictor)
    lines = [line.text for line in predictions[0].text_lines]
    return "\n".join(lines)


def extract_screenshots(folder: Path) -> list[Page]:
    """Extract text from all images in a folder, sorted by filename."""
    image_exts = {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"}
    image_files = sorted(
        f for f in folder.iterdir()
        if f.suffix.lower() in image_exts
    )
    pages = []
    for img_path in image_files:
        try:
            text = ocr_image(img_path)
            pages.append(Page(
                source_path=img_path,
                raw_text=text,
                extraction_method="surya",
            ))
        except Exception:
            logger.warning("OCR failed for %s", img_path)
            pages.append(Page(
                source_path=img_path,
                raw_text="",
                extraction_method="surya_failed",
            ))
    return pages
