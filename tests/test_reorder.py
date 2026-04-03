"""Tests for page reordering."""

from pathlib import Path
from unittest.mock import MagicMock

from doc2md.models import Page
from doc2md.ordering.reorder import detect_page_numbers, find_page_gaps, reorder_pages


def _page(text: str, page_num: int | None = None) -> Page:
    return Page(
        source_path=Path("/fake/test.png"),
        raw_text=text,
        extraction_method="surya",
        page_number=page_num,
    )


class TestReorderPages:
    def test_already_ordered(self):
        pages = [_page("a", 1), _page("b", 2), _page("c", 3)]
        result = reorder_pages(pages)
        assert [p.page_number for p in result] == [1, 2, 3]

    def test_out_of_order(self):
        pages = [_page("c", 3), _page("a", 1), _page("b", 2)]
        result = reorder_pages(pages)
        assert [p.page_number for p in result] == [1, 2, 3]

    def test_unnumbered_first(self):
        pages = [_page("numbered", 5), _page("front matter", None)]
        result = reorder_pages(pages)
        assert result[0].page_number is None
        assert result[1].page_number == 5

    def test_mixed_numbered_unnumbered(self):
        pages = [_page("p3", 3), _page("intro", None), _page("p1", 1), _page("preface", None)]
        result = reorder_pages(pages)
        # Unnumbered first (in original order), then numbered sorted
        assert result[0].raw_text == "intro"
        assert result[1].raw_text == "preface"
        assert result[2].page_number == 1
        assert result[3].page_number == 3

    def test_empty(self):
        assert reorder_pages([]) == []


class TestFindPageGaps:
    def test_no_gaps(self):
        pages = [_page("", 1), _page("", 2), _page("", 3)]
        assert find_page_gaps(pages) == []

    def test_with_gaps(self):
        pages = [_page("", 1), _page("", 3), _page("", 7)]
        assert find_page_gaps(pages) == [2, 4, 5, 6]

    def test_single_page(self):
        assert find_page_gaps([_page("", 5)]) == []

    def test_no_numbered_pages(self):
        assert find_page_gaps([_page("", None)]) == []


class TestDetectPageNumbers:
    def test_assigns_page_numbers(self):
        mock_client = MagicMock()
        mock_client.generate_json.return_value = {"page_number": 42, "confidence": 0.95}
        pages = [_page("some text with 42 at bottom")]
        result = detect_page_numbers(pages, mock_client)
        assert result[0].page_number == 42

    def test_skips_already_numbered(self):
        mock_client = MagicMock()
        pages = [_page("text", page_num=10)]
        result = detect_page_numbers(pages, mock_client)
        assert result[0].page_number == 10
        mock_client.generate_json.assert_not_called()

    def test_handles_null_response(self):
        mock_client = MagicMock()
        mock_client.generate_json.return_value = {"page_number": None, "confidence": 0.1}
        pages = [_page("no page number")]
        result = detect_page_numbers(pages, mock_client)
        assert result[0].page_number is None

    def test_handles_llm_failure(self):
        mock_client = MagicMock()
        mock_client.generate_json.side_effect = RuntimeError("LLM down")
        pages = [_page("text")]
        result = detect_page_numbers(pages, mock_client)
        assert result[0].page_number is None
