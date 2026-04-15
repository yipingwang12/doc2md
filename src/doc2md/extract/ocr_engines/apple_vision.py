"""Apple Vision OCR engine adapter (macOS only).

Wraps `ocrmac` (thin Python binding around `VNRecognizeTextRequest`)
behind the `OcrEngine` protocol. On Apple Silicon, Apple Vision runs on
the Neural Engine, which is dramatically faster than CPU Surya and does
not compete for the GPU. Supports per-engine column preprocessing.

`ocrmac` is loaded lazily so doc2md remains importable on non-macOS
systems and in environments without the dependency installed. If
`ocrmac` is missing, `ocr_batch` raises `RuntimeError` with install
instructions.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from doc2md.extract.ocr_engines.base import OcrResult
from doc2md.models import Page


class AppleVisionEngine:
    """Apple Vision (`VNRecognizeTextRequest`) backed OCR engine."""

    name = "apple_vision"

    def __init__(self, columns: list[tuple[int, int]] | None = None):
        self.columns = columns

    def ocr_batch(
        self,
        items: list[tuple[Image.Image, Path]],
        *,
        auto_number: bool = False,
    ) -> list[OcrResult]:
        ocrmac = self._load_ocrmac()

        results: list[OcrResult] = []
        for idx, (image, source_path) in enumerate(items):
            if self.columns and len(self.columns) > 1:
                text, mean_conf, line_count = self._ocr_with_columns(image, ocrmac)
            else:
                text, mean_conf, line_count = self._ocr_single(image, ocrmac)

            page = Page(
                source_path=source_path,
                raw_text=text,
                extraction_method="apple_vision",
                page_number=(idx + 1) if auto_number else None,
            )
            results.append(OcrResult(page=page, confidence=mean_conf, line_count=line_count))

        return results

    def _ocr_with_columns(self, image: Image.Image, ocrmac):
        text_parts: list[str] = []
        all_confs: list[float] = []
        for left, right in self.columns:
            col_img = image.crop((left, 0, right, image.height))
            col_text, col_confs = self._extract(col_img, ocrmac)
            if col_text:
                text_parts.append(col_text)
            all_confs.extend(col_confs)

        combined = "\n".join(text_parts)
        mean_conf = sum(all_confs) / len(all_confs) if all_confs else 0.0
        return combined, mean_conf, len(all_confs)

    def _ocr_single(self, image: Image.Image, ocrmac):
        text, confs = self._extract(image, ocrmac)
        mean_conf = sum(confs) / len(confs) if confs else 0.0
        return text, mean_conf, len(confs)

    def _extract(self, image: Image.Image, ocrmac):
        """Call ocrmac on a single image and return (text, per_line_confs).

        ocrmac's `OCR(image).recognize()` returns a list of
        `(text, confidence, bbox)` tuples sorted by reading order.
        """
        annotations = ocrmac.OCR(image).recognize()
        lines: list[str] = []
        confs: list[float] = []
        for item in annotations:
            # Defensive unpacking: accept 3-tuples (text, conf, bbox) or
            # longer shapes if future ocrmac versions add fields.
            text = item[0]
            conf = float(item[1]) if len(item) > 1 else 0.0
            if not text:
                continue
            lines.append(text)
            confs.append(conf)
        return "\n".join(lines), confs

    @staticmethod
    def _load_ocrmac():
        try:
            from ocrmac import ocrmac
        except ImportError as e:
            raise RuntimeError(
                "AppleVisionEngine requires `ocrmac`. Install with "
                "`pip install ocrmac`. Only available on macOS."
            ) from e
        return ocrmac
