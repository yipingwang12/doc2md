"""Tests for Surya OCR extraction (mocked)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from doc2md.extract.ocr_extract import extract_screenshots, ocr_image


class MockTextLine:
    def __init__(self, text):
        self.text = text


class MockPrediction:
    def __init__(self, lines):
        self.text_lines = [MockTextLine(l) for l in lines]


@pytest.fixture(autouse=True)
def reset_predictor():
    """Reset the global predictor between tests."""
    import doc2md.extract.ocr_extract as mod
    mod._foundation = None
    mod._det_predictor = None
    mod._rec_predictor = None
    yield
    mod._foundation = None
    mod._det_predictor = None
    mod._rec_predictor = None


class TestOcrImage:
    @patch("doc2md.extract.ocr_extract._get_predictors")
    @patch("doc2md.extract.ocr_extract.Image")
    def test_returns_text(self, mock_image_mod, mock_get_preds):
        mock_rec = MagicMock()
        mock_det = MagicMock()
        mock_rec.return_value = [MockPrediction(["Hello world", "Line two"])]
        mock_get_preds.return_value = (mock_rec, mock_det)
        mock_image_mod.open.return_value = "fake_image"

        result = ocr_image(Path("/fake/image.png"))
        assert result == "Hello world\nLine two"

    @patch("doc2md.extract.ocr_extract._get_predictors")
    @patch("doc2md.extract.ocr_extract.Image")
    def test_empty_page(self, mock_image_mod, mock_get_preds):
        mock_rec = MagicMock()
        mock_det = MagicMock()
        mock_rec.return_value = [MockPrediction([])]
        mock_get_preds.return_value = (mock_rec, mock_det)
        mock_image_mod.open.return_value = "fake_image"

        result = ocr_image(Path("/fake/image.png"))
        assert result == ""


class TestExtractScreenshots:
    @patch("doc2md.extract.ocr_extract.ocr_image")
    def test_extracts_from_folder(self, mock_ocr, tmp_path):
        (tmp_path / "img1.png").write_bytes(b"fake")
        (tmp_path / "img2.png").write_bytes(b"fake")
        (tmp_path / "notes.txt").write_text("ignore me")
        mock_ocr.side_effect = ["Text from page 1", "Text from page 2"]

        pages = extract_screenshots(tmp_path)
        assert len(pages) == 2
        assert pages[0].raw_text == "Text from page 1"
        assert pages[1].raw_text == "Text from page 2"
        assert all(p.extraction_method == "surya" for p in pages)

    @patch("doc2md.extract.ocr_extract.ocr_image")
    def test_sorted_by_filename(self, mock_ocr, tmp_path):
        (tmp_path / "b_img.png").write_bytes(b"fake")
        (tmp_path / "a_img.png").write_bytes(b"fake")
        mock_ocr.side_effect = ["B text", "A text"]

        pages = extract_screenshots(tmp_path)
        assert pages[0].source_path.name == "a_img.png"
        assert pages[1].source_path.name == "b_img.png"

    @patch("doc2md.extract.ocr_extract.ocr_image")
    def test_handles_ocr_failure(self, mock_ocr, tmp_path):
        (tmp_path / "img.png").write_bytes(b"fake")
        mock_ocr.side_effect = RuntimeError("OCR failed")

        pages = extract_screenshots(tmp_path)
        assert len(pages) == 1
        assert pages[0].extraction_method == "surya_failed"
        assert pages[0].raw_text == ""

    def test_empty_folder(self, tmp_path):
        pages = extract_screenshots(tmp_path)
        assert pages == []
