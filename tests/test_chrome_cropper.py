"""Tests for browser chrome detection and cropping."""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from doc2md.extract.chrome_cropper import (
    _find_edge,
    _sample_indices,
    crop_image,
    detect_column_bounds,
    detect_content_bounds,
    split_image_into_columns,
)


def _make_chrome_images(
    tmp_path: Path,
    count: int = 8,
    width: int = 200,
    height: int = 150,
    chrome_top: int = 20,
    chrome_left: int = 15,
    chrome_right: int = 10,
    chrome_bottom: int = 0,
) -> list[Path]:
    """Create synthetic screenshots with fixed chrome borders and random content."""
    rng = np.random.RandomState(42)
    paths = []
    for i in range(count):
        arr = np.zeros((height, width, 3), dtype=np.uint8)
        # Fixed chrome borders (same across all images)
        arr[:chrome_top, :] = [80, 80, 80]  # top bar
        arr[:, :chrome_left] = [50, 50, 50]  # left dock
        if chrome_right > 0:
            arr[:, -chrome_right:] = [60, 60, 60]  # right scrollbar
        if chrome_bottom > 0:
            arr[-chrome_bottom:, :] = [70, 70, 70]  # bottom bar
        # Random content in center (varies per image)
        ct = chrome_top
        cb = height - chrome_bottom if chrome_bottom > 0 else height
        cl = chrome_left
        cr = width - chrome_right if chrome_right > 0 else width
        arr[ct:cb, cl:cr] = rng.randint(50, 200, (cb - ct, cr - cl, 3), dtype=np.uint8)
        img = Image.fromarray(arr)
        p = tmp_path / f"screenshot_{i:03d}.png"
        img.save(p)
        paths.append(p)
    return paths


class TestDetectContentBounds:
    def test_detects_chrome_borders(self, tmp_path):
        paths = _make_chrome_images(tmp_path)
        bounds = detect_content_bounds(paths)
        assert bounds is not None
        left, top, right, bottom = bounds
        assert top == 20
        assert left == 15
        assert right == 190  # 200 - 10
        assert bottom == 150

    def test_detects_all_four_borders(self, tmp_path):
        paths = _make_chrome_images(
            tmp_path, chrome_top=25, chrome_left=20,
            chrome_right=15, chrome_bottom=10,
        )
        bounds = detect_content_bounds(paths)
        assert bounds is not None
        left, top, right, bottom = bounds
        assert top == 25
        assert left == 20
        assert right == 185  # 200 - 15
        assert bottom == 140  # 150 - 10

    def test_no_chrome_returns_none(self, tmp_path):
        """All-random images with no consistent borders → None."""
        rng = np.random.RandomState(99)
        paths = []
        for i in range(8):
            arr = rng.randint(50, 200, (150, 200, 3), dtype=np.uint8)
            img = Image.fromarray(arr)
            p = tmp_path / f"img_{i}.png"
            img.save(p)
            paths.append(p)
        assert detect_content_bounds(paths) is None

    def test_fewer_than_3_returns_none(self, tmp_path):
        paths = _make_chrome_images(tmp_path, count=2)
        assert detect_content_bounds(paths) is None

    def test_mixed_dimensions_returns_none(self, tmp_path):
        p1 = tmp_path / "a.png"
        p2 = tmp_path / "b.png"
        p3 = tmp_path / "c.png"
        Image.fromarray(np.zeros((100, 200, 3), dtype=np.uint8)).save(p1)
        Image.fromarray(np.zeros((150, 200, 3), dtype=np.uint8)).save(p2)
        Image.fromarray(np.zeros((100, 200, 3), dtype=np.uint8)).save(p3)
        assert detect_content_bounds([p1, p2, p3]) is None

    def test_all_identical_returns_none(self, tmp_path):
        """All images identical → zero std everywhere → no content detected."""
        arr = np.full((150, 200, 3), 128, dtype=np.uint8)
        paths = []
        for i in range(5):
            p = tmp_path / f"same_{i}.png"
            Image.fromarray(arr).save(p)
            paths.append(p)
        assert detect_content_bounds(paths) is None

    def test_respects_sample_size(self, tmp_path):
        """With many images, only sample_size are loaded."""
        paths = _make_chrome_images(tmp_path, count=20)
        bounds = detect_content_bounds(paths, sample_size=5)
        assert bounds is not None
        assert bounds[1] == 20  # top chrome still detected


class TestCropImage:
    def test_crop_applies_bounds(self):
        img = Image.fromarray(np.zeros((150, 200, 3), dtype=np.uint8))
        cropped = crop_image(img, (15, 20, 190, 150))
        assert cropped.size == (175, 130)

    def test_crop_preserves_content(self):
        arr = np.zeros((150, 200, 3), dtype=np.uint8)
        arr[50, 100] = [255, 0, 0]  # red pixel at (100, 50)
        img = Image.fromarray(arr)
        cropped = crop_image(img, (10, 10, 190, 140))
        # Red pixel now at (90, 40) in cropped coords
        pixel = cropped.getpixel((90, 40))
        assert pixel == (255, 0, 0)


class TestSampleIndices:
    def test_fewer_than_sample(self):
        assert _sample_indices(3, 8) == [0, 1, 2]

    def test_exact_sample(self):
        result = _sample_indices(8, 8)
        assert result[0] == 0
        assert result[-1] == 7
        assert len(result) == 8

    def test_larger_list(self):
        result = _sample_indices(100, 5)
        assert result[0] == 0
        assert result[-1] == 99
        assert len(result) == 5


class TestFindEdge:
    def test_from_start(self):
        profile = np.array([1.0, 2.0, 20.0, 30.0, 25.0, 3.0])
        assert _find_edge(profile, 15.0) == 2

    def test_from_end(self):
        profile = np.array([1.0, 2.0, 20.0, 30.0, 25.0, 3.0])
        assert _find_edge(profile, 15.0, from_end=True) == 4

    def test_all_below_threshold(self):
        profile = np.array([1.0, 2.0, 3.0])
        assert _find_edge(profile, 15.0) == 0
        assert _find_edge(profile, 15.0, from_end=True) == 2


def _make_column_images(
    tmp_path: Path,
    count: int = 8,
    width: int = 400,
    height: int = 200,
    columns: list[tuple[int, int]] | None = None,
) -> list[Path]:
    """Synthesize pages with random text in given column x-ranges on white bg."""
    if columns is None:
        columns = [(20, 180), (220, 380)]  # two columns with 40px gutter
    rng = np.random.RandomState(123)
    paths = []
    for i in range(count):
        arr = np.full((height, width, 3), 255, dtype=np.uint8)  # white page
        for left, right in columns:
            arr[10:height - 10, left:right] = rng.randint(
                0, 180, (height - 20, right - left, 3), dtype=np.uint8
            )
        p = tmp_path / f"col_{i:03d}.png"
        Image.fromarray(arr).save(p)
        paths.append(p)
    return paths


class TestDetectColumnBounds:
    def test_detects_two_columns(self, tmp_path):
        paths = _make_column_images(tmp_path)
        columns = detect_column_bounds(paths)
        assert len(columns) == 2
        c1, c2 = columns
        # Allow a few pixels of slack on each edge
        assert abs(c1[0] - 20) <= 2
        assert abs(c1[1] - 180) <= 2
        assert abs(c2[0] - 220) <= 2
        assert abs(c2[1] - 380) <= 2

    def test_detects_single_wide_column(self, tmp_path):
        paths = _make_column_images(
            tmp_path, columns=[(30, 370)],  # one wide column with margins
        )
        columns = detect_column_bounds(paths)
        assert len(columns) == 1
        left, right = columns[0]
        assert abs(left - 30) <= 2
        assert abs(right - 370) <= 2

    def test_detects_three_columns(self, tmp_path):
        paths = _make_column_images(
            tmp_path,
            width=600,
            columns=[(20, 170), (200, 370), (400, 580)],
        )
        columns = detect_column_bounds(paths)
        assert len(columns) == 3

    def test_respects_content_bounds(self, tmp_path):
        """With content_bounds, columns are in cropped coordinate space."""
        # 400x200 image, content bounds crop off 50px on each side → 300 wide
        paths = _make_column_images(
            tmp_path,
            columns=[(70, 190), (210, 330)],  # 2 cols at raw coords
        )
        content_bounds = (50, 20, 350, 180)  # 300x160 content area
        columns = detect_column_bounds(paths, content_bounds=content_bounds)
        assert len(columns) == 2
        # Columns are in content space: raw_x - content_left
        c1, c2 = columns
        assert abs(c1[0] - (70 - 50)) <= 2
        assert abs(c1[1] - (190 - 50)) <= 2
        assert abs(c2[0] - (210 - 50)) <= 2
        assert abs(c2[1] - (330 - 50)) <= 2

    def test_fewer_than_3_images_returns_full_width(self, tmp_path):
        paths = _make_column_images(tmp_path, count=2)
        columns = detect_column_bounds(paths)
        assert columns == [(0, 400)]

    def test_mixed_dimensions_returns_full_width(self, tmp_path):
        p1 = tmp_path / "a.png"
        p2 = tmp_path / "b.png"
        p3 = tmp_path / "c.png"
        Image.fromarray(np.full((200, 400, 3), 255, dtype=np.uint8)).save(p1)
        Image.fromarray(np.full((200, 300, 3), 255, dtype=np.uint8)).save(p2)
        Image.fromarray(np.full((200, 400, 3), 255, dtype=np.uint8)).save(p3)
        columns = detect_column_bounds([p1, p2, p3])
        assert columns == [(0, 400)]

    def test_blank_pages_return_full_width(self, tmp_path):
        """All-white pages have zero variance; should fall back to single column."""
        paths = []
        for i in range(5):
            arr = np.full((200, 400, 3), 255, dtype=np.uint8)
            p = tmp_path / f"blank_{i}.png"
            Image.fromarray(arr).save(p)
            paths.append(p)
        columns = detect_column_bounds(paths)
        assert columns == [(0, 400)]

    def test_narrow_runs_filtered(self, tmp_path):
        """A narrow text run below min_col_width should be discarded."""
        # Main 150-wide column plus a tiny 30-wide strip of text
        paths = _make_column_images(
            tmp_path,
            columns=[(30, 180), (220, 250)],  # strip is 30 wide < min_col_width=100
        )
        columns = detect_column_bounds(paths)
        # Only the main column should survive
        assert len(columns) == 1
        assert columns[0][0] >= 28 and columns[0][1] <= 182


class TestSplitImageIntoColumns:
    def test_splits_two_columns(self):
        img = Image.fromarray(np.zeros((100, 400, 3), dtype=np.uint8))
        cols = split_image_into_columns(img, [(0, 200), (200, 400)])
        assert len(cols) == 2
        assert cols[0].size == (200, 100)
        assert cols[1].size == (200, 100)

    def test_preserves_column_pixel_content(self):
        arr = np.zeros((100, 400, 3), dtype=np.uint8)
        arr[50, 50] = [255, 0, 0]   # red pixel in left column
        arr[50, 250] = [0, 255, 0]  # green pixel in right column
        img = Image.fromarray(arr)
        cols = split_image_into_columns(img, [(0, 200), (200, 400)])
        assert cols[0].getpixel((50, 50)) == (255, 0, 0)
        assert cols[1].getpixel((50, 50)) == (0, 255, 0)  # 250 - 200 = 50

    def test_single_column_returns_one_image(self):
        img = Image.fromarray(np.zeros((100, 400, 3), dtype=np.uint8))
        cols = split_image_into_columns(img, [(0, 400)])
        assert len(cols) == 1
        assert cols[0].size == (400, 100)
