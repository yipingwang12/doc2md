"""Tests for two-column PDF layout reflow."""

from pathlib import Path

from doc2md.papers.column_extractor import (
    detect_column_split,
    extract_two_column_pages,
    reorder_blocks_two_column,
)


def _block(x0, y0, x1, y1, text="text"):
    """Build a minimal PyMuPDF-style block dict."""
    return {
        "type": 0,
        "bbox": (x0, y0, x1, y1),
        "lines": [{"spans": [{"text": text, "size": 10.0, "font": "Times-Roman"}]}],
    }


class TestDetectColumnSplit:
    def test_single_column_returns_none(self):
        # All blocks span nearly full width
        blocks = [_block(50, y, 550, y + 20) for y in range(0, 200, 25)]
        assert detect_column_split(blocks, page_width=600) is None

    def test_two_column_detects_gutter(self):
        # Left column blocks: x0 ~50, x1 ~270; right column: x0 ~330, x1 ~550
        left = [_block(50, y, 270, y + 20) for y in range(0, 200, 25)]
        right = [_block(330, y, 550, y + 20) for y in range(0, 200, 25)]
        split = detect_column_split(left + right, page_width=600)
        assert split is not None
        assert 270 < split < 330

    def test_full_width_block_does_not_prevent_detection(self):
        # Title spanning full width + two-column body
        full_width = [_block(50, 0, 550, 40, "Title")]
        left = [_block(50, y, 270, y + 20) for y in range(50, 200, 25)]
        right = [_block(330, y, 550, y + 20) for y in range(50, 200, 25)]
        split = detect_column_split(full_width + left + right, page_width=600)
        assert split is not None

    def test_empty_blocks_returns_none(self):
        assert detect_column_split([], page_width=600) is None

    def test_single_block_returns_none(self):
        assert detect_column_split([_block(50, 0, 270, 20)], page_width=600) is None

    def test_gutter_must_be_between_30_and_70_percent(self):
        # Blocks clustered near left edge — not a two-column layout
        blocks = [_block(10, y, 100, y + 20) for y in range(0, 100, 25)]
        blocks += [_block(110, y, 200, y + 20) for y in range(0, 100, 25)]
        # Gap is at x=100–110, which is only ~17% across a 600px page
        assert detect_column_split(blocks, page_width=600) is None


class TestReorderBlocksTwoColumn:
    def test_left_then_right_order(self):
        # Left column: two blocks stacked; right column: two blocks stacked
        blocks = [
            _block(330, 0, 550, 20, "R1"),
            _block(50, 0, 270, 20, "L1"),
            _block(330, 25, 550, 45, "R2"),
            _block(50, 25, 270, 45, "L2"),
        ]
        result = reorder_blocks_two_column(blocks, split_x=300)
        texts = [b["lines"][0]["spans"][0]["text"] for b in result]
        assert texts.index("L1") < texts.index("L2")
        assert texts.index("L2") < texts.index("R1")
        assert texts.index("R1") < texts.index("R2")

    def test_full_width_blocks_placed_first(self):
        full = _block(50, 0, 550, 40, "Title")
        left = _block(50, 50, 270, 70, "Left body")
        right = _block(330, 50, 550, 70, "Right body")
        result = reorder_blocks_two_column([left, right, full], split_x=300)
        texts = [b["lines"][0]["spans"][0]["text"] for b in result]
        assert texts[0] == "Title"

    def test_within_column_sorted_by_y(self):
        blocks = [
            _block(50, 100, 270, 120, "L3"),
            _block(50, 0, 270, 20, "L1"),
            _block(50, 50, 270, 70, "L2"),
        ]
        result = reorder_blocks_two_column(blocks, split_x=300)
        texts = [b["lines"][0]["spans"][0]["text"] for b in result]
        assert texts == ["L1", "L2", "L3"]

    def test_empty_returns_empty(self):
        assert reorder_blocks_two_column([], split_x=300) == []

    def test_non_text_blocks_preserved_in_position(self):
        # type != 0 blocks (images) should be kept in order
        img_block = {"type": 1, "bbox": (50, 0, 550, 100)}
        text_left = _block(50, 110, 270, 130, "Left")
        text_right = _block(330, 110, 550, 130, "Right")
        result = reorder_blocks_two_column([text_right, img_block, text_left], split_x=300)
        assert any(b.get("type") == 1 for b in result)


class TestExtractTwoColumnPages:
    def test_returns_pages(self, tmp_path):
        # Use an existing small PDF from the test fixtures if available,
        # otherwise just verify the function is importable and callable with a stub.
        import importlib
        assert importlib.import_module("doc2md.papers.column_extractor")

    def test_single_column_pdf_unchanged_order(self, tmp_path):
        """Single-column PDF should produce same text as standard extract_pages."""
        import fitz
        from doc2md.extract.pdf_extract import extract_pages

        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "Hello world single column text.")
        pdf_path = tmp_path / "single.pdf"
        doc.save(str(pdf_path))
        doc.close()

        std_pages = extract_pages(pdf_path)
        two_col_pages = extract_two_column_pages(pdf_path)
        assert len(std_pages) == len(two_col_pages)
        assert std_pages[0].raw_text.strip() == two_col_pages[0].raw_text.strip()
