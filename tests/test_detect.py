"""Tests for auto-detection of digital vs scanned PDFs."""

from pathlib import Path
from unittest.mock import patch

import fitz
import pytest

from doc2md.extract.detect import extract_auto, is_digital_pdf


@pytest.fixture
def digital_pdf(tmp_path):
    path = tmp_path / "digital.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "This is a digital PDF with plenty of readable text content. " * 5)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def empty_pdf(tmp_path):
    path = tmp_path / "empty.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(path)
    doc.close()
    return path


class TestIsDigitalPdf:
    def test_digital_pdf_detected(self, digital_pdf):
        assert is_digital_pdf(digital_pdf) is True

    def test_empty_pdf_not_digital(self, empty_pdf):
        assert is_digital_pdf(empty_pdf) is False

    def test_custom_min_chars(self, digital_pdf):
        assert is_digital_pdf(digital_pdf, min_chars=10000) is False


class TestExtractAuto:
    def test_uses_pymupdf_for_digital(self, digital_pdf):
        pages = extract_auto(digital_pdf)
        assert all(p.extraction_method == "pymupdf" for p in pages)

    @patch("doc2md.extract.ocr_extract.ocr_image")
    def test_uses_surya_for_scanned(self, mock_ocr, empty_pdf):
        mock_ocr.return_value = "OCR text"
        pages = extract_auto(empty_pdf)
        assert all(p.extraction_method == "surya" for p in pages)
        assert pages[0].raw_text == "OCR text"
