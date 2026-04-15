"""Tesseract OCR engine adapter.

Wraps pytesseract behind the `OcrEngine` protocol. Supports per-engine
column preprocessing: when constructed with a non-trivial `columns`
argument, each input image is cropped into columns and OCR'd
separately (with --psm 6, single block of text) before the per-line
results are concatenated.

Tesseract is loaded lazily on first use so the package doesn't become a
hard dependency of doc2md. If pytesseract or the tesseract binary is
missing, `ocr_batch` raises a `RuntimeError` with install instructions.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from doc2md.extract.ocr_engines.base import OcrResult
from doc2md.models import Page


class TesseractEngine:
    """Tesseract-backed OCR engine."""

    name = "tesseract"

    def __init__(
        self,
        columns: list[tuple[int, int]] | None = None,
        lang: str = "eng",
    ):
        self.columns = columns
        self.lang = lang

    def ocr_batch(
        self,
        items: list[tuple[Image.Image, Path]],
        *,
        auto_number: bool = False,
    ) -> list[OcrResult]:
        pytesseract = self._load_pytesseract()

        results: list[OcrResult] = []
        for idx, (image, source_path) in enumerate(items):
            if self.columns and len(self.columns) > 1:
                text, mean_conf, line_count = self._ocr_with_columns(image, pytesseract)
            else:
                text, mean_conf, line_count = self._ocr_single(image, pytesseract)

            page = Page(
                source_path=source_path,
                raw_text=text,
                extraction_method="tesseract",
                page_number=(idx + 1) if auto_number else None,
            )
            results.append(OcrResult(page=page, confidence=mean_conf, line_count=line_count))

        return results

    def _ocr_with_columns(self, image: Image.Image, pytesseract):
        text_parts: list[str] = []
        all_line_confs: list[float] = []
        for left, right in self.columns:
            col_img = image.crop((left, 0, right, image.height))
            col_text, line_confs = self._extract_text_and_line_confs(col_img, pytesseract)
            if col_text:
                text_parts.append(col_text)
            all_line_confs.extend(line_confs)

        combined = "\n".join(text_parts)
        mean_conf = (
            sum(all_line_confs) / len(all_line_confs)
            if all_line_confs
            else 0.0
        )
        return combined, mean_conf, len(all_line_confs)

    def _ocr_single(self, image: Image.Image, pytesseract):
        text, line_confs = self._extract_text_and_line_confs(image, pytesseract)
        mean_conf = sum(line_confs) / len(line_confs) if line_confs else 0.0
        return text, mean_conf, len(line_confs)

    def _extract_text_and_line_confs(self, image: Image.Image, pytesseract):
        """Run Tesseract on a single image and return (text, line_confs).

        Groups words into lines by (block_num, par_num, line_num), computes
        per-line mean confidence normalized from 0-100 to 0-1, and filters
        out Tesseract's sentinel -1 confidences for undetected words.
        """
        data = pytesseract.image_to_data(
            image,
            lang=self.lang,
            config="--psm 6",
            output_type=pytesseract.Output.DICT,
        )

        lines: dict[tuple[int, int, int], list[tuple[str, float]]] = {}
        for i, word in enumerate(data["text"]):
            if not word or not word.strip():
                continue
            key = (
                data["block_num"][i],
                data["par_num"][i],
                data["line_num"][i],
            )
            # Tesseract confidence is 0-100 for real detections, -1 for
            # sentinels (e.g. whitespace). Skip the sentinels.
            conf_raw = float(data["conf"][i])
            if conf_raw < 0:
                continue
            lines.setdefault(key, []).append((word, conf_raw / 100.0))

        line_texts: list[str] = []
        line_confs: list[float] = []
        for key in sorted(lines.keys()):
            words = lines[key]
            text = " ".join(w for w, _ in words)
            if not text:
                continue
            line_texts.append(text)
            word_confs = [c for _, c in words]
            line_confs.append(sum(word_confs) / len(word_confs))

        return "\n".join(line_texts), line_confs

    @staticmethod
    def _load_pytesseract():
        try:
            import pytesseract
        except ImportError as e:
            raise RuntimeError(
                "TesseractEngine requires pytesseract. Install with "
                "`pip install pytesseract` and ensure the tesseract binary "
                "is on PATH (e.g. `brew install tesseract`)."
            ) from e
        return pytesseract
