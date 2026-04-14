"""Extract text from images/scanned PDFs using Surya OCR."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image
from surya.recognition import DetectionPredictor, FoundationPredictor, RecognitionPredictor

from doc2md.extract.chrome_cropper import crop_image, detect_content_bounds
from doc2md.models import Page

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


def _ocr_batched(
    items: list[tuple[Image.Image, Path]],
    *,
    auto_number: bool = False,
) -> list[Page]:
    """Run batched OCR with image-only page skipping.

    Each item is (pil_image, source_path). Pages with fewer than
    MIN_BBOXES detected text regions get empty text (image-only).
    When auto_number=True, pages get sequential page_number values.
    """
    rec_predictor, det_predictor = _get_predictors()
    pages: list[Page] = []
    page_num = 1

    for batch_start in range(0, len(items), BATCH_SIZE):
        batch = items[batch_start:batch_start + BATCH_SIZE]
        images = [item[0] for item in batch]
        sources = [item[1] for item in batch]

        # Detection pass to find image-only pages
        det_results = det_predictor(images)
        to_recognize = []
        to_recognize_idx = []
        for i, det in enumerate(det_results):
            if len(det.bboxes) >= MIN_BBOXES:
                to_recognize.append(images[i])
                to_recognize_idx.append(i)

        # Recognition pass on text pages only
        rec_texts: dict[int, str] = {}
        if to_recognize:
            rec_results = rec_predictor(to_recognize, det_predictor=det_predictor)
            for j, idx in enumerate(to_recognize_idx):
                lines = [line.text for line in rec_results[j].text_lines]
                rec_texts[idx] = "\n".join(lines)

        for i in range(len(batch)):
            text = rec_texts.get(i, "")
            pages.append(Page(
                source_path=sources[i],
                raw_text=text,
                extraction_method="surya",
                page_number=page_num if auto_number else None,
            ))
            if auto_number:
                page_num += 1

    return pages


def extract_screenshots(folder: Path, *, auto_number: bool = False) -> list[Page]:
    """Extract text from all images in a folder via batched OCR.

    Detects and crops browser chrome before OCR. Skips image-only pages.
    When auto_number=True, pages get sequential page numbers.
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

    pages = _ocr_batched(items, auto_number=auto_number)
    pages.extend(failed)
    pages.sort(key=lambda p: p.source_path)
    return pages
