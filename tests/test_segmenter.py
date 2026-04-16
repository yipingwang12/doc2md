"""Tests for rule-based page segmentation."""

from doc2md.analysis.segmenter import (
    FontProfile,
    build_font_profile,
    segment_page_blocks,
    segment_raw_text,
    _block_text,
    _dominant_size,
    _is_all_caps_heading,
    _is_boilerplate,
    _is_figure_panel_label,
    _line_starts_with_superscript_number,
    _rejoin_lines,
    _split_footnote_block,
)


def _text_block(text, size=10.0, y=100):
    return {
        "type": 0,
        "bbox": (0, y, 500, y + 20),
        "lines": [{
            "spans": [{"text": text, "size": size, "font": "TestFont", "flags": 0}],
        }],
    }


def _superscript_block(fn_num, body_text, fn_size=5.6, body_size=8.0, y=500):
    return {
        "type": 0,
        "bbox": (0, y, 500, y + 20),
        "lines": [{
            "spans": [
                {"text": fn_num, "size": fn_size, "font": "F", "flags": 0},
                {"text": " ", "size": body_size, "font": "F", "flags": 0},
                {"text": body_text, "size": body_size, "font": "F", "flags": 0},
            ],
        }],
    }


PROFILE = FontProfile(body_size=10.0, footnote_size=8.0, heading_sizes=[16.0, 12.0])


class TestBlockText:
    def test_extracts_text(self):
        block = _text_block("Hello world")
        assert _block_text(block) == "Hello world"

    def test_non_text_block_returns_empty(self):
        assert _block_text({"type": 1}) == ""

    def test_normalizes_ligatures(self):
        block = _text_block("scientiﬁc diﬃculty")
        assert _block_text(block) == "scientific difficulty"

    def test_multiline(self):
        block = {
            "type": 0,
            "bbox": (0, 0, 500, 40),
            "lines": [
                {"spans": [{"text": "line one", "size": 10.0, "font": "F", "flags": 0}]},
                {"spans": [{"text": "line two", "size": 10.0, "font": "F", "flags": 0}]},
            ],
        }
        assert _block_text(block) == "line one\nline two"


class TestDominantSize:
    def test_single_size(self):
        assert _dominant_size(_text_block("text", size=10.0)) == 10.0

    def test_majority_wins(self):
        block = {
            "type": 0,
            "bbox": (0, 0, 500, 20),
            "lines": [{
                "spans": [
                    {"text": "1", "size": 5.6, "font": "F", "flags": 0},
                    {"text": " A long footnote text here", "size": 8.0, "font": "F", "flags": 0},
                ],
            }],
        }
        assert _dominant_size(block) == 8.0

    def test_empty_block(self):
        assert _dominant_size({"lines": []}) == 0.0


class TestIsBoilerplate:
    def test_page_number(self):
        assert _is_boilerplate("345")
        assert _is_boilerplate("  42  ")

    def test_url(self):
        assert _is_boilerplate("https://doi.org/10.1017/foo Published online")

    def test_preprint_watermark_cc_by(self):
        assert _is_boilerplate("CC-BY 4.0 International license")

    def test_preprint_watermark_not_certified(self):
        assert _is_boilerplate("not certified by peer review) is the author/funder")

    def test_preprint_watermark_biorxiv(self):
        assert _is_boilerplate("posted on bioRxiv as a preprint")

    def test_preprint_watermark_copyright(self):
        assert _is_boilerplate("The copyright holder for this preprint (which was")

    def test_not_boilerplate(self):
        assert not _is_boilerplate("Regular text")
        assert not _is_boilerplate("12345")  # 5 digits, too long for page number


class TestIsFigurePanelLabel:
    def test_single_uppercase_letter(self):
        assert _is_figure_panel_label("A")
        assert _is_figure_panel_label("D")

    def test_single_lowercase_letter(self):
        assert _is_figure_panel_label("a")

    def test_page_fraction(self):
        assert _is_figure_panel_label("2/24")
        assert _is_figure_panel_label("15/30")

    def test_real_heading_not_panel(self):
        assert not _is_figure_panel_label("Results")
        assert not _is_figure_panel_label("INTRODUCTION")

    def test_two_letter_abbreviation_not_panel(self):
        assert not _is_figure_panel_label("AB")

    def test_panel_label_at_heading_size_discarded(self):
        blocks = [_text_block("A", size=16.0), _text_block("Body text here.", size=10.0)]
        result = segment_page_blocks(blocks, 0, PROFILE)
        texts = [b.text for b in result]
        assert "A" not in texts
        assert any("Body" in t for t in texts)

    def test_page_fraction_at_heading_size_discarded(self):
        blocks = [_text_block("2/24", size=16.0)]
        result = segment_page_blocks(blocks, 0, PROFILE)
        assert len(result) == 0

    def test_real_heading_not_discarded(self):
        blocks = [_text_block("Results", size=16.0)]
        result = segment_page_blocks(blocks, 0, PROFILE)
        assert len(result) == 1
        assert result[0].block_type == "heading"


class TestIsAllCapsHeading:
    def test_all_caps(self):
        assert _is_all_caps_heading("INTRODUCTION")
        assert _is_all_caps_heading("THE EXACT SCIENCES")

    def test_not_all_caps(self):
        assert not _is_all_caps_heading("Introduction")
        assert not _is_all_caps_heading("the exact sciences")

    def test_too_long(self):
        assert not _is_all_caps_heading("A" * 121)

    def test_too_short(self):
        assert not _is_all_caps_heading("AB")

    def test_multiline_rejected(self):
        assert not _is_all_caps_heading("HEADING\nSECOND LINE")

    def test_no_alpha(self):
        assert not _is_all_caps_heading("123")


class TestLineStartsWithSuperscriptNumber:
    def _line(self, fn_num, body_text, fn_size=5.6, body_size=8.0):
        return {
            "spans": [
                {"text": fn_num, "size": fn_size, "font": "F", "flags": 0},
                {"text": " ", "size": body_size, "font": "F", "flags": 0},
                {"text": body_text, "size": body_size, "font": "F", "flags": 0},
            ],
        }

    def test_superscript_number(self):
        assert _line_starts_with_superscript_number(self._line("1", "A footnote.")) == "1"

    def test_no_superscript(self):
        line = {"spans": [{"text": "1 Not a superscript", "size": 10.0, "font": "F", "flags": 0}]}
        assert _line_starts_with_superscript_number(line) is None

    def test_non_numeric(self):
        assert _line_starts_with_superscript_number(self._line("*", "A footnote.")) is None


class TestRejoinLines:
    def test_short_lines_joined(self):
        text = "The word\nmathēmatikē\nare\nnot\nidentical\nto\nthose"
        result = _rejoin_lines(text)
        assert "mathēmatikē are not identical to those" in result

    def test_normal_lines_preserved(self):
        text = "This is a normal length line that should not be changed.\nAnother normal line here."
        assert _rejoin_lines(text) == text

    def test_single_line(self):
        assert _rejoin_lines("hello") == "hello"

    def test_two_short_lines_not_joined(self):
        text = "AB\nCD"
        assert _rejoin_lines(text) == text


class TestSplitFootnoteBlock:
    def test_single_footnote(self):
        block = _superscript_block("1", "A footnote.")
        segments = _split_footnote_block(block)
        assert len(segments) == 1
        assert segments[0][0] == "1"

    def test_multiple_footnotes(self):
        block = {
            "type": 0,
            "bbox": (0, 500, 500, 560),
            "lines": [
                {"spans": [
                    {"text": "1", "size": 5.6, "font": "F", "flags": 0},
                    {"text": " First footnote text.", "size": 8.0, "font": "F", "flags": 0},
                ]},
                {"spans": [
                    {"text": "2", "size": 5.6, "font": "F", "flags": 0},
                    {"text": " Second footnote.", "size": 8.0, "font": "F", "flags": 0},
                ]},
            ],
        }
        segments = _split_footnote_block(block)
        assert len(segments) == 2
        assert segments[0][0] == "1"
        assert "First" in segments[0][1]
        assert segments[1][0] == "2"
        assert "Second" in segments[1][1]

    def test_footnote_with_continuation_lines(self):
        block = {
            "type": 0,
            "bbox": (0, 500, 500, 580),
            "lines": [
                {"spans": [
                    {"text": "1", "size": 5.6, "font": "F", "flags": 0},
                    {"text": " Start of footnote.", "size": 8.0, "font": "F", "flags": 0},
                ]},
                {"spans": [
                    {"text": "Continuation text.", "size": 8.0, "font": "F", "flags": 0},
                ]},
                {"spans": [
                    {"text": "2", "size": 5.6, "font": "F", "flags": 0},
                    {"text": " Next footnote.", "size": 8.0, "font": "F", "flags": 0},
                ]},
            ],
        }
        segments = _split_footnote_block(block)
        assert len(segments) == 2
        assert segments[0][0] == "1"
        assert "Continuation" in segments[0][1]
        assert segments[1][0] == "2"


class TestBuildFontProfile:
    def test_detects_body_size(self):
        pages = [[_text_block("Body " * 100, size=10.0), _text_block("Title", size=16.0)]]
        profile = build_font_profile(pages)
        assert profile.body_size == 10.0

    def test_detects_heading_sizes(self):
        pages = [[
            _text_block("Body " * 100, size=10.0),
            _text_block("H1", size=16.0),
            _text_block("H2", size=12.0),
        ]]
        profile = build_font_profile(pages)
        assert 16.0 in profile.heading_sizes
        assert 12.0 in profile.heading_sizes

    def test_detects_footnote_size(self):
        pages = [[
            _text_block("Body " * 100, size=10.0),
            _text_block("Footnote text", size=8.0),
        ]]
        profile = build_font_profile(pages)
        assert profile.footnote_size == 8.0

    def test_empty_pages(self):
        profile = build_font_profile([])
        assert profile.body_size == 0.0

    def test_repeated_lines_passed_through(self):
        profile = build_font_profile([[]], repeated_lines={"Author Name"})
        assert "Author Name" in profile.repeated_lines


class TestSegmentPageBlocks:
    def test_heading_detected(self):
        blocks = [_text_block("CHAPTER TITLE", size=16.0)]
        result = segment_page_blocks(blocks, 0, PROFILE)
        assert len(result) == 1
        assert result[0].block_type == "heading"
        assert result[0].heading_level == 1

    def test_body_detected(self):
        blocks = [_text_block("Regular paragraph.", size=10.0)]
        result = segment_page_blocks(blocks, 0, PROFILE)
        assert result[0].block_type == "body"

    def test_all_caps_heading_at_body_size(self):
        blocks = [_text_block("INTRODUCTION", size=10.0)]
        result = segment_page_blocks(blocks, 0, PROFILE)
        assert result[0].block_type == "heading"
        assert result[0].heading_level == 2

    def test_footnote_with_superscript(self):
        blocks = [_superscript_block("5", "A reference.")]
        result = segment_page_blocks(blocks, 0, PROFILE)
        footnotes = [b for b in result if b.block_type == "footnote"]
        assert len(footnotes) >= 1
        assert footnotes[0].footnote_id == "5"

    def test_footnote_by_size(self):
        blocks = [_text_block("10 See Smith (2020).", size=8.0, y=500)]
        result = segment_page_blocks(blocks, 0, PROFILE, page_height=800.0)
        footnotes = [b for b in result if b.block_type == "footnote"]
        assert len(footnotes) >= 1
        assert footnotes[0].footnote_id == "10"

    def test_footnote_continuation_merged(self):
        blocks = [
            _superscript_block("1", "Start of footnote.", y=500),
            _text_block("Continuation of footnote.", size=8.0, y=520),
        ]
        result = segment_page_blocks(blocks, 0, PROFILE, page_height=800.0)
        footnotes = [b for b in result if b.block_type == "footnote"]
        assert len(footnotes) == 1
        assert footnotes[0].footnote_id == "1"
        assert "Continuation" in footnotes[0].text

    def test_multiple_footnotes_in_one_block_split(self):
        block = {
            "type": 0,
            "bbox": (0, 500, 500, 580),
            "lines": [
                {"spans": [
                    {"text": "1", "size": 5.6, "font": "F", "flags": 0},
                    {"text": " First fn.", "size": 8.0, "font": "F", "flags": 0},
                ]},
                {"spans": [
                    {"text": "2", "size": 5.6, "font": "F", "flags": 0},
                    {"text": " Second fn.", "size": 8.0, "font": "F", "flags": 0},
                ]},
            ],
        }
        result = segment_page_blocks([block], 0, PROFILE, page_height=800.0)
        footnotes = [b for b in result if b.block_type == "footnote"]
        assert len(footnotes) == 2
        assert footnotes[0].footnote_id == "1"
        assert footnotes[1].footnote_id == "2"

    def test_boilerplate_filtered(self):
        blocks = [
            _text_block("345", size=10.0),
            _text_block("https://example.com/foo", size=6.0),
            _text_block("Body text.", size=10.0),
        ]
        result = segment_page_blocks(blocks, 0, PROFILE)
        assert len(result) == 1
        assert result[0].block_type == "body"

    def test_repeated_lines_filtered(self):
        profile = FontProfile(
            body_size=10.0, footnote_size=8.0, heading_sizes=[16.0],
            repeated_lines={"Author Name"},
        )
        blocks = [_text_block("Author Name", size=12.0)]
        result = segment_page_blocks(blocks, 0, profile)
        assert len(result) == 0

    def test_page_index_set(self):
        blocks = [_text_block("Text", size=10.0)]
        result = segment_page_blocks(blocks, 7, PROFILE)
        assert result[0].page_index == 7

    def test_caption_detected(self):
        blocks = [_text_block("Figure 3. A diagram showing results.", size=10.0)]
        result = segment_page_blocks(blocks, 0, PROFILE)
        assert result[0].block_type == "caption"

    def test_image_blocks_skipped(self):
        blocks = [{"type": 1, "bbox": (0, 0, 500, 200)}]
        result = segment_page_blocks(blocks, 0, PROFILE)
        assert len(result) == 0

    def test_mixed_page(self):
        blocks = [
            _text_block("CHAPTER ONE", size=16.0, y=50),
            _text_block("Body paragraph here.", size=10.0, y=100),
            _text_block("More body text follows.", size=10.0, y=200),
            _superscript_block("1", "A footnote reference.", y=600),
            _text_block("345", size=10.0, y=700),
        ]
        result = segment_page_blocks(blocks, 0, PROFILE, page_height=800.0)
        assert len(result) == 4
        assert result[0].block_type == "heading"
        assert result[1].block_type == "body"
        assert result[2].block_type == "body"
        assert result[3].block_type == "footnote"


class TestSegmentRawText:
    def test_body_paragraphs(self):
        text = "First paragraph.\n\nSecond paragraph."
        result = segment_raw_text(text, 0)
        assert len(result) == 2
        assert all(b.block_type == "body" for b in result)

    def test_all_caps_heading(self):
        text = "INTRODUCTION\n\nBody text."
        result = segment_raw_text(text, 0)
        assert result[0].block_type == "heading"
        assert result[0].heading_level == 2

    def test_footnote_bottom_half(self):
        text = "Para 1.\n\nPara 2.\n\n1 A footnote."
        result = segment_raw_text(text, 0)
        footnotes = [b for b in result if b.block_type == "footnote"]
        assert len(footnotes) == 1
        assert footnotes[0].footnote_id == "1"

    def test_caption(self):
        text = "Figure 1. A chart.\n\nBody text."
        result = segment_raw_text(text, 0)
        assert result[0].block_type == "caption"

    def test_boilerplate_filtered(self):
        text = "Body.\n\n123\n\nhttps://example.com"
        result = segment_raw_text(text, 0)
        assert len(result) == 1
        assert result[0].block_type == "body"

    def test_empty_text(self):
        assert segment_raw_text("", 0) == []
        assert segment_raw_text("   \n\n   ", 0) == []

    def test_page_index_set(self):
        result = segment_raw_text("text", 3)
        assert result[0].page_index == 3
