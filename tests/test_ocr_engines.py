"""Tests for the OCR engine abstraction and SuryaEngine."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from doc2md.extract.ocr_engines import (
    AppleVisionEngine,
    CascadeEngine,
    OcrEngine,
    OcrResult,
    SuryaEngine,
    TesseractEngine,
    default_quality_check,
)
from doc2md.models import Page


class MockTextLine:
    def __init__(self, text, confidence=0.95):
        self.text = text
        self.confidence = confidence


class MockPrediction:
    def __init__(self, lines):
        # Each entry in `lines` is either a str or (text, confidence)
        self.text_lines = [
            MockTextLine(*l) if isinstance(l, tuple) else MockTextLine(l)
            for l in lines
        ]


@pytest.fixture(autouse=True)
def reset_predictor():
    """Reset the global Surya predictor between tests."""
    import doc2md.extract.ocr_extract as mod
    mod._foundation = None
    mod._det_predictor = None
    mod._rec_predictor = None
    yield
    mod._foundation = None
    mod._det_predictor = None
    mod._rec_predictor = None


def _det_with_bboxes(count):
    return MagicMock(bboxes=[object()] * count)


class TestOcrResult:
    def test_dataclass_fields(self):
        page = Page(source_path=Path("/a.png"), raw_text="hi", extraction_method="surya")
        r = OcrResult(page=page, confidence=0.9, line_count=1)
        assert r.page is page
        assert r.confidence == pytest.approx(0.9)
        assert r.line_count == 1


class TestOcrEngineProtocol:
    def test_surya_satisfies_protocol(self):
        assert isinstance(SuryaEngine(), OcrEngine)


class TestSuryaEngine:
    def test_name(self):
        assert SuryaEngine().name == "surya"

    @patch("doc2md.extract.ocr_extract._get_predictors")
    def test_ocr_batch_returns_one_result_per_item(self, mock_predictors):
        mock_det = MagicMock(side_effect=lambda imgs: [_det_with_bboxes(5) for _ in imgs])
        mock_rec = MagicMock(side_effect=lambda imgs, det_predictor=None: [
            MockPrediction(["text"]) for _ in imgs
        ])
        mock_predictors.return_value = (mock_rec, mock_det)

        items = [(MagicMock(), Path(f"/{i}.png")) for i in range(3)]
        results = SuryaEngine().ocr_batch(items)

        assert len(results) == 3
        assert all(isinstance(r, OcrResult) for r in results)
        assert [r.page.source_path for r in results] == [Path("/0.png"), Path("/1.png"), Path("/2.png")]

    @patch("doc2md.extract.ocr_extract._get_predictors")
    def test_extracts_confidence_from_text_lines(self, mock_predictors):
        mock_det = MagicMock(side_effect=lambda imgs: [_det_with_bboxes(5) for _ in imgs])
        mock_rec = MagicMock(return_value=[
            MockPrediction([("line one", 0.90), ("line two", 0.80), ("line three", 0.70)])
        ])
        mock_predictors.return_value = (mock_rec, mock_det)

        items = [(MagicMock(), Path("/a.png"))]
        results = SuryaEngine().ocr_batch(items)

        assert len(results) == 1
        r = results[0]
        assert r.line_count == 3
        assert r.confidence == pytest.approx(0.80)
        assert r.page.raw_text == "line one\nline two\nline three"

    @patch("doc2md.extract.ocr_extract._get_predictors")
    def test_image_only_skip_zero_confidence(self, mock_predictors):
        # First image has 2 bboxes (<MIN_BBOXES=3); second has 4.
        mock_det = MagicMock(side_effect=lambda imgs: [
            _det_with_bboxes(2) if i == 0 else _det_with_bboxes(4)
            for i, _ in enumerate(imgs)
        ])
        mock_rec = MagicMock(side_effect=lambda imgs, det_predictor=None: [
            MockPrediction([("real text", 0.95)])
        ])
        mock_predictors.return_value = (mock_rec, mock_det)

        items = [(MagicMock(), Path("/img1.png")), (MagicMock(), Path("/img2.png"))]
        results = SuryaEngine().ocr_batch(items)

        # Image-only page: empty text, zero confidence, zero lines
        assert results[0].page.raw_text == ""
        assert results[0].confidence == 0.0
        assert results[0].line_count == 0
        # Text page: real content
        assert results[1].page.raw_text == "real text"
        assert results[1].confidence == pytest.approx(0.95)
        assert results[1].line_count == 1
        # rec_predictor should have been called with exactly one image
        mock_rec.assert_called_once()
        passed_images = mock_rec.call_args[0][0]
        assert len(passed_images) == 1

    @patch("doc2md.extract.ocr_extract._get_predictors")
    def test_auto_number_sequential(self, mock_predictors):
        mock_det = MagicMock(side_effect=lambda imgs: [_det_with_bboxes(5) for _ in imgs])
        mock_rec = MagicMock(side_effect=lambda imgs, det_predictor=None: [
            MockPrediction(["text"]) for _ in imgs
        ])
        mock_predictors.return_value = (mock_rec, mock_det)

        items = [(MagicMock(), Path(f"/{i}.png")) for i in range(3)]
        results = SuryaEngine().ocr_batch(items, auto_number=True)

        assert [r.page.page_number for r in results] == [1, 2, 3]

    @patch("doc2md.extract.ocr_extract._get_predictors")
    def test_auto_number_false_leaves_none(self, mock_predictors):
        mock_det = MagicMock(side_effect=lambda imgs: [_det_with_bboxes(5) for _ in imgs])
        mock_rec = MagicMock(side_effect=lambda imgs, det_predictor=None: [
            MockPrediction(["text"]) for _ in imgs
        ])
        mock_predictors.return_value = (mock_rec, mock_det)

        items = [(MagicMock(), Path("/a.png"))]
        results = SuryaEngine().ocr_batch(items)

        assert results[0].page.page_number is None


def _make_real_image(width: int = 400, height: int = 200) -> Image.Image:
    """Create a real PIL image so .crop() works during tests."""
    return Image.new("RGB", (width, height), color=(255, 255, 255))


def _make_pytesseract_mock(
    data_dict: dict | None = None,
    output_dict_class: type = dict,
) -> MagicMock:
    """Build a fake pytesseract module whose image_to_data returns the dict."""
    pytesseract_mock = MagicMock()
    pytesseract_mock.Output = MagicMock()
    pytesseract_mock.Output.DICT = "DICT"
    if data_dict is None:
        data_dict = {
            "text": ["hello", "world"],
            "conf": [90.0, 85.0],
            "block_num": [1, 1],
            "par_num": [1, 1],
            "line_num": [1, 1],
        }
    pytesseract_mock.image_to_data.return_value = data_dict
    return pytesseract_mock


class TestTesseractEngine:
    def test_name(self):
        assert TesseractEngine().name == "tesseract"

    def test_missing_dependency_raises_runtime_error(self):
        with patch.dict(sys.modules, {"pytesseract": None}):
            with pytest.raises(RuntimeError, match="pytesseract"):
                TesseractEngine().ocr_batch([
                    (_make_real_image(), Path("/a.png"))
                ])

    def test_ocr_batch_aggregates_lines_and_normalizes_confidence(self):
        fake_data = {
            "text": ["hello", "world", "next", "line"],
            "conf": [90.0, 80.0, 60.0, 50.0],
            "block_num": [1, 1, 1, 1],
            "par_num": [1, 1, 1, 1],
            "line_num": [1, 1, 2, 2],
        }
        pytesseract_mock = _make_pytesseract_mock(fake_data)
        with patch.dict(sys.modules, {"pytesseract": pytesseract_mock}):
            results = TesseractEngine().ocr_batch([
                (_make_real_image(), Path("/a.png"))
            ])
        assert len(results) == 1
        r = results[0]
        assert r.line_count == 2
        assert r.page.raw_text == "hello world\nnext line"
        # Line 1 mean conf = (0.90 + 0.80) / 2 = 0.85
        # Line 2 mean conf = (0.60 + 0.50) / 2 = 0.55
        # Overall mean   = (0.85 + 0.55) / 2 = 0.70
        assert r.confidence == pytest.approx(0.70)

    def test_filters_negative_confidence_sentinels(self):
        fake_data = {
            "text": ["good", "skip"],
            "conf": [95.0, -1.0],  # -1 means Tesseract saw no text
            "block_num": [1, 1],
            "par_num": [1, 1],
            "line_num": [1, 1],
        }
        pytesseract_mock = _make_pytesseract_mock(fake_data)
        with patch.dict(sys.modules, {"pytesseract": pytesseract_mock}):
            results = TesseractEngine().ocr_batch([
                (_make_real_image(), Path("/a.png"))
            ])
        assert results[0].page.raw_text == "good"
        assert results[0].confidence == pytest.approx(0.95)

    def test_column_preprocessing_splits_image(self):
        """With columns, each column gets its own image_to_data call."""
        fake_data = {
            "text": ["column_text"],
            "conf": [85.0],
            "block_num": [1],
            "par_num": [1],
            "line_num": [1],
        }
        pytesseract_mock = _make_pytesseract_mock(fake_data)

        columns = [(0, 200), (200, 400)]
        engine = TesseractEngine(columns=columns)
        with patch.dict(sys.modules, {"pytesseract": pytesseract_mock}):
            results = engine.ocr_batch([(_make_real_image(), Path("/a.png"))])

        # image_to_data should be called once per column = 2 total
        assert pytesseract_mock.image_to_data.call_count == 2
        # Text is concatenated with newline between columns
        assert results[0].page.raw_text == "column_text\ncolumn_text"
        assert results[0].line_count == 2

    def test_auto_number_sequential(self):
        pytesseract_mock = _make_pytesseract_mock()
        items = [(_make_real_image(), Path(f"/{i}.png")) for i in range(3)]
        with patch.dict(sys.modules, {"pytesseract": pytesseract_mock}):
            results = TesseractEngine().ocr_batch(items, auto_number=True)
        assert [r.page.page_number for r in results] == [1, 2, 3]

    def test_auto_number_false_leaves_none(self):
        pytesseract_mock = _make_pytesseract_mock()
        with patch.dict(sys.modules, {"pytesseract": pytesseract_mock}):
            results = TesseractEngine().ocr_batch(
                [(_make_real_image(), Path("/a.png"))]
            )
        assert results[0].page.page_number is None


class _FakeOcrmacModule:
    """Stand-in for the `ocrmac.ocrmac` module used in tests."""

    def __init__(self, annotations_per_image: list[list[tuple]]):
        self._annotations = list(annotations_per_image)
        self._call_idx = 0

    def OCR(self, image):
        annotations = self._annotations[self._call_idx]
        self._call_idx += 1
        mock_request = MagicMock()
        mock_request.recognize.return_value = annotations
        return mock_request


def _install_fake_ocrmac(annotations_per_image):
    """Put a fake `ocrmac.ocrmac` module on sys.modules for the test."""
    fake_submodule = _FakeOcrmacModule(annotations_per_image)
    fake_package = MagicMock()
    fake_package.ocrmac = fake_submodule
    return {"ocrmac": fake_package, "ocrmac.ocrmac": fake_submodule}


class TestAppleVisionEngine:
    def test_name(self):
        assert AppleVisionEngine().name == "apple_vision"

    def test_missing_dependency_raises_runtime_error(self):
        # Remove `ocrmac` from sys.modules and block re-import
        patched = sys.modules.copy()
        patched.pop("ocrmac", None)
        patched.pop("ocrmac.ocrmac", None)
        patched["ocrmac"] = None  # None blocks import
        with patch.dict(sys.modules, patched, clear=True):
            with pytest.raises(RuntimeError, match="ocrmac"):
                AppleVisionEngine().ocr_batch(
                    [(_make_real_image(), Path("/a.png"))]
                )

    def test_ocr_batch_extracts_text_and_mean_confidence(self):
        # Two text lines, confidences 0.9 and 0.7
        annotations = [[
            ("first line", 0.9, (0, 0, 100, 20)),
            ("second line", 0.7, (0, 25, 100, 45)),
        ]]
        fake_modules = _install_fake_ocrmac(annotations)
        with patch.dict(sys.modules, fake_modules):
            results = AppleVisionEngine().ocr_batch(
                [(_make_real_image(), Path("/a.png"))]
            )
        assert len(results) == 1
        r = results[0]
        assert r.page.raw_text == "first line\nsecond line"
        assert r.line_count == 2
        assert r.confidence == pytest.approx(0.8)

    def test_column_preprocessing(self):
        # One call per column, so we need 2 annotation sets for 1 page
        annotations = [
            [("left col", 0.9, (0, 0, 100, 20))],
            [("right col", 0.85, (0, 0, 100, 20))],
        ]
        fake_modules = _install_fake_ocrmac(annotations)
        columns = [(0, 200), (200, 400)]
        engine = AppleVisionEngine(columns=columns)
        with patch.dict(sys.modules, fake_modules):
            results = engine.ocr_batch([(_make_real_image(), Path("/a.png"))])
        assert results[0].page.raw_text == "left col\nright col"
        assert results[0].line_count == 2
        # (0.9 + 0.85) / 2 = 0.875
        assert results[0].confidence == pytest.approx(0.875)

    def test_auto_number_sequential(self):
        annotations = [
            [("t1", 0.9, (0, 0, 100, 20))],
            [("t2", 0.9, (0, 0, 100, 20))],
            [("t3", 0.9, (0, 0, 100, 20))],
        ]
        fake_modules = _install_fake_ocrmac(annotations)
        items = [(_make_real_image(), Path(f"/{i}.png")) for i in range(3)]
        with patch.dict(sys.modules, fake_modules):
            results = AppleVisionEngine().ocr_batch(items, auto_number=True)
        assert [r.page.page_number for r in results] == [1, 2, 3]


def _fake_result(path: Path, text: str, conf: float, line_count: int) -> OcrResult:
    return OcrResult(
        page=Page(source_path=path, raw_text=text, extraction_method="fake"),
        confidence=conf,
        line_count=line_count,
    )


class _ScriptedEngine:
    """Test double that returns pre-scripted OcrResults and records calls."""

    def __init__(self, name: str, results_by_key: dict[Path, OcrResult]):
        self.name = name
        self.results_by_key = results_by_key
        self.calls: list[list[tuple]] = []

    def ocr_batch(self, items, *, auto_number=False):
        self.calls.append(list(items))
        return [self.results_by_key[p] for _, p in items]


class TestDefaultQualityCheck:
    def _good_result(self):
        return _fake_result(Path("/a.png"), "one\ntwo\nthree", 0.9, 3)

    def test_accepts_good_result(self):
        assert default_quality_check(self._good_result()) is True

    def test_rejects_low_confidence(self):
        r = self._good_result()
        r.confidence = 0.50
        assert default_quality_check(r) is False

    def test_rejects_too_few_lines(self):
        r = self._good_result()
        r.line_count = 1
        assert default_quality_check(r) is False

    def test_rejects_high_non_printable_ratio(self):
        r = _fake_result(
            Path("/a.png"),
            "ok\x00\x00\x00\x00\x00\x00\x00",  # lots of control chars
            0.9,
            3,
        )
        assert default_quality_check(r) is False

    def test_custom_thresholds(self):
        r = _fake_result(Path("/a.png"), "one\ntwo", 0.55, 2)
        assert default_quality_check(r) is False
        assert default_quality_check(r, min_confidence=0.5, min_lines=2) is True


class TestCascadeEngine:
    def test_requires_at_least_one_stage(self):
        with pytest.raises(ValueError):
            CascadeEngine([])

    def test_empty_items_returns_empty(self):
        fake = _ScriptedEngine("fake", {})
        cascade = CascadeEngine([(fake, None)])
        assert cascade.ocr_batch([]) == []

    def test_single_stage_runs_once(self):
        p = Path("/a.png")
        fake = _ScriptedEngine("fake", {p: _fake_result(p, "text", 0.9, 3)})
        cascade = CascadeEngine([(fake, None)])
        results = cascade.ocr_batch([(_make_real_image(), p)])
        assert len(results) == 1
        assert results[0].page.raw_text == "text"
        assert len(fake.calls) == 1

    def test_failed_items_fallback_to_next_stage(self):
        p1, p2 = Path("/a.png"), Path("/b.png")
        # Primary: p1 good, p2 bad (low confidence)
        primary = _ScriptedEngine("primary", {
            p1: _fake_result(p1, "primary good", 0.9, 5),
            p2: _fake_result(p2, "primary bad", 0.3, 5),
        })
        # Fallback: p2 fixed
        fallback = _ScriptedEngine("fallback", {
            p2: _fake_result(p2, "fallback good", 0.95, 5),
        })
        cascade = CascadeEngine([
            (primary, default_quality_check),
            (fallback, None),
        ])
        results = cascade.ocr_batch([
            (_make_real_image(), p1),
            (_make_real_image(), p2),
        ])
        assert len(results) == 2
        assert results[0].page.raw_text == "primary good"
        assert results[1].page.raw_text == "fallback good"
        # Primary called on both, fallback called only on p2
        assert len(primary.calls[0]) == 2
        assert len(fallback.calls[0]) == 1

    def test_all_accepted_skips_later_stages(self):
        p = Path("/a.png")
        primary = _ScriptedEngine("primary", {p: _fake_result(p, "good", 0.9, 5)})
        fallback = _ScriptedEngine("fallback", {p: _fake_result(p, "unused", 0.9, 5)})
        cascade = CascadeEngine([
            (primary, default_quality_check),
            (fallback, None),
        ])
        results = cascade.ocr_batch([(_make_real_image(), p)])
        assert results[0].page.raw_text == "good"
        assert len(fallback.calls) == 0

    def test_auto_number_applied_at_end(self):
        p1, p2 = Path("/a.png"), Path("/b.png")
        primary = _ScriptedEngine("primary", {
            p1: _fake_result(p1, "a", 0.9, 5),
            p2: _fake_result(p2, "b", 0.3, 5),  # will fall back
        })
        fallback = _ScriptedEngine("fallback", {
            p2: _fake_result(p2, "b2", 0.95, 5),
        })
        cascade = CascadeEngine([
            (primary, default_quality_check),
            (fallback, None),
        ])
        results = cascade.ocr_batch(
            [(_make_real_image(), p1), (_make_real_image(), p2)],
            auto_number=True,
        )
        assert [r.page.page_number for r in results] == [1, 2]

    def test_three_stage_cascade(self):
        p1, p2, p3 = Path("/a.png"), Path("/b.png"), Path("/c.png")
        # Stage 1: p1 good, p2 and p3 bad
        s1 = _ScriptedEngine("s1", {
            p1: _fake_result(p1, "s1-a", 0.9, 5),
            p2: _fake_result(p2, "s1-b", 0.1, 5),
            p3: _fake_result(p3, "s1-c", 0.1, 5),
        })
        # Stage 2: p2 good, p3 still bad
        s2 = _ScriptedEngine("s2", {
            p2: _fake_result(p2, "s2-b", 0.9, 5),
            p3: _fake_result(p3, "s2-c", 0.1, 5),
        })
        # Stage 3: p3 fallback
        s3 = _ScriptedEngine("s3", {
            p3: _fake_result(p3, "s3-c", 0.95, 5),
        })
        cascade = CascadeEngine([
            (s1, default_quality_check),
            (s2, default_quality_check),
            (s3, None),
        ])
        results = cascade.ocr_batch([
            (_make_real_image(), p1),
            (_make_real_image(), p2),
            (_make_real_image(), p3),
        ])
        assert results[0].page.raw_text == "s1-a"
        assert results[1].page.raw_text == "s2-b"
        assert results[2].page.raw_text == "s3-c"
        # s1 saw all 3, s2 saw 2 (failed from s1), s3 saw 1 (failed from s2)
        assert len(s1.calls[0]) == 3
        assert len(s2.calls[0]) == 2
        assert len(s3.calls[0]) == 1
