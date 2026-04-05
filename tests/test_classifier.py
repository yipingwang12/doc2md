"""Tests for block classification."""

from pathlib import Path
from unittest.mock import MagicMock

from doc2md.analysis.classifier import classify_page, classify_pages
from doc2md.analysis.segmenter import FontProfile
from doc2md.models import Page


def _page(text: str, block_dicts=None, page_height=800.0) -> Page:
    return Page(
        source_path=Path("/fake.pdf"),
        raw_text=text,
        extraction_method="pymupdf",
        block_dicts=block_dicts,
        page_height=page_height,
    )


class TestClassifyPageRawText:
    def test_empty_page_returns_empty(self):
        blocks = classify_page(_page(""), 0, MagicMock())
        assert blocks == []

    def test_body_text(self):
        blocks = classify_page(_page("Some body text here."), 0, MagicMock())
        assert len(blocks) == 1
        assert blocks[0].block_type == "body"
        assert blocks[0].text == "Some body text here."

    def test_all_caps_heading(self):
        blocks = classify_page(_page("INTRODUCTION\n\nBody text."), 0, MagicMock())
        assert len(blocks) == 2
        assert blocks[0].block_type == "heading"
        assert blocks[0].heading_level == 2
        assert blocks[1].block_type == "body"

    def test_footnote_in_bottom_half(self):
        text = "Body paragraph.\n\nMore body.\n\n1 This is a footnote."
        blocks = classify_page(_page(text), 0, MagicMock())
        footnotes = [b for b in blocks if b.block_type == "footnote"]
        assert len(footnotes) == 1
        assert footnotes[0].footnote_id == "1"

    def test_caption_detected(self):
        blocks = classify_page(_page("Figure 1. A diagram."), 0, MagicMock())
        assert blocks[0].block_type == "caption"

    def test_boilerplate_filtered(self):
        blocks = classify_page(_page("123\n\nhttps://example.com/foo"), 0, MagicMock())
        assert len(blocks) == 0

    def test_page_index_set(self):
        blocks = classify_page(_page("text"), 5, MagicMock())
        assert blocks[0].page_index == 5


class TestClassifyPageBlockDicts:
    def _make_block(self, text, size=10.0, y=100):
        return {
            "type": 0,
            "bbox": (0, y, 500, y + 20),
            "lines": [{
                "spans": [{"text": text, "size": size, "font": "TestFont", "flags": 0}],
            }],
        }

    def test_heading_by_font_size(self):
        profile = FontProfile(body_size=10.0, footnote_size=8.0, heading_sizes=[16.0])
        block_dicts = [self._make_block("Chapter Title", size=16.0)]
        page = _page("Chapter Title", block_dicts=block_dicts)
        blocks = classify_page(page, 0, MagicMock(), profile=profile)
        assert blocks[0].block_type == "heading"
        assert blocks[0].heading_level == 1

    def test_body_by_font_size(self):
        profile = FontProfile(body_size=10.0, footnote_size=8.0, heading_sizes=[16.0])
        block_dicts = [self._make_block("Regular body text.", size=10.0)]
        page = _page("Regular body text.", block_dicts=block_dicts)
        blocks = classify_page(page, 0, MagicMock(), profile=profile)
        assert blocks[0].block_type == "body"

    def test_all_caps_heading_at_body_size(self):
        profile = FontProfile(body_size=10.0, footnote_size=8.0, heading_sizes=[16.0])
        block_dicts = [self._make_block("INTRODUCTION", size=10.0)]
        page = _page("INTRODUCTION", block_dicts=block_dicts)
        blocks = classify_page(page, 0, MagicMock(), profile=profile)
        assert blocks[0].block_type == "heading"
        assert blocks[0].heading_level == 2

    def test_footnote_by_size_and_position(self):
        profile = FontProfile(body_size=10.0, footnote_size=8.0, heading_sizes=[16.0])
        block_dicts = [self._make_block("1 A footnote.", size=8.0, y=500)]
        page = _page("1 A footnote.", block_dicts=block_dicts, page_height=800.0)
        blocks = classify_page(page, 0, MagicMock(), profile=profile)
        assert blocks[0].block_type == "footnote"
        assert blocks[0].footnote_id == "1"

    def test_boilerplate_filtered(self):
        profile = FontProfile(body_size=10.0, footnote_size=8.0, heading_sizes=[16.0])
        block_dicts = [
            self._make_block("345", size=10.0),
            self._make_block("https://example.com/foo", size=6.0),
        ]
        page = _page("345\nhttps://example.com/foo", block_dicts=block_dicts)
        blocks = classify_page(page, 0, MagicMock(), profile=profile)
        assert len(blocks) == 0

    def test_repeated_lines_filtered(self):
        profile = FontProfile(
            body_size=10.0, footnote_size=8.0, heading_sizes=[16.0],
            repeated_lines={"Author Name"},
        )
        block_dicts = [self._make_block("Author Name", size=12.0)]
        page = _page("Author Name", block_dicts=block_dicts)
        blocks = classify_page(page, 0, MagicMock(), profile=profile)
        assert len(blocks) == 0


class TestClassifyPages:
    def test_processes_multiple_pages(self):
        pages = [_page("page one text"), _page("page two text")]
        blocks = classify_pages(pages, MagicMock())
        assert len(blocks) == 2
        assert blocks[0].page_index == 0
        assert blocks[1].page_index == 1

    def test_builds_font_profile_from_block_dicts(self):
        block_dicts = [{
            "type": 0,
            "bbox": (0, 100, 500, 120),
            "lines": [{"spans": [{"text": "Body text.", "size": 10.0, "font": "F", "flags": 0}]}],
        }]
        pages = [
            _page("Body text.", block_dicts=block_dicts),
            _page("More text.", block_dicts=block_dicts),
        ]
        blocks = classify_pages(pages, MagicMock())
        assert len(blocks) == 2
