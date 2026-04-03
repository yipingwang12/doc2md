"""Tests for PyMuPDF PDF extraction."""

from pathlib import Path

import fitz
import pytest

from doc2md.extract.pdf_extract import extract_pages


@pytest.fixture
def sample_pdf(tmp_path):
    """Create a simple 2-page PDF with text."""
    path = tmp_path / "sample.pdf"
    doc = fitz.open()
    for i, text in enumerate(["Page one content here.", "Page two content here."]):
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()
    return path


class TestPdfExtract:
    def test_extracts_correct_page_count(self, sample_pdf):
        pages = extract_pages(sample_pdf)
        assert len(pages) == 2

    def test_extracts_text_content(self, sample_pdf):
        pages = extract_pages(sample_pdf)
        assert "Page one" in pages[0].raw_text
        assert "Page two" in pages[1].raw_text

    def test_sets_extraction_method(self, sample_pdf):
        pages = extract_pages(sample_pdf)
        assert all(p.extraction_method == "pymupdf" for p in pages)

    def test_sets_page_numbers(self, sample_pdf):
        pages = extract_pages(sample_pdf)
        assert pages[0].page_number == 1
        assert pages[1].page_number == 2

    def test_sets_source_path(self, sample_pdf):
        pages = extract_pages(sample_pdf)
        assert all(p.source_path == sample_pdf for p in pages)

    def test_computes_content_hash(self, sample_pdf):
        pages = extract_pages(sample_pdf)
        assert all(len(p.content_hash) == 64 for p in pages)

    def test_empty_pdf(self, tmp_path):
        path = tmp_path / "empty.pdf"
        doc = fitz.open()
        doc.new_page()
        doc.save(path)
        doc.close()
        pages = extract_pages(path)
        assert len(pages) == 1
        assert pages[0].raw_text.strip() == ""
