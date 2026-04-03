"""Auto-detect whether a PDF is digital or scanned, choose extraction method."""

from __future__ import annotations

from pathlib import Path

import fitz

from doc2md.models import Page


def is_digital_pdf(pdf_path: Path, min_chars: int = 100, gibberish_threshold: float = 0.3) -> bool:
    """Check if a PDF has extractable digital text."""
    doc = fitz.open(pdf_path)
    try:
        sample_pages = min(3, len(doc))
        total_text = ""
        for i in range(sample_pages):
            total_text += doc[i].get_text()

        if len(total_text.strip()) < min_chars:
            return False

        non_printable = sum(1 for c in total_text if not c.isprintable() and c not in "\n\r\t")
        if len(total_text) > 0 and non_printable / len(total_text) > gibberish_threshold:
            return False

        return True
    finally:
        doc.close()


def extract_auto(pdf_path: Path, min_chars: int = 100, gibberish_threshold: float = 0.3) -> list[Page]:
    """Extract pages from a PDF, auto-detecting the best method."""
    if is_digital_pdf(pdf_path, min_chars, gibberish_threshold):
        from doc2md.extract.pdf_extract import extract_pages
        return extract_pages(pdf_path)
    else:
        from doc2md.extract.ocr_extract import ocr_image
        doc = fitz.open(pdf_path)
        pages = []
        try:
            for i in range(len(doc)):
                pix = doc[i].get_pixmap()
                from PIL import Image
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                from io import BytesIO
                buf = BytesIO()
                img.save(buf, format="PNG")
                buf.seek(0)

                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp.write(buf.read())
                    tmp_path = Path(tmp.name)
                try:
                    text = ocr_image(tmp_path)
                finally:
                    tmp_path.unlink(missing_ok=True)

                pages.append(Page(
                    source_path=pdf_path,
                    raw_text=text,
                    extraction_method="surya",
                    page_number=i + 1,
                ))
        finally:
            doc.close()
        return pages
