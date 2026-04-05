"""Extract text from digital PDFs using PyMuPDF."""

from __future__ import annotations

from pathlib import Path

import fitz

from doc2md.models import Page


def extract_pages(pdf_path: Path) -> list[Page]:
    """Extract text and block structure from each page of a digital PDF."""
    pages = []
    doc = fitz.open(pdf_path)
    try:
        for i in range(len(doc)):
            page = doc[i]
            text = page.get_text()
            page_dict = page.get_text("dict")
            pages.append(Page(
                source_path=pdf_path,
                raw_text=text,
                extraction_method="pymupdf",
                page_number=i + 1,
                block_dicts=page_dict.get("blocks", []),
                page_height=page_dict.get("height", 800.0),
            ))
    finally:
        doc.close()
    return pages
