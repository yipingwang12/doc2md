"""Tests for Surya OCR extraction (mocked)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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


class TestExtractScreenshots:
    @patch("doc2md.extract.ocr_extract.detect_content_bounds", return_value=None)
    @patch("doc2md.extract.ocr_extract._ocr_batched")
    @patch("doc2md.extract.ocr_extract.Image")
    def test_extracts_from_folder(self, mock_image_mod, mock_batched, _mock_detect, tmp_path):
        (tmp_path / "img1.png").write_bytes(b"fake")
        (tmp_path / "img2.png").write_bytes(b"fake")
        (tmp_path / "notes.txt").write_text("ignore me")
        mock_image_mod.open.return_value = "fake_image"
        mock_batched.return_value = [
            Page(source_path=tmp_path / "img1.png", raw_text="Text 1", extraction_method="surya"),
            Page(source_path=tmp_path / "img2.png", raw_text="Text 2", extraction_method="surya"),
        ]

        pages = extract_screenshots(tmp_path)
        assert len(pages) == 2
        assert pages[0].raw_text == "Text 1"
        assert pages[1].raw_text == "Text 2"
        # Verify _ocr_batched called with items and auto_number=False
        mock_batched.assert_called_once()
        _, kwargs = mock_batched.call_args
        assert kwargs["auto_number"] is False

    @patch("doc2md.extract.ocr_extract.detect_content_bounds", return_value=None)
    @patch("doc2md.extract.ocr_extract._ocr_batched")
    @patch("doc2md.extract.ocr_extract.Image")
    def test_sorted_by_filename(self, mock_image_mod, mock_batched, _mock_detect, tmp_path):
        (tmp_path / "b_img.png").write_bytes(b"fake")
        (tmp_path / "a_img.png").write_bytes(b"fake")
        mock_image_mod.open.return_value = "fake_image"
        mock_batched.return_value = [
            Page(source_path=tmp_path / "a_img.png", raw_text="A", extraction_method="surya"),
            Page(source_path=tmp_path / "b_img.png", raw_text="B", extraction_method="surya"),
        ]

        pages = extract_screenshots(tmp_path)
        assert pages[0].source_path.name == "a_img.png"
        assert pages[1].source_path.name == "b_img.png"

    @patch("doc2md.extract.ocr_extract.detect_content_bounds", return_value=None)
    @patch("doc2md.extract.ocr_extract._ocr_batched")
    @patch("doc2md.extract.ocr_extract.Image")
    def test_handles_open_failure(self, mock_image_mod, mock_batched, _mock_detect, tmp_path):
        (tmp_path / "img.png").write_bytes(b"fake")
        mock_image_mod.open.side_effect = RuntimeError("bad file")
        mock_batched.return_value = []

        pages = extract_screenshots(tmp_path)
        assert len(pages) == 1
        assert pages[0].extraction_method == "surya_failed"
        assert pages[0].raw_text == ""

    @patch("doc2md.extract.ocr_extract.detect_content_bounds", return_value=None)
    def test_empty_folder(self, _mock_detect, tmp_path):
        pages = extract_screenshots(tmp_path)
        assert pages == []

    @patch("doc2md.extract.ocr_extract.detect_content_bounds", return_value=None)
    @patch("doc2md.extract.ocr_extract._ocr_batched")
    @patch("doc2md.extract.ocr_extract.Image")
    def test_auto_number_passed_through(self, mock_image_mod, mock_batched, _mock_detect, tmp_path):
        (tmp_path / "img.png").write_bytes(b"fake")
        mock_image_mod.open.return_value = "fake_image"
        mock_batched.return_value = [
            Page(source_path=tmp_path / "img.png", raw_text="text", extraction_method="surya", page_number=1),
        ]

        pages = extract_screenshots(tmp_path, auto_number=True)
        _, kwargs = mock_batched.call_args
        assert kwargs["auto_number"] is True


class TestExtractScreenshotsCropping:
    @patch("doc2md.extract.ocr_extract._ocr_batched")
    @patch("doc2md.extract.ocr_extract.detect_content_bounds")
    @patch("doc2md.extract.ocr_extract.crop_image")
    @patch("doc2md.extract.ocr_extract.Image")
    def test_crops_when_bounds_detected(
        self, mock_image_mod, mock_crop, mock_detect, mock_batched, tmp_path
    ):
        (tmp_path / "img1.png").write_bytes(b"fake")
        fake_img = MagicMock()
        mock_image_mod.open.return_value = fake_img
        mock_detect.return_value = (10, 20, 190, 140)
        cropped_img = MagicMock()
        mock_crop.return_value = cropped_img
        mock_batched.return_value = [
            Page(source_path=tmp_path / "img1.png", raw_text="Cropped text", extraction_method="surya"),
        ]

        pages = extract_screenshots(tmp_path)
        assert len(pages) == 1
        assert pages[0].raw_text == "Cropped text"
        mock_crop.assert_called_once_with(fake_img, (10, 20, 190, 140))
        # Verify the cropped image was passed to _ocr_batched
        items = mock_batched.call_args[0][0]
        assert items[0][0] is cropped_img

    @patch("doc2md.extract.ocr_extract._ocr_batched")
    @patch("doc2md.extract.ocr_extract.detect_content_bounds")
    @patch("doc2md.extract.ocr_extract.Image")
    def test_no_crop_when_no_bounds(
        self, mock_image_mod, mock_detect, mock_batched, tmp_path
    ):
        (tmp_path / "img1.png").write_bytes(b"fake")
        fake_img = MagicMock()
        mock_image_mod.open.return_value = fake_img
        mock_detect.return_value = None
        mock_batched.return_value = [
            Page(source_path=tmp_path / "img1.png", raw_text="Uncropped text", extraction_method="surya"),
        ]

        pages = extract_screenshots(tmp_path)
        assert len(pages) == 1
        assert pages[0].raw_text == "Uncropped text"
        # Verify the original image was passed to _ocr_batched
        items = mock_batched.call_args[0][0]
        assert items[0][0] is fake_img


class TestOcrBatched:
    @patch("doc2md.extract.ocr_extract._get_predictors")
    def test_batched_with_auto_number(self, mock_predictors):
        from doc2md.extract.ocr_extract import _ocr_batched

        mock_det = MagicMock()
        mock_det.side_effect = lambda imgs: [MagicMock(bboxes=[1, 2, 3]) for _ in imgs]

        def mock_rec(imgs, det_predictor=None):
            return [MockPrediction([f"text_{i}"]) for i in range(len(imgs))]

        mock_predictors.return_value = (MagicMock(side_effect=mock_rec), mock_det)

        items = [
            (MagicMock(), Path("/a.png")),
            (MagicMock(), Path("/b.png")),
        ]
        pages = _ocr_batched(items, auto_number=True)
        assert len(pages) == 2
        assert pages[0].page_number == 1
        assert pages[1].page_number == 2

    @patch("doc2md.extract.ocr_extract._get_predictors")
    def test_batched_without_auto_number(self, mock_predictors):
        from doc2md.extract.ocr_extract import _ocr_batched

        mock_det = MagicMock()
        mock_det.side_effect = lambda imgs: [MagicMock(bboxes=[1, 2, 3]) for _ in imgs]

        def mock_rec(imgs, det_predictor=None):
            return [MockPrediction(["text"]) for _ in imgs]

        mock_predictors.return_value = (MagicMock(side_effect=mock_rec), mock_det)

        items = [(MagicMock(), Path("/a.png"))]
        pages = _ocr_batched(items, auto_number=False)
        assert pages[0].page_number is None

    @patch("doc2md.extract.ocr_extract._get_predictors")
    def test_image_only_pages_skipped(self, mock_predictors):
        from doc2md.extract.ocr_extract import _ocr_batched

        mock_det = MagicMock()
        mock_det.side_effect = lambda imgs: [
            MagicMock(bboxes=[1, 2]) if i == 0 else MagicMock(bboxes=[1, 2, 3, 4])
            for i, _ in enumerate(imgs)
        ]

        def mock_rec(imgs, det_predictor=None):
            assert len(imgs) == 1  # only second image recognized
            return [MockPrediction(["recognized"])]

        mock_predictors.return_value = (MagicMock(side_effect=mock_rec), mock_det)

        items = [(MagicMock(), Path("/img1.png")), (MagicMock(), Path("/img2.png"))]
        pages = _ocr_batched(items)
        assert pages[0].raw_text == ""
        assert pages[1].raw_text == "recognized"
