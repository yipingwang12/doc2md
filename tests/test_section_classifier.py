"""Tests for academic paper section classification."""

from doc2md.models import TextBlock
from doc2md.papers.section_classifier import (
    CANONICAL_SECTIONS,
    classify_section_heading,
    label_blocks_by_section,
)


class TestCanonicalSections:
    def test_has_expected_labels(self):
        labels = set(CANONICAL_SECTIONS.values())
        assert "abstract" in labels
        assert "introduction" in labels
        assert "methods" in labels
        assert "results" in labels
        assert "discussion" in labels
        assert "references" in labels


class TestClassifySectionHeading:
    def test_exact_matches(self):
        assert classify_section_heading("Abstract") == "abstract"
        assert classify_section_heading("Introduction") == "introduction"
        assert classify_section_heading("References") == "references"

    def test_case_insensitive(self):
        assert classify_section_heading("ABSTRACT") == "abstract"
        assert classify_section_heading("abstract") == "abstract"
        assert classify_section_heading("INTRODUCTION") == "introduction"

    def test_common_variants(self):
        assert classify_section_heading("Materials and Methods") == "methods"
        assert classify_section_heading("Methods") == "methods"
        assert classify_section_heading("Experimental Procedures") == "methods"
        assert classify_section_heading("Results and Discussion") == "results"
        assert classify_section_heading("Conclusions") == "discussion"
        assert classify_section_heading("Conclusion") == "discussion"
        assert classify_section_heading("Discussion") == "discussion"
        assert classify_section_heading("Supplemental Information") == "supplementary"
        assert classify_section_heading("Supplementary Materials") == "supplementary"
        assert classify_section_heading("Author Contributions") == "metadata"
        assert classify_section_heading("Acknowledgments") == "metadata"
        assert classify_section_heading("Acknowledgements") == "metadata"

    def test_unknown_heading_returns_none(self):
        assert classify_section_heading("Figure 1") is None
        assert classify_section_heading("Table 2") is None
        assert classify_section_heading("") is None
        assert classify_section_heading("Random text that is not a section") is None

    def test_strips_whitespace(self):
        assert classify_section_heading("  Abstract  ") == "abstract"

    def test_numbered_sections(self):
        # Some journals prefix with numbers: "1. Introduction"
        assert classify_section_heading("1. Introduction") == "introduction"
        assert classify_section_heading("2. Materials and Methods") == "methods"


class TestLabelBlocksBySection:
    def _heading(self, text, page=0):
        return TextBlock(text=text, block_type="heading", page_index=page)

    def _body(self, text, page=0):
        return TextBlock(text=text, block_type="body", page_index=page)

    def test_empty_returns_empty(self):
        assert label_blocks_by_section([]) == []

    def test_blocks_before_first_heading_get_preamble(self):
        blocks = [self._body("Some intro text"), self._heading("Abstract")]
        result = label_blocks_by_section(blocks)
        labels = [label for _, label in result]
        assert labels[0] == "preamble"
        assert labels[1] == "abstract"

    def test_blocks_inherit_section_from_last_heading(self):
        blocks = [
            self._heading("Abstract"),
            self._body("The abstract text."),
            self._body("More abstract text."),
            self._heading("Introduction"),
            self._body("Intro body."),
        ]
        result = label_blocks_by_section(blocks)
        labels = [label for _, label in result]
        assert labels == ["abstract", "abstract", "abstract", "introduction", "introduction"]

    def test_unknown_heading_does_not_change_section(self):
        blocks = [
            self._heading("Abstract"),
            self._body("Abstract body."),
            self._heading("Figure 1"),      # not a known section
            self._body("Figure caption."),
        ]
        result = label_blocks_by_section(blocks)
        labels = [label for _, label in result]
        assert labels[2] == "abstract"   # heading not recognised → no section change
        assert labels[3] == "abstract"

    def test_section_label_set_on_blocks(self):
        blocks = [
            self._heading("Methods"),
            self._body("We used CRISPR."),
        ]
        result = label_blocks_by_section(blocks)
        for block, label in result:
            assert block.section_label == label

    def test_returns_original_block_objects(self):
        b = self._body("text")
        result = label_blocks_by_section([b])
        assert result[0][0] is b
