"""Tests for doc2md.papers.figure_extractor."""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from doc2md.papers.figure_extractor import (
    _caption_figure_id,
    extract_figures_from_pdf,
    write_figures_json,
)


# --- Unit tests for _caption_figure_id ---

def test_caption_figure_id_standard():
    assert _caption_figure_id("Figure 2A") == "2A"


def test_caption_figure_id_abbreviated():
    assert _caption_figure_id("Fig. S1B") == "S1B"


def test_caption_figure_id_not_caption():
    assert _caption_figure_id("some body text") is None


def test_caption_figure_id_case_insensitive():
    assert _caption_figure_id("FIGURE 3") == "3"


def test_caption_figure_id_lowercase():
    assert _caption_figure_id("figure 4C blah blah") == "4C"


# --- Helpers to create minimal PDFs ---

def _red_pixmap(w: int, h: int) -> fitz.Pixmap:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h))
    pix.set_rect(fitz.IRect(0, 0, w, h), (200, 50, 50))
    return pix


def _make_pdf_with_image(tmp_path: Path) -> Path:
    """Single image + caption."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(fitz.Rect(72, 100, 272, 300), pixmap=_red_pixmap(200, 200))
    page.insert_text((72, 320), "Figure 1A. Red square test image.", fontsize=10)
    pdf_path = tmp_path / "test_figures.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _pixmap(w: int, h: int, color: tuple) -> fitz.Pixmap:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h))
    pix.set_rect(fitz.IRect(0, 0, w, h), color)
    return pix


def _make_pdf_duplicate_figure(tmp_path: Path) -> Path:
    """Two differently-colored 200x200 images side by side; both within caption range.

    Different colors → different xrefs → current code produces two 'Figure 2' entries.
    After the fix, only one should appear.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(fitz.Rect(50, 100, 250, 300), pixmap=_pixmap(200, 200, (200, 50, 50)))
    page.insert_image(fitz.Rect(270, 100, 470, 300), pixmap=_pixmap(200, 200, (50, 200, 50)))
    page.insert_text((50, 320), "Figure 2. Two panels.", fontsize=10)
    pdf_path = tmp_path / "test_dup.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _make_pdf_captioned_plus_subpanel(tmp_path: Path) -> Path:
    """200x200 subpanel at top (caption too far) + 300x250 captioned figure below.

    Current code assigns a fallback ID to the subpanel; after the fix it is dropped.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(fitz.Rect(50, 50, 250, 250), pixmap=_pixmap(200, 200, (50, 50, 200)))
    page.insert_image(fitz.Rect(50, 400, 350, 620), pixmap=_pixmap(300, 250, (200, 50, 50)))
    page.insert_text((50, 660), "Figure 3. Main figure.", fontsize=10)
    pdf_path = tmp_path / "test_subpanel.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _make_pdf_all_unlabeled(tmp_path: Path) -> Path:
    """Page with two images, no caption — both should get fallback IDs."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(fitz.Rect(72, 100, 272, 300), pixmap=_red_pixmap(200, 200))
    page.insert_image(fitz.Rect(72, 350, 272, 550), pixmap=_red_pixmap(200, 200))
    pdf_path = tmp_path / "test_unlabeled.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


# --- Integration tests for extract_figures_from_pdf ---

def test_extract_figures_returns_list(tmp_path):
    pdf = _make_pdf_with_image(tmp_path)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    figures = extract_figures_from_pdf(pdf, [], output_dir)
    assert isinstance(figures, list)


def test_extract_figures_finds_at_least_one(tmp_path):
    pdf = _make_pdf_with_image(tmp_path)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    figures = extract_figures_from_pdf(pdf, [], output_dir)
    assert len(figures) >= 1


def test_extract_figures_entry_schema(tmp_path):
    pdf = _make_pdf_with_image(tmp_path)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    figures = extract_figures_from_pdf(pdf, [], output_dir)
    fig = figures[0]
    assert "figure_id" in fig
    assert "image_path" in fig
    assert "caption" in fig
    assert "page" in fig


def test_extract_figures_image_file_written(tmp_path):
    pdf = _make_pdf_with_image(tmp_path)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    figures = extract_figures_from_pdf(pdf, [], output_dir)
    for fig in figures:
        img_path = output_dir / fig["image_path"]
        assert img_path.exists(), f"Expected {img_path} to exist"


def test_extract_figures_caption_detected(tmp_path):
    pdf = _make_pdf_with_image(tmp_path)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    figures = extract_figures_from_pdf(pdf, [], output_dir)
    assert any(fig["figure_id"] == "1A" for fig in figures)


def test_duplicate_figure_id_deduplicated(tmp_path):
    """Two images on same page with same caption → only one figure_id in output."""
    pdf = _make_pdf_duplicate_figure(tmp_path)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    figures = extract_figures_from_pdf(pdf, [], output_dir)
    ids = [f["figure_id"] for f in figures]
    assert ids.count("2") == 1, f"Expected exactly one Figure 2, got: {ids}"


def test_subpanel_dropped_when_captioned_figure_present(tmp_path):
    """Unlabeled small subpanel on a page with a captioned figure → dropped."""
    pdf = _make_pdf_captioned_plus_subpanel(tmp_path)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    figures = extract_figures_from_pdf(pdf, [], output_dir)
    ids = [f["figure_id"] for f in figures]
    assert "3" in ids
    assert not any(fid.startswith("p") for fid in ids), f"Fallback IDs leaked: {ids}"


def test_all_unlabeled_kept_with_fallback_ids(tmp_path):
    """Page with no captioned figures → unlabeled images kept with fallback IDs."""
    pdf = _make_pdf_all_unlabeled(tmp_path)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    figures = extract_figures_from_pdf(pdf, [], output_dir)
    assert len(figures) >= 1
    assert all(fid.startswith("p") for fid in [f["figure_id"] for f in figures])


# --- Tests for write_figures_json ---

def test_write_figures_json_creates_file(tmp_path):
    figures = [{"figure_id": "1", "image_path": "figures/figure_1.png", "caption": "", "page": 1}]
    write_figures_json(figures, tmp_path)
    assert (tmp_path / "figures.json").exists()


def test_write_figures_json_valid_json(tmp_path):
    figures = [
        {"figure_id": "2A", "image_path": "figures/figure_2A.png", "caption": "Figure 2A.", "page": 3},
    ]
    write_figures_json(figures, tmp_path)
    data = json.loads((tmp_path / "figures.json").read_text())
    assert isinstance(data, list)
    assert data[0]["figure_id"] == "2A"


def test_write_figures_json_empty(tmp_path):
    write_figures_json([], tmp_path)
    data = json.loads((tmp_path / "figures.json").read_text())
    assert data == []
