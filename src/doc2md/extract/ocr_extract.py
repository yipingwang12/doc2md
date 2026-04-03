"""Extract text from images/scanned PDFs using Surya OCR."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image
from surya.recognition import RecognitionPredictor

from doc2md.models import Page

logger = logging.getLogger(__name__)

_predictor: RecognitionPredictor | None = None


def _get_predictor() -> RecognitionPredictor:
    global _predictor
    if _predictor is None:
        _predictor = RecognitionPredictor()
    return _predictor


def ocr_image(image_path: Path) -> str:
    """Run OCR on a single image file, return extracted text."""
    predictor = _get_predictor()
    image = Image.open(image_path)
    predictions = predictor([image])
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
