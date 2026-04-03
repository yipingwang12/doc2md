"""Tests for header/footer stripping and text cleaning."""

from pathlib import Path

from doc2md.assembly.cleaner import (
    detect_repeated_lines,
    fix_hyphenation,
    join_broken_sentences,
    strip_headers_footers,
)
from doc2md.models import Page


def _page(text: str) -> Page:
    return Page(source_path=Path("/fake.pdf"), raw_text=text, extraction_method="pymupdf")


class TestDetectRepeatedLines:
    def test_finds_repeated_header(self):
        pages = [_page("HEADER\nbody1"), _page("HEADER\nbody2"), _page("HEADER\nbody3")]
        repeated = detect_repeated_lines(pages)
        assert "HEADER" in repeated

    def test_finds_repeated_footer(self):
        pages = [_page("body1\nFOOTER"), _page("body2\nFOOTER"), _page("body3\nFOOTER")]
        repeated = detect_repeated_lines(pages)
        assert "FOOTER" in repeated

    def test_no_repeats(self):
        pages = [_page("unique1"), _page("unique2"), _page("unique3")]
        repeated = detect_repeated_lines(pages)
        assert len(repeated) == 0

    def test_ignores_below_threshold(self):
        pages = [_page("HEADER\nbody1"), _page("HEADER\nbody2")]
        repeated = detect_repeated_lines(pages, min_occurrences=3)
        assert len(repeated) == 0


class TestStripHeadersFooters:
    def test_removes_repeated(self):
        pages = [_page("HEADER\ncontent\nFOOTER")]
        result = strip_headers_footers(pages, {"HEADER", "FOOTER"})
        assert "HEADER" not in result[0].raw_text
        assert "FOOTER" not in result[0].raw_text
        assert "content" in result[0].raw_text

    def test_no_repeated_returns_unchanged(self):
        pages = [_page("content")]
        result = strip_headers_footers(pages, set())
        assert result[0].raw_text == "content"


class TestFixHyphenation:
    def test_joins_hyphenated_word(self):
        assert fix_hyphenation("con-\ntinue") == "continue"

    def test_preserves_real_hyphens(self):
        assert fix_hyphenation("well-known\nfact") == "well-known\nfact"

    def test_no_hyphenation(self):
        assert fix_hyphenation("normal text") == "normal text"


class TestJoinBrokenSentences:
    def test_joins_mid_sentence(self):
        result = join_broken_sentences("the quick brown", "fox jumps")
        assert result == "the quick brown fox jumps"

    def test_preserves_sentence_boundary(self):
        result = join_broken_sentences("End of sentence.", "Start of next.")
        assert "\n\n" in result

    def test_empty_texts(self):
        result = join_broken_sentences("", "text")
        assert "text" in result

    def test_uppercase_start_not_joined(self):
        result = join_broken_sentences("end of paragraph", "New paragraph starts")
        assert "\n\n" in result
