"""Tests for block classification."""

from pathlib import Path
from unittest.mock import MagicMock

from doc2md.analysis.classifier import classify_page, classify_pages
from doc2md.models import Page


def _page(text: str) -> Page:
    return Page(source_path=Path("/fake.pdf"), raw_text=text, extraction_method="pymupdf")


class TestClassifyPage:
    def test_classifies_blocks(self):
        mock_client = MagicMock()
        mock_client.generate_json.return_value = [
            {"text": "Chapter 1", "type": "heading", "heading_level": 1, "footnote_id": None},
            {"text": "Body text here.", "type": "body", "heading_level": None, "footnote_id": None},
        ]
        blocks = classify_page(_page("Chapter 1\nBody text here."), 0, mock_client)
        assert len(blocks) == 2
        assert blocks[0].block_type == "heading"
        assert blocks[0].heading_level == 1
        assert blocks[1].block_type == "body"

    def test_empty_page_returns_empty(self):
        mock_client = MagicMock()
        blocks = classify_page(_page(""), 0, mock_client)
        assert blocks == []
        mock_client.generate_json.assert_not_called()

    def test_llm_failure_returns_body(self):
        mock_client = MagicMock()
        mock_client.generate_json.side_effect = RuntimeError("LLM error")
        page = _page("Some text")
        blocks = classify_page(page, 0, mock_client)
        assert len(blocks) == 1
        assert blocks[0].block_type == "body"
        assert blocks[0].text == "Some text"

    def test_invalid_block_type_defaults_to_body(self):
        mock_client = MagicMock()
        mock_client.generate_json.return_value = [
            {"text": "text", "type": "unknown_type", "heading_level": None, "footnote_id": None},
        ]
        blocks = classify_page(_page("text"), 0, mock_client)
        assert blocks[0].block_type == "body"

    def test_footnote_id_converted_to_string(self):
        mock_client = MagicMock()
        mock_client.generate_json.return_value = [
            {"text": "note", "type": "footnote", "heading_level": None, "footnote_id": 3},
        ]
        blocks = classify_page(_page("note"), 0, mock_client)
        assert blocks[0].footnote_id == "3"

    def test_single_dict_response_wrapped(self):
        mock_client = MagicMock()
        mock_client.generate_json.return_value = {
            "text": "solo", "type": "body", "heading_level": None, "footnote_id": None,
        }
        blocks = classify_page(_page("solo"), 0, mock_client)
        assert len(blocks) == 1


class TestClassifyPages:
    def test_processes_multiple_pages(self):
        mock_client = MagicMock()
        mock_client.generate_json.side_effect = [
            [{"text": "p1", "type": "body", "heading_level": None, "footnote_id": None}],
            [{"text": "p2", "type": "heading", "heading_level": 2, "footnote_id": None}],
        ]
        pages = [_page("page1"), _page("page2")]
        blocks = classify_pages(pages, mock_client)
        assert len(blocks) == 2
        assert blocks[0].page_index == 0
        assert blocks[1].page_index == 1
