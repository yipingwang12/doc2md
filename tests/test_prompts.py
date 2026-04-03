"""Tests for LLM prompt templates."""

from doc2md.analysis.prompts import (
    format_block_classification,
    format_chapter_boundary,
    format_duplicate_detection,
    format_page_number,
)


class TestPromptFormatting:
    def test_page_number_prompt(self):
        result = format_page_number("Some page text here")
        assert "Some page text here" in result
        assert "page_number" in result
        assert "confidence" in result

    def test_page_number_truncates_to_500(self):
        long_text = "x" * 1000
        result = format_page_number(long_text)
        # The text in the prompt should be truncated
        assert "x" * 500 in result
        assert "x" * 501 not in result

    def test_block_classification_prompt(self):
        result = format_block_classification("Chapter 1\nSome body text.")
        assert "Chapter 1" in result
        assert "heading" in result
        assert "footnote" in result

    def test_chapter_boundary_prompt(self):
        result = format_chapter_boundary('[{"text": "Chapter 1"}]')
        assert "Chapter 1" in result
        assert "is_chapter_start" in result

    def test_duplicate_detection_prompt(self):
        result = format_duplicate_detection("Page A text", "Page B text")
        assert "Page A text" in result
        assert "Page B text" in result
        assert "is_duplicate" in result

    def test_duplicate_detection_truncates_to_300(self):
        long_a = "a" * 500
        long_b = "b" * 500
        result = format_duplicate_detection(long_a, long_b)
        assert "a" * 300 in result
        assert "a" * 301 not in result
