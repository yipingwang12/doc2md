"""Tests for Surya OCR extraction (mocked)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from doc2md.extract.ocr_engines import OcrResult, SuryaEngine
from doc2md.extract.ocr_extract import _ocr_pil, extract_screenshots, ocr_image
from doc2md.models import Page


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


def _result_for(path: Path, text: str, *, page_number=None) -> OcrResult:
    """Helper to build an OcrResult with a Page for tests."""
    page = Page(
        source_path=path,
        raw_text=text,
        extraction_method="surya",
        page_number=page_number,
    )
    return OcrResult(page=page, confidence=0.95, line_count=text.count("\n") + 1 if text else 0)


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


class TestOcrPil:
    @patch("doc2md.extract.ocr_extract._get_predictors")
    def test_returns_text(self, mock_get_preds):
        mock_rec = MagicMock()
        mock_det = MagicMock()
        mock_rec.return_value = [MockPrediction(["Line A", "Line B"])]
        mock_get_preds.return_value = (mock_rec, mock_det)

        result = _ocr_pil("fake_pil_image")
        assert result == "Line A\nLine B"
        mock_rec.assert_called_once_with(["fake_pil_image"], det_predictor=mock_det)


def _mock_engine(*results: OcrResult) -> MagicMock:
    """Build a MagicMock that plays the OcrEngine protocol and returns
    the given results from ocr_batch."""
    engine = MagicMock()
    engine.ocr_batch.return_value = list(results)
    return engine


class TestExtractScreenshots:
    @patch("doc2md.extract.ocr_extract.detect_content_bounds", return_value=None)
    @patch("doc2md.extract.ocr_extract.Image")
    def test_extracts_from_folder(self, mock_image_mod, _mock_detect, tmp_path):
        (tmp_path / "img1.png").write_bytes(b"fake")
        (tmp_path / "img2.png").write_bytes(b"fake")
        (tmp_path / "notes.txt").write_text("ignore me")
        mock_image_mod.open.return_value = "fake_image"
        engine = _mock_engine(
            _result_for(tmp_path / "img1.png", "Text 1"),
            _result_for(tmp_path / "img2.png", "Text 2"),
        )

        pages = extract_screenshots(tmp_path, engine=engine)
        assert len(pages) == 2
        assert pages[0].raw_text == "Text 1"
        assert pages[1].raw_text == "Text 2"
        engine.ocr_batch.assert_called_once()
        _, kwargs = engine.ocr_batch.call_args
        assert kwargs["auto_number"] is False

    @patch("doc2md.extract.ocr_extract.detect_content_bounds", return_value=None)
    @patch("doc2md.extract.ocr_extract.Image")
    def test_sorted_by_filename(self, mock_image_mod, _mock_detect, tmp_path):
        (tmp_path / "b_img.png").write_bytes(b"fake")
        (tmp_path / "a_img.png").write_bytes(b"fake")
        mock_image_mod.open.return_value = "fake_image"
        engine = _mock_engine(
            _result_for(tmp_path / "a_img.png", "A"),
            _result_for(tmp_path / "b_img.png", "B"),
        )

        pages = extract_screenshots(tmp_path, engine=engine)
        assert pages[0].source_path.name == "a_img.png"
        assert pages[1].source_path.name == "b_img.png"

    @patch("doc2md.extract.ocr_extract.detect_content_bounds", return_value=None)
    @patch("doc2md.extract.ocr_extract.Image")
    def test_handles_open_failure(self, mock_image_mod, _mock_detect, tmp_path):
        (tmp_path / "img.png").write_bytes(b"fake")
        mock_image_mod.open.side_effect = RuntimeError("bad file")
        engine = _mock_engine()

        pages = extract_screenshots(tmp_path, engine=engine)
        assert len(pages) == 1
        assert pages[0].extraction_method == "surya_failed"
        assert pages[0].raw_text == ""

    @patch("doc2md.extract.ocr_extract.detect_content_bounds", return_value=None)
    def test_empty_folder(self, _mock_detect, tmp_path):
        engine = _mock_engine()
        pages = extract_screenshots(tmp_path, engine=engine)
        assert pages == []

    @patch("doc2md.extract.ocr_extract.detect_content_bounds", return_value=None)
    @patch("doc2md.extract.ocr_extract.Image")
    def test_auto_number_passed_through(self, mock_image_mod, _mock_detect, tmp_path):
        (tmp_path / "img.png").write_bytes(b"fake")
        mock_image_mod.open.return_value = "fake_image"
        engine = _mock_engine(_result_for(tmp_path / "img.png", "text", page_number=1))

        extract_screenshots(tmp_path, engine=engine, auto_number=True)
        _, kwargs = engine.ocr_batch.call_args
        assert kwargs["auto_number"] is True

    @patch("doc2md.extract.ocr_extract.detect_content_bounds", return_value=None)
    @patch("doc2md.extract.ocr_extract.Image")
    def test_accepts_custom_engine(self, mock_image_mod, _mock_detect, tmp_path):
        (tmp_path / "img.png").write_bytes(b"fake")
        mock_image_mod.open.return_value = "fake_image"

        engine = _mock_engine(_result_for(tmp_path / "img.png", "custom engine output"))

        pages = extract_screenshots(tmp_path, engine=engine)
        assert len(pages) == 1
        assert pages[0].raw_text == "custom engine output"
        engine.ocr_batch.assert_called_once()


class TestExtractScreenshotsCropping:
    @patch("doc2md.extract.ocr_extract.detect_content_bounds")
    @patch("doc2md.extract.ocr_extract.crop_image")
    @patch("doc2md.extract.ocr_extract.Image")
    def test_crops_when_bounds_detected(
        self, mock_image_mod, mock_crop, mock_detect, tmp_path
    ):
        (tmp_path / "img1.png").write_bytes(b"fake")
        fake_img = MagicMock()
        mock_image_mod.open.return_value = fake_img
        mock_detect.return_value = (10, 20, 190, 140)
        cropped_img = MagicMock()
        mock_crop.return_value = cropped_img
        engine = _mock_engine(_result_for(tmp_path / "img1.png", "Cropped text"))

        pages = extract_screenshots(tmp_path, engine=engine)
        assert len(pages) == 1
        assert pages[0].raw_text == "Cropped text"
        mock_crop.assert_called_once_with(fake_img, (10, 20, 190, 140))
        items = engine.ocr_batch.call_args[0][0]
        assert items[0][0] is cropped_img

    @patch("doc2md.extract.ocr_extract.detect_content_bounds")
    @patch("doc2md.extract.ocr_extract.Image")
    def test_no_crop_when_no_bounds(
        self, mock_image_mod, mock_detect, tmp_path
    ):
        (tmp_path / "img1.png").write_bytes(b"fake")
        fake_img = MagicMock()
        mock_image_mod.open.return_value = fake_img
        mock_detect.return_value = None
        engine = _mock_engine(_result_for(tmp_path / "img1.png", "Uncropped text"))

        pages = extract_screenshots(tmp_path, engine=engine)
        assert len(pages) == 1
        assert pages[0].raw_text == "Uncropped text"
        items = engine.ocr_batch.call_args[0][0]
        assert items[0][0] is fake_img
