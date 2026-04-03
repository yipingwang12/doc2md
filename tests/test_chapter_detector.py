"""Tests for chapter boundary detection."""

from unittest.mock import MagicMock

from doc2md.analysis.chapter_detector import detect_chapters
from doc2md.models import TextBlock


def _block(text: str, btype: str = "body", level: int | None = None, page: int = 0) -> TextBlock:
    return TextBlock(text=text, block_type=btype, page_index=page, heading_level=level)


class TestDetectChapters:
    def test_no_headings_returns_single_chapter(self):
        blocks = [_block("para 1"), _block("para 2")]
        mock_client = MagicMock()
        chapters = detect_chapters(blocks, mock_client)
        assert len(chapters) == 1
        assert chapters[0].title == "Untitled"
        mock_client.generate_json.assert_not_called()

    def test_llm_detects_chapters(self):
        blocks = [
            _block("Chapter 1: Intro", "heading", 1),
            _block("Body text 1"),
            _block("Chapter 2: Methods", "heading", 1),
            _block("Body text 2"),
        ]
        mock_client = MagicMock()
        mock_client.generate_json.return_value = [
            {"heading_index": 0, "is_chapter_start": True},
            {"heading_index": 1, "is_chapter_start": True},
        ]
        chapters = detect_chapters(blocks, mock_client)
        assert len(chapters) == 2
        assert chapters[0].title == "Chapter 1: Intro"
        assert chapters[1].title == "Chapter 2: Methods"

    def test_front_matter_before_first_chapter(self):
        blocks = [
            _block("Preface text"),
            _block("Chapter 1", "heading", 1),
            _block("Body"),
        ]
        mock_client = MagicMock()
        # heading_index=0 refers to first heading in headings list (which is block index 1)
        mock_client.generate_json.return_value = [
            {"heading_index": 0, "is_chapter_start": True},
        ]
        chapters = detect_chapters(blocks, mock_client)
        assert len(chapters) == 2
        assert chapters[0].title == "Front Matter"
        assert chapters[0].blocks[0].text == "Preface text"
        assert chapters[1].title == "Chapter 1"

    def test_llm_failure_falls_back_to_heading_levels(self):
        blocks = [
            _block("Ch 1", "heading", 1),
            _block("text"),
            _block("Ch 2", "heading", 1),
            _block("more text"),
        ]
        mock_client = MagicMock()
        mock_client.generate_json.side_effect = RuntimeError("LLM down")
        chapters = detect_chapters(blocks, mock_client)
        assert len(chapters) == 2

    def test_no_chapter_starts_detected(self):
        blocks = [
            _block("Section A", "heading", 2),
            _block("text"),
        ]
        mock_client = MagicMock()
        mock_client.generate_json.return_value = []
        chapters = detect_chapters(blocks, mock_client)
        # Falls back to single chapter with first heading
        assert len(chapters) == 1
        assert chapters[0].title == "Section A"

    def test_chapter_blocks_assigned_correctly(self):
        blocks = [
            _block("Ch 1", "heading", 1),
            _block("para 1"),
            _block("para 2"),
            _block("Ch 2", "heading", 1),
            _block("para 3"),
        ]
        mock_client = MagicMock()
        mock_client.generate_json.return_value = [
            {"heading_index": 0, "is_chapter_start": True},
            {"heading_index": 1, "is_chapter_start": True},
        ]
        chapters = detect_chapters(blocks, mock_client)
        assert len(chapters[0].blocks) == 2  # para 1, para 2
        assert len(chapters[1].blocks) == 1  # para 3
