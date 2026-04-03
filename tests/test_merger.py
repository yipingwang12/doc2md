"""Tests for page-to-chapter merging."""

from doc2md.assembly.merger import merge_chapter_text
from doc2md.models import Chapter, TextBlock


def _block(text: str, btype: str = "body", page: int = 0) -> TextBlock:
    return TextBlock(text=text, block_type=btype, page_index=page)


class TestMergeChapterText:
    def test_merges_consecutive_body(self):
        ch = Chapter(
            title="Ch1", heading_level=1,
            blocks=[_block("first part", page=0), _block("second part", page=1)],
        )
        result = merge_chapter_text(ch)
        assert len(result.blocks) == 1
        assert "first part" in result.blocks[0].text
        assert "second part" in result.blocks[0].text

    def test_preserves_non_body_blocks(self):
        ch = Chapter(
            title="Ch1", heading_level=1,
            blocks=[
                _block("body1"),
                _block("Section 2", "heading"),
                _block("body2"),
            ],
        )
        result = merge_chapter_text(ch)
        assert len(result.blocks) == 3

    def test_fixes_hyphenation(self):
        ch = Chapter(
            title="Ch1", heading_level=1,
            blocks=[_block("con-\ntinue here")],
        )
        result = merge_chapter_text(ch)
        assert "continue" in result.blocks[0].text

    def test_empty_chapter(self):
        ch = Chapter(title="Empty", heading_level=1, blocks=[])
        result = merge_chapter_text(ch)
        assert result.blocks == []

    def test_preserves_metadata(self):
        ch = Chapter(
            title="Ch1", heading_level=2,
            blocks=[_block("text")],
            footnotes={"1": "note"},
            bibliography=["ref1"],
        )
        result = merge_chapter_text(ch)
        assert result.title == "Ch1"
        assert result.heading_level == 2
        assert result.footnotes == {"1": "note"}
        assert result.bibliography == ["ref1"]

    def test_joins_broken_sentences(self):
        ch = Chapter(
            title="Ch1", heading_level=1,
            blocks=[_block("the quick brown", page=0), _block("fox jumps over", page=1)],
        )
        result = merge_chapter_text(ch)
        assert "the quick brown fox jumps over" in result.blocks[0].text
