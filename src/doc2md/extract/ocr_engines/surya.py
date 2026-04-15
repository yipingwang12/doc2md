"""Surya OCR engine adapter.

Wraps the existing Surya detection + recognition predictors behind the
`OcrEngine` protocol. Batching, image-only page skipping, and the
BATCH_SIZE / MIN_BBOXES thresholds live in `ocr_extract.py` and are
imported here so there's a single source of truth.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from doc2md.extract.ocr_engines.base import OcrResult
from doc2md.models import Page


class SuryaEngine:
    """Surya-backed OCR engine."""

    name = "surya"

    def ocr_batch(
        self,
        items: list[tuple[Image.Image, Path]],
        *,
        auto_number: bool = False,
    ) -> list[OcrResult]:
        # Imported lazily to avoid a circular import with ocr_extract,
        # which re-exports SuryaEngine via ocr_engines.__init__.
        from doc2md.extract.ocr_extract import (
            BATCH_SIZE,
            MIN_BBOXES,
            _get_predictors,
        )

        rec_predictor, det_predictor = _get_predictors()
        results: list[OcrResult] = []
        page_num = 1

        for batch_start in range(0, len(items), BATCH_SIZE):
            batch = items[batch_start:batch_start + BATCH_SIZE]
            images = [item[0] for item in batch]
            sources = [item[1] for item in batch]

            # Detection pass identifies pages with enough text regions
            # to be worth recognizing.
            det_results = det_predictor(images)
            to_recognize = []
            to_recognize_idx = []
            for i, det in enumerate(det_results):
                if len(det.bboxes) >= MIN_BBOXES:
                    to_recognize.append(images[i])
                    to_recognize_idx.append(i)

            # Recognition pass returns text + per-line confidence
            rec_data: dict[int, tuple[str, float, int]] = {}
            if to_recognize:
                rec_results = rec_predictor(to_recognize, det_predictor=det_predictor)
                for j, idx in enumerate(to_recognize_idx):
                    text_lines = rec_results[j].text_lines
                    lines = [line.text for line in text_lines]
                    text = "\n".join(lines)
                    confidences = [
                        getattr(line, "confidence", 0.0) or 0.0
                        for line in text_lines
                    ]
                    mean_conf = (
                        sum(confidences) / len(confidences)
                        if confidences
                        else 0.0
                    )
                    rec_data[idx] = (text, mean_conf, len(text_lines))

            for i in range(len(batch)):
                text, conf, line_count = rec_data.get(i, ("", 0.0, 0))
                page = Page(
                    source_path=sources[i],
                    raw_text=text,
                    extraction_method="surya",
                    page_number=page_num if auto_number else None,
                )
                results.append(OcrResult(page=page, confidence=conf, line_count=line_count))
                if auto_number:
                    page_num += 1

        return results
