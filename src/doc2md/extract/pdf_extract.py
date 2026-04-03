"""Extract text from digital PDFs using PyMuPDF."""

from __future__ import annotations

from pathlib import Path

import fitz

from doc2md.models import Page


def extract_pages(pdf_path: Path) -> list[Page]:
    """Extract text from each page of a digital PDF."""
    pages = []
    doc = fitz.open(pdf_path)
    try:
        for i in range(len(doc)):
            text = doc[i].get_text()
            pages.append(Page(
                source_path=pdf_path,
                raw_text=text,
                extraction_method="pymupdf",
                page_number=i + 1,
            ))
    finally:
        doc.close()
    return pages
