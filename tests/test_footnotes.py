"""Tests for footnote linking."""

from doc2md.assembly.footnotes import link_footnotes
from doc2md.models import Chapter, TextBlock


def _block(text: str, btype: str = "body", fid: str | None = None) -> TextBlock:
    return TextBlock(text=text, block_type=btype, page_index=0, footnote_id=fid)


class TestLinkFootnotes:
    def test_extracts_footnotes(self):
        ch = Chapter(
            title="Ch1", heading_level=1,
            blocks=[
                _block("Body text with1 reference"),
                _block("This is footnote one.", "footnote", "1"),
            ],
        )
        result = link_footnotes(ch)
        assert "1" in result.footnotes
        assert result.footnotes["1"] == "This is footnote one."
        # Footnote block should be removed from body
        assert all(b.block_type != "footnote" for b in result.blocks)

    def test_preserves_non_footnote_blocks(self):
        ch = Chapter(
            title="Ch1", heading_level=1,
            blocks=[_block("body"), _block("Section", "heading")],
        )
        result = link_footnotes(ch)
        assert len(result.blocks) == 2

    def test_no_footnotes(self):
        ch = Chapter(title="Ch1", heading_level=1, blocks=[_block("plain text")])
        result = link_footnotes(ch)
        assert result.footnotes == {}

    def test_multiple_footnotes(self):
        ch = Chapter(
            title="Ch1", heading_level=1,
            blocks=[
                _block("Text here"),
                _block("First footnote.", "footnote", "1"),
                _block("Second footnote.", "footnote", "2"),
            ],
        )
        result = link_footnotes(ch)
        assert len(result.footnotes) == 2
        assert result.footnotes["1"] == "First footnote."
        assert result.footnotes["2"] == "Second footnote."

    def test_merges_with_existing_footnotes(self):
        ch = Chapter(
            title="Ch1", heading_level=1,
            blocks=[_block("Note text.", "footnote", "2")],
            footnotes={"1": "Existing note."},
        )
        result = link_footnotes(ch)
        assert "1" in result.footnotes
        assert "2" in result.footnotes
