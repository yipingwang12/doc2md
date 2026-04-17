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


# --- Helper to create a minimal PDF with an embedded image ---

def _make_pdf_with_image(tmp_path: Path) -> Path:
    """Create a PDF with one embedded raster image and a caption."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    # Create a small red pixmap (200x200) and insert it
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200))
    pix.set_rect(fitz.IRect(0, 0, 200, 200), (200, 50, 50))

    img_rect = fitz.Rect(72, 100, 272, 300)
    page.insert_image(img_rect, pixmap=pix)

    # Insert caption below the image
    page.insert_text((72, 320), "Figure 1A. Red square test image.", fontsize=10)

    pdf_path = tmp_path / "test_figures.pdf"
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
