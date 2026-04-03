"""Tests for citation linking."""

from doc2md.assembly.citations import detect_citation_style, link_citations
from doc2md.models import Chapter, TextBlock


def _block(text: str, btype: str = "body") -> TextBlock:
    return TextBlock(text=text, block_type=btype, page_index=0)


class TestLinkCitations:
    def test_extracts_references(self):
        ch = Chapter(
            title="Ch1", heading_level=1,
            blocks=[
                _block("Body text [1]"),
                _block("Smith J. (2020). Title. Journal.", "reference"),
            ],
        )
        result = link_citations(ch)
        assert len(result.bibliography) == 1
        assert "Smith" in result.bibliography[0]
        # Reference block removed from body
        assert all(b.block_type != "reference" for b in result.blocks)

    def test_no_references(self):
        ch = Chapter(title="Ch1", heading_level=1, blocks=[_block("plain text")])
        result = link_citations(ch)
        assert result.bibliography == []

    def test_preserves_existing_bibliography(self):
        ch = Chapter(
            title="Ch1", heading_level=1,
            blocks=[_block("New ref.", "reference")],
            bibliography=["Existing ref."],
        )
        result = link_citations(ch)
        assert len(result.bibliography) == 2


class TestDetectCitationStyle:
    def test_bracket_number(self):
        text = "As shown in [1], and confirmed by [2] and [3]."
        assert detect_citation_style(text) == "bracket_number"

    def test_author_year(self):
        text = "According to (Smith, 2020) and (Jones, 2019)."
        assert detect_citation_style(text) == "author_year"

    def test_author_year_et_al(self):
        text = "Work by (Smith et al., 2020) confirmed this."
        assert detect_citation_style(text) == "author_year"

    def test_unknown(self):
        assert detect_citation_style("no citations here") == "unknown"

    def test_mixed_prefers_majority(self):
        text = "See [1], [2], [3] and (Smith, 2020)."
        assert detect_citation_style(text) == "bracket_number"
