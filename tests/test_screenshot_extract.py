"""Tests for screenshot format detection and extraction."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from doc2md.extract.ocr_engines import SuryaEngine
from doc2md.extract.screenshot_extract import (
    _split_image,
    extract_screenshot_spread,
    is_browser_screenshot,
    is_libby_spread,
)


def _make_image(width: int, height: int, color: str = "red") -> Image.Image:
    return Image.new("RGB", (width, height), color)


def _save_image(path: Path, width: int, height: int, color: str = "red"):
    img = _make_image(width, height, color)
    img.save(path)


class TestSplitImage:
    def test_splits_at_midpoint(self, tmp_path):
        img_path = tmp_path / "spread.png"
        _save_image(img_path, 3024, 1642)
        halves = _split_image(img_path)

        assert len(halves) == 2
        left_img, left_src = halves[0]
        right_img, right_src = halves[1]
        assert left_img.size == (1512, 1642)
        assert right_img.size == (1512, 1642)
        assert left_src == img_path
        assert right_src == img_path

    def test_preserves_pixel_content(self, tmp_path):
        """Left half red, right half blue -- split should preserve colors."""
        img = Image.new("RGB", (100, 50))
        img.paste(Image.new("RGB", (50, 50), "red"), (0, 0))
        img.paste(Image.new("RGB", (50, 50), "blue"), (50, 0))
        img_path = tmp_path / "bicolor.png"
        img.save(img_path)

        halves = _split_image(img_path)
        left_img = halves[0][0]
        right_img = halves[1][0]
        assert left_img.getpixel((25, 25)) == (255, 0, 0)
        assert right_img.getpixel((25, 25)) == (0, 0, 255)


class TestIsLibbySpread:
    def test_landscape_same_size(self, tmp_path):
        for i in range(3):
            _save_image(tmp_path / f"img_{i}.png", 3024, 1642)
        assert is_libby_spread(tmp_path) is True

    def test_portrait_rejected(self, tmp_path):
        for i in range(3):
            _save_image(tmp_path / f"img_{i}.png", 1642, 3024)
        assert is_libby_spread(tmp_path) is False

    def test_mixed_sizes_rejected(self, tmp_path):
        _save_image(tmp_path / "a.png", 3024, 1642)
        _save_image(tmp_path / "b.png", 2048, 1536)
        assert is_libby_spread(tmp_path) is False

    def test_empty_folder(self, tmp_path):
        assert is_libby_spread(tmp_path) is False

    def test_barely_landscape_rejected(self, tmp_path):
        """w > h but not w > h * 1.5 -- not a spread."""
        _save_image(tmp_path / "img.png", 1200, 1000)
        assert is_libby_spread(tmp_path) is False


class TestIsBrowserScreenshot:
    @patch("doc2md.extract.screenshot_extract.detect_content_bounds")
    def test_detected_when_chrome_present(self, mock_detect, tmp_path):
        """Uniform portrait images with chrome → True."""
        for i in range(5):
            _save_image(tmp_path / f"img_{i}.png", 1920, 1080)
        mock_detect.return_value = (65, 95, 1905, 1080)
        assert is_browser_screenshot(tmp_path) is True

    @patch("doc2md.extract.screenshot_extract.detect_content_bounds")
    def test_no_chrome_returns_false(self, mock_detect, tmp_path):
        """Uniform images but no chrome detected → False."""
        for i in range(5):
            _save_image(tmp_path / f"img_{i}.png", 1920, 1080)
        mock_detect.return_value = None
        assert is_browser_screenshot(tmp_path) is False

    def test_mixed_sizes_returns_false(self, tmp_path):
        _save_image(tmp_path / "a.png", 1920, 1080)
        _save_image(tmp_path / "b.png", 1024, 768)
        _save_image(tmp_path / "c.png", 1920, 1080)
        assert is_browser_screenshot(tmp_path) is False

    def test_fewer_than_3_returns_false(self, tmp_path):
        _save_image(tmp_path / "a.png", 1920, 1080)
        _save_image(tmp_path / "b.png", 1920, 1080)
        assert is_browser_screenshot(tmp_path) is False

    def test_empty_folder_returns_false(self, tmp_path):
        assert is_browser_screenshot(tmp_path) is False


class TestPageOrdering:
    @patch("doc2md.extract.ocr_extract._get_predictors")
    def test_left_before_right(self, mock_predictors, tmp_path):
        """Pages should be: img1_left, img1_right, img2_left, img2_right."""
        _save_image(tmp_path / "Screenshot 2026-01-20 at 11.52.07 AM.png", 200, 100)
        _save_image(tmp_path / "Screenshot 2026-01-20 at 11.53.07 AM.png", 200, 100)

        # Mock detection: all pages have enough bboxes
        mock_det = MagicMock()
        mock_det.side_effect = lambda imgs: [
            MagicMock(bboxes=[1, 2, 3]) for _ in imgs
        ]
        # Mock recognition
        def mock_rec(imgs, det_predictor=None):
            results = []
            for _ in imgs:
                line = MagicMock()
                line.text = "text"
                result = MagicMock()
                result.text_lines = [line]
                results.append(result)
            return results

        mock_predictors.return_value = (MagicMock(side_effect=mock_rec), mock_det)

        pages = extract_screenshot_spread(tmp_path, engine=SuryaEngine())

        assert len(pages) == 4
        assert pages[0].page_number == 1
        assert pages[1].page_number == 2
        assert pages[2].page_number == 3
        assert pages[3].page_number == 4
        # First two from first screenshot, second two from second
        assert pages[0].source_path == pages[1].source_path
        assert pages[2].source_path == pages[3].source_path
        assert pages[0].source_path != pages[2].source_path


class TestImageOnlySkip:
    @patch("doc2md.extract.ocr_extract._get_predictors")
    def test_few_bboxes_skipped(self, mock_predictors, tmp_path):
        """Pages with <3 bboxes should have empty raw_text and skip recognition."""
        _save_image(tmp_path / "img.png", 200, 100)

        # Left half: 2 bboxes (skip), Right half: 5 bboxes (process)
        mock_det = MagicMock()
        mock_det.side_effect = lambda imgs: [
            MagicMock(bboxes=[1, 2]) if i == 0 else MagicMock(bboxes=[1, 2, 3, 4, 5])
            for i, _ in enumerate(imgs)
        ]

        def mock_rec(imgs, det_predictor=None):
            # Only called for the right half
            assert len(imgs) == 1
            line = MagicMock()
            line.text = "recognized text"
            result = MagicMock()
            result.text_lines = [line]
            return [result]

        mock_predictors.return_value = (MagicMock(side_effect=mock_rec), mock_det)

        pages = extract_screenshot_spread(tmp_path, engine=SuryaEngine())

        assert len(pages) == 2
        assert pages[0].raw_text == ""  # skipped (image-only)
        assert pages[1].raw_text == "recognized text"
        assert pages[0].extraction_method == "surya"
