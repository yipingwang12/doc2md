"""Tests for page deduplication."""

from pathlib import Path
from unittest.mock import MagicMock

from doc2md.models import Page
from doc2md.ordering.dedup import deduplicate


def _page(text: str, name: str = "test.png") -> Page:
    return Page(source_path=Path(f"/fake/{name}"), raw_text=text, extraction_method="surya")


class TestDeduplicate:
    def test_empty_input(self):
        assert deduplicate([]) == []

    def test_no_duplicates(self):
        pages = [_page("page one"), _page("page two")]
        result = deduplicate(pages)
        assert len(result) == 2

    def test_exact_hash_dedup(self):
        pages = [_page("same text"), _page("same text")]
        result = deduplicate(pages)
        assert len(result) == 1

    def test_fuzzy_dedup(self):
        text1 = "This is the content of page one with some details about the topic."
        text2 = "This is the content of page one with some details about the topic"  # missing period
        pages = [_page(text1), _page(text2)]
        result = deduplicate(pages)
        assert len(result) == 1

    def test_fuzzy_keeps_longer_text(self):
        short = "This is page content repeated here for testing purposes yes."
        long = "This is page content repeated here for testing purposes yes. Extra."
        pages = [_page(short, "a.png"), _page(long, "b.png")]
        result = deduplicate(pages)
        assert len(result) == 1
        assert result[0].raw_text == long

    def test_non_duplicates_preserved(self):
        pages = [_page("completely different text"), _page("another unique page")]
        result = deduplicate(pages)
        assert len(result) == 2

    def test_llm_fallback_for_borderline(self):
        # Texts with ~0.7-0.85 similarity
        text1 = "The quick brown fox jumps over the lazy dog near the river"
        text2 = "The quick brown fox jumps over the lazy cat near the river"
        mock_client = MagicMock()
        mock_client.generate_json.return_value = {"is_duplicate": True, "confidence": 0.9}
        pages = [_page(text1), _page(text2)]
        result = deduplicate(pages, llm_client=mock_client)
        assert len(result) == 1

    def test_llm_says_not_duplicate(self):
        # Texts with ~0.7-0.85 similarity to trigger LLM check
        text1 = "The quick brown fox jumps over the lazy dog near the river bank today"
        text2 = "A slow red cat crawls under the sleepy dog near the river bank today"
        mock_client = MagicMock()
        mock_client.generate_json.return_value = {"is_duplicate": False, "confidence": 0.3}
        pages = [_page(text1), _page(text2)]
        result = deduplicate(pages, llm_client=mock_client)
        assert len(result) == 2

    def test_single_page(self):
        result = deduplicate([_page("only one")])
        assert len(result) == 1
