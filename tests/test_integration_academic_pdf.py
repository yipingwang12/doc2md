"""Integration tests capturing lessons from the Cambridge History of Science improvement session.

These tests verify the full pipeline handles real-world academic PDF patterns:
- Font-based classification beats LLM for digital PDFs
- PyMuPDF block dicts provide natural paragraph boundaries
- Multiple footnotes merged into single PyMuPDF blocks need splitting
- Orphan footnote continuations across page breaks need merging
- Running headers/footers/page numbers must be stripped
- Ligature characters must be normalized
- Broken line wrapping from centered/indented text must be rejoined
- Page-break mid-sentence must be joined (footnotes before merge)
- Pipeline stage ordering: link_footnotes before merge_chapter_text
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz
import pytest

from doc2md.analysis.classifier import classify_pages
from doc2md.analysis.segmenter import (
    FontProfile,
    build_font_profile,
    segment_page_blocks,
)
from doc2md.assembly.cleaner import (
    detect_boilerplate_lines,
    detect_repeated_lines,
    normalize_ligatures,
    strip_headers_footers,
)
from doc2md.assembly.footnotes import link_footnotes
from doc2md.assembly.merger import merge_chapter_text
from doc2md.analysis.chapter_detector import detect_chapters
from doc2md.config import Config
from doc2md.extract.pdf_extract import extract_pages
from doc2md.models import Chapter, Page, TextBlock
from doc2md.pipeline import process_file


# ---------------------------------------------------------------------------
# Helpers: build realistic PyMuPDF block dicts
# ---------------------------------------------------------------------------

def _span(text, size=10.7, font="Body"):
    return {"text": text, "size": size, "font": font, "flags": 0}


def _line(*spans):
    return {"spans": list(spans)}


def _block(lines, y=100):
    return {
        "type": 0,
        "bbox": (72, y, 540, y + 14 * len(lines)),
        "lines": lines,
    }


def _img_block(y=200):
    return {"type": 1, "bbox": (72, y, 540, y + 100)}


def _page_obj(text, block_dicts, page_height=842.0):
    return Page(
        source_path=Path("/fake.pdf"),
        raw_text=text,
        extraction_method="pymupdf",
        block_dicts=block_dicts,
        page_height=page_height,
    )


# Realistic font sizes matching Cambridge University Press academic PDFs
BODY = 10.7
HEADING_1 = 15.9
HEADING_2 = 12.0  # also used for author names
FOOTNOTE = 8.0
SUPERSCRIPT = 5.6
PAGE_NUM = 9.7
URL = 6.0


# ---------------------------------------------------------------------------
# Test: PDF extraction captures block dicts
# ---------------------------------------------------------------------------

class TestPdfExtractBlockDicts:
    def test_extract_pages_includes_block_dicts(self, tmp_path):
        path = tmp_path / "test.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Hello world", fontsize=11)
        doc.save(path)
        doc.close()

        pages = extract_pages(path)
        assert pages[0].block_dicts is not None
        assert len(pages[0].block_dicts) > 0
        assert pages[0].page_height > 0

    def test_block_dicts_preserved_after_header_stripping(self, tmp_path):
        path = tmp_path / "test.pdf"
        doc = fitz.open()
        for _ in range(3):
            page = doc.new_page()
            page.insert_text((72, 72), "HEADER\nBody text\nFOOTER", fontsize=11)
        doc.save(path)
        doc.close()

        pages = extract_pages(path)
        repeated = detect_repeated_lines(pages)
        cleaned = strip_headers_footers(pages, repeated)
        assert all(p.block_dicts is not None for p in cleaned)
        assert all(p.page_height > 0 for p in cleaned)


# ---------------------------------------------------------------------------
# Test: Font profile detection across pages
# ---------------------------------------------------------------------------

class TestFontProfileAcademic:
    def _academic_page_blocks(self, page_num=1):
        """Simulate a typical academic page with heading, body, footnotes, and boilerplate."""
        blocks = []
        if page_num == 1:
            blocks.append(_block([_line(_span("18", size=23.9))], y=57))
            blocks.append(_block([_line(_span("CHAPTER TITLE", size=HEADING_1))], y=101))
            blocks.append(_block([_line(_span("Author Name", size=HEADING_2))], y=129))
        blocks.append(_block([
            _line(_span("Body text paragraph one. " * 5, size=BODY)),
            _line(_span("More body text continues here. " * 5, size=BODY)),
        ], y=226))
        blocks.append(_block([
            _line(_span("1", size=SUPERSCRIPT), _span(" A footnote reference with enough text to outweigh the URL.", size=FOOTNOTE)),
            _line(_span("See also Smith (2020) for further discussion of this important topic.", size=FOOTNOTE)),
        ], y=532))
        blocks.append(_block([_line(_span(str(340 + page_num), size=PAGE_NUM))], y=607))
        blocks.append(_block([
            _line(_span("https://doi.org/10.1017/example Published online", size=URL)),
        ], y=627))
        return blocks

    def test_identifies_body_as_most_common_size(self):
        pages = [self._academic_page_blocks(i) for i in range(1, 4)]
        profile = build_font_profile(pages)
        assert profile.body_size == BODY

    def test_identifies_footnote_size(self):
        pages = [self._academic_page_blocks(i) for i in range(1, 4)]
        profile = build_font_profile(pages)
        assert profile.footnote_size == FOOTNOTE

    def test_identifies_heading_sizes(self):
        pages = [self._academic_page_blocks(i) for i in range(1, 4)]
        profile = build_font_profile(pages)
        assert HEADING_1 in profile.heading_sizes


# ---------------------------------------------------------------------------
# Test: Realistic page segmentation
# ---------------------------------------------------------------------------

class TestSegmentAcademicPage:
    """Tests for patterns found in Cambridge History of Science PDFs."""

    PROFILE = FontProfile(
        body_size=BODY,
        footnote_size=FOOTNOTE,
        heading_sizes=[23.9, HEADING_1, HEADING_2],
        repeated_lines={
            "https://doi.org/10.1017/example Published online",
            "Greek Mathematics",
            "Nathan Sidoli",
        },
    )

    def test_chapter_title_detected_as_heading(self):
        blocks = [_block([_line(_span("CHAPTER TITLE", size=HEADING_1))], y=101)]
        result = segment_page_blocks(blocks, 0, self.PROFILE, page_height=842.0)
        assert result[0].block_type == "heading"
        assert result[0].heading_level == 2  # second-largest heading size

    def test_all_caps_section_heading_at_body_size(self):
        blocks = [_block([_line(_span("OBSCURE ORIGINS", size=BODY))], y=100)]
        result = segment_page_blocks(blocks, 0, self.PROFILE, page_height=842.0)
        assert result[0].block_type == "heading"
        assert result[0].heading_level == 2

    def test_url_footer_filtered(self):
        blocks = [_block([
            _line(_span("https://doi.org/10.1017/example Published online", size=URL)),
        ], y=627)]
        result = segment_page_blocks(blocks, 0, self.PROFILE, page_height=842.0)
        assert len(result) == 0

    def test_page_number_filtered(self):
        blocks = [_block([_line(_span("345", size=PAGE_NUM))], y=607)]
        result = segment_page_blocks(blocks, 0, self.PROFILE, page_height=842.0)
        assert len(result) == 0

    def test_running_header_filtered(self):
        blocks = [_block([_line(_span("Greek Mathematics", size=BODY))], y=33)]
        result = segment_page_blocks(blocks, 0, self.PROFILE, page_height=842.0)
        assert len(result) == 0

    def test_author_name_running_header_filtered(self):
        """Author name appears on alternating pages as running header."""
        blocks = [_block([_line(_span("Nathan Sidoli", size=HEADING_2))], y=33)]
        result = segment_page_blocks(blocks, 0, self.PROFILE, page_height=842.0)
        assert len(result) == 0

    def test_mixed_boilerplate_block_filtered(self):
        """Block with repeated text + page number (e.g. 'Greek Mathematics\\n347')."""
        blocks = [_block([
            _line(_span("Greek Mathematics", size=BODY)),
            _line(_span("347", size=PAGE_NUM)),
        ], y=600)]
        result = segment_page_blocks(blocks, 0, self.PROFILE, page_height=842.0)
        assert len(result) == 0

    def test_footnote_with_superscript_number(self):
        blocks = [_block([
            _line(_span("5", size=SUPERSCRIPT), _span(" See Smith (2020).", size=FOOTNOTE)),
        ], y=500)]
        result = segment_page_blocks(blocks, 0, self.PROFILE, page_height=842.0)
        assert result[0].block_type == "footnote"
        assert result[0].footnote_id == "5"

    def test_multiple_footnotes_in_single_block_split(self):
        """PyMuPDF often merges adjacent footnotes into one block."""
        blocks = [_block([
            _line(_span("1", size=SUPERSCRIPT), _span(" First reference.", size=FOOTNOTE)),
            _line(_span("(Publisher, 2001).", size=FOOTNOTE)),
            _line(_span("2", size=SUPERSCRIPT), _span(" Second reference.", size=FOOTNOTE)),
            _line(_span("pp. 107-32.", size=FOOTNOTE)),
        ], y=500)]
        result = segment_page_blocks(blocks, 0, self.PROFILE, page_height=842.0)
        footnotes = [b for b in result if b.block_type == "footnote"]
        assert len(footnotes) == 2
        assert footnotes[0].footnote_id == "1"
        assert "(Publisher, 2001)" in footnotes[0].text
        assert footnotes[1].footnote_id == "2"
        assert "pp. 107-32" in footnotes[1].text

    def test_many_footnotes_in_single_block(self):
        """Real-world case: 5+ footnotes merged in one PyMuPDF block."""
        lines = []
        for n in range(8, 15):
            lines.append(_line(
                _span(str(n), size=SUPERSCRIPT),
                _span(f" Footnote {n} text here.", size=FOOTNOTE),
            ))
        blocks = [_block(lines, y=400)]
        result = segment_page_blocks(blocks, 0, self.PROFILE, page_height=842.0)
        footnotes = [b for b in result if b.block_type == "footnote"]
        assert len(footnotes) == 7
        for i, fn in enumerate(footnotes):
            assert fn.footnote_id == str(8 + i)

    def test_body_text_preserved(self):
        blocks = [_block([
            _line(_span("The origins of Greek mathematics were a favorite topic. " * 3, size=BODY)),
        ], y=200)]
        result = segment_page_blocks(blocks, 0, self.PROFILE, page_height=842.0)
        assert result[0].block_type == "body"
        assert "origins of Greek mathematics" in result[0].text

    def test_image_block_skipped(self):
        blocks = [_img_block()]
        result = segment_page_blocks(blocks, 0, self.PROFILE, page_height=842.0)
        assert len(result) == 0

    def test_full_academic_page(self):
        """Simulate a realistic academic page with all block types."""
        blocks = [
            _block([_line(_span("OBSCURE ORIGINS", size=BODY))], y=50),
            _block([
                _line(_span("The origins of Greek mathematics. " * 4, size=BODY)),
                _line(_span("Multiple lines of body text. " * 4, size=BODY)),
            ], y=80),
            _block([
                _line(_span("Further discussion continues. " * 4, size=BODY)),
            ], y=300),
            _img_block(y=450),
            _block([
                _line(_span("5", size=SUPERSCRIPT), _span(" See Szabó (1978).", size=FOOTNOTE)),
                _line(_span("6", size=SUPERSCRIPT), _span(" Friedlein (1873).", size=FOOTNOTE)),
            ], y=550),
            _block([_line(_span("Greek Mathematics", size=BODY))], y=600),
            _block([_line(_span("347", size=PAGE_NUM))], y=610),
            _block([
                _line(_span("https://doi.org/10.1017/example Published online", size=URL)),
            ], y=627),
        ]
        result = segment_page_blocks(blocks, 0, self.PROFILE, page_height=842.0)
        types = [b.block_type for b in result]
        assert types == ["heading", "body", "body", "footnote", "footnote"]
        assert result[0].text == "OBSCURE ORIGINS"
        assert result[3].footnote_id == "5"
        assert result[4].footnote_id == "6"


# ---------------------------------------------------------------------------
# Test: Ligature normalization
# ---------------------------------------------------------------------------

class TestLigatureNormalization:
    def test_fi_ligature(self):
        assert normalize_ligatures("scientiﬁc") == "scientific"

    def test_fl_ligature(self):
        assert normalize_ligatures("reﬂection") == "reflection"

    def test_ff_ligature(self):
        assert normalize_ligatures("eﬀect") == "effect"

    def test_ffi_ligature(self):
        assert normalize_ligatures("diﬃcult") == "difficult"

    def test_ffl_ligature(self):
        assert normalize_ligatures("raﬄe") == "raffle"

    def test_st_ligature(self):
        assert normalize_ligatures("ﬆore") == "store"

    def test_multiple_ligatures_in_text(self):
        text = "The scientiﬁc diﬃculty of the reﬂection"
        assert normalize_ligatures(text) == "The scientific difficulty of the reflection"

    def test_no_ligatures_unchanged(self):
        text = "Normal text without ligatures"
        assert normalize_ligatures(text) == text

    def test_ligatures_in_block_text_extraction(self):
        """Block text extraction must normalize ligatures automatically."""
        from doc2md.analysis.segmenter import _block_text
        block = {
            "type": 0,
            "bbox": (0, 0, 500, 20),
            "lines": [{"spans": [_span("scientiﬁc diﬃculty", size=BODY)]}],
        }
        assert "scientific difficulty" == _block_text(block)


# ---------------------------------------------------------------------------
# Test: Header/footer/boilerplate detection
# ---------------------------------------------------------------------------

class TestBoilerplateDetection:
    def _page(self, text):
        return Page(source_path=Path("/f.pdf"), raw_text=text, extraction_method="pymupdf")

    def test_detects_urls_as_boilerplate(self):
        pages = [self._page("body\nhttps://doi.org/10.1017/example Published online")]
        boilerplate = detect_boilerplate_lines(pages)
        assert any("doi.org" in b for b in boilerplate)

    def test_detects_page_numbers_as_boilerplate(self):
        pages = [self._page("body\n345"), self._page("body\n346"), self._page("body\n347")]
        boilerplate = detect_boilerplate_lines(pages)
        assert "345" in boilerplate
        assert "346" in boilerplate
        assert "347" in boilerplate

    def test_repeated_lines_detects_running_headers(self):
        pages = [
            self._page("Author Name\nbody1\nBook Title\n100\nhttps://example.com"),
            self._page("Author Name\nbody2\nBook Title\n101\nhttps://example.com"),
            self._page("Author Name\nbody3\nBook Title\n102\nhttps://example.com"),
        ]
        repeated = detect_repeated_lines(pages)
        assert "Author Name" in repeated
        assert "Book Title" in repeated

    def test_check_lines_parameter_catches_second_line_headers(self):
        """Author names that appear as second line should be caught with check_lines=3."""
        pages = [
            self._page("345\nAuthor Name\nbody1"),
            self._page("346\nAuthor Name\nbody2"),
            self._page("347\nAuthor Name\nbody3"),
        ]
        repeated = detect_repeated_lines(pages, check_lines=3)
        assert "Author Name" in repeated


# ---------------------------------------------------------------------------
# Test: Footnote extraction and orphan merging
# ---------------------------------------------------------------------------

def _tb(text, btype="body", fid=None, page=0):
    return TextBlock(text=text, block_type=btype, page_index=page, footnote_id=fid)


class TestFootnoteOrphanMerging:
    def test_orphan_footnote_after_footnote_with_id_merged(self):
        ch = Chapter(title="T", heading_level=1, blocks=[
            _tb("Body text."),
            _tb("1 First footnote.", "footnote", "1"),
            _tb("Continuation of first footnote.", "footnote"),
        ])
        result = link_footnotes(ch)
        assert "1" in result.footnotes
        assert "Continuation" in result.footnotes["1"]
        assert len(result.blocks) == 1

    def test_orphan_footnote_between_body_blocks_merged_to_previous_fn(self):
        """Orphan footnote between body blocks (page break in footnote area)."""
        ch = Chapter(title="T", heading_level=1, blocks=[
            _tb("Body on page 1.", page=0),
            _tb("64 A footnote on page 1.", "footnote", "64", page=0),
            _tb("Continuation of fn 64 on page 2.", "footnote", page=1),
            _tb("Body on page 2.", page=1),
        ])
        result = link_footnotes(ch)
        assert "64" in result.footnotes
        assert "Continuation" in result.footnotes["64"]
        assert len(result.blocks) == 2
        assert all(b.block_type == "body" for b in result.blocks)

    def test_orphan_footnote_with_no_prior_id_discarded(self):
        ch = Chapter(title="T", heading_level=1, blocks=[
            _tb("Orphan continuation text.", "footnote"),
            _tb("Body text."),
        ])
        result = link_footnotes(ch)
        assert len(result.footnotes) == 0
        assert len(result.blocks) == 1

    def test_multiple_orphans_merge_into_correct_parent(self):
        ch = Chapter(title="T", heading_level=1, blocks=[
            _tb("1 First fn.", "footnote", "1"),
            _tb("Still first fn.", "footnote"),
            _tb("More first fn.", "footnote"),
            _tb("2 Second fn.", "footnote", "2"),
            _tb("Still second fn.", "footnote"),
        ])
        result = link_footnotes(ch)
        assert "Still first" in result.footnotes["1"]
        assert "More first" in result.footnotes["1"]
        assert "Still second" in result.footnotes["2"]


# ---------------------------------------------------------------------------
# Test: Pipeline stage ordering — footnotes before merge
# ---------------------------------------------------------------------------

class TestPipelineStageOrdering:
    def test_footnotes_between_body_blocks_dont_break_sentence_joining(self):
        """When footnotes sit between body blocks that should be joined,
        extracting footnotes first allows the merger to join them."""
        ch = Chapter(title="T", heading_level=1, blocks=[
            _tb("the quick brown", page=0),
            _tb("42 A footnote.", "footnote", "42", page=0),
            _tb("fox jumps over", page=1),
        ])
        # Step 1: extract footnotes
        ch = link_footnotes(ch)
        assert len(ch.blocks) == 2
        assert ch.blocks[0].text.endswith("brown")
        assert ch.blocks[1].text.startswith("fox")

        # Step 2: merge body blocks
        ch = merge_chapter_text(ch)
        assert len(ch.blocks) == 1
        assert "brown fox" in ch.blocks[0].text

    def test_reversed_order_breaks_joining(self):
        """If merge runs before footnote extraction, the footnote block
        prevents consecutive body block joining."""
        ch = Chapter(title="T", heading_level=1, blocks=[
            _tb("the quick brown", page=0),
            _tb("42 A footnote.", "footnote", "42", page=0),
            _tb("fox jumps over", page=1),
        ])
        # Wrong order: merge first
        ch_merged = merge_chapter_text(ch)
        # Footnote block breaks the chain — still 3 blocks
        assert len(ch_merged.blocks) == 3


# ---------------------------------------------------------------------------
# Test: Chapter detection single-chapter fallback
# ---------------------------------------------------------------------------

class TestChapterDetectorSingleChapter:
    def test_single_chapter_uses_first_heading_as_title(self):
        blocks = [
            _tb("GREEK MATHEMATICS", "heading"),
            _tb("Body text."),
            _tb("OBSCURE ORIGINS", "heading"),
            _tb("More body."),
        ]
        blocks[0].heading_level = 2
        blocks[2].heading_level = 2
        mock_client = MagicMock()
        mock_client.generate_json.return_value = []
        chapters = detect_chapters(blocks, mock_client)
        assert len(chapters) == 1
        assert chapters[0].title == "GREEK MATHEMATICS"

    def test_single_chapter_excludes_title_heading_from_blocks(self):
        blocks = [
            _tb("TITLE", "heading"),
            _tb("Body."),
        ]
        blocks[0].heading_level = 2
        mock_client = MagicMock()
        mock_client.generate_json.return_value = []
        chapters = detect_chapters(blocks, mock_client)
        # Title heading should not appear in blocks
        assert all(b.text != "TITLE" for b in chapters[0].blocks)


# ---------------------------------------------------------------------------
# Test: Broken line wrapping rejoin
# ---------------------------------------------------------------------------

class TestBrokenLineWrapping:
    def test_centered_text_one_word_per_line(self):
        """PyMuPDF extracts centered/indented text as one word per line."""
        from doc2md.analysis.segmenter import _rejoin_lines
        text = (
            "The range of ideas designated by the word\n"
            "mathēmatikē\n"
            "are\n"
            "not\n"
            "identical\n"
            "to\n"
            "those\n"
            "denoted\n"
            "by\n"
            "our\n"
            "word\n"
            "mathematics."
        )
        result = _rejoin_lines(text)
        assert "mathēmatikē are not identical to those denoted by our word mathematics." in result

    def test_normal_paragraph_not_rejoined(self):
        from doc2md.analysis.segmenter import _rejoin_lines
        text = (
            "This is a normal length line with plenty of words in it.\n"
            "And another line that is also quite long enough.\n"
            "These should not be touched at all."
        )
        assert _rejoin_lines(text) == text

    def test_short_terminal_punctuation_not_joined(self):
        from doc2md.analysis.segmenter import _rejoin_lines
        text = "Done.\nFinished.\nComplete."
        assert _rejoin_lines(text) == text


# ---------------------------------------------------------------------------
# Test: End-to-end pipeline with realistic multi-page PDF
# ---------------------------------------------------------------------------

class TestEndToEndAcademicPdf:
    @pytest.fixture
    def academic_pdf(self, tmp_path):
        """Create a multi-page PDF mimicking academic chapter structure."""
        path = tmp_path / "chapter.pdf"
        doc = fitz.open()

        page1 = doc.new_page()
        page1.insert_text((72, 80), "GREEK MATHEMATICS", fontsize=16)
        page1.insert_text((72, 110), "Nathan Sidoli", fontsize=12)
        page1.insert_text((72, 140), (
            "This chapter discusses theoretical mathematics. "
            "The subscientific traditions were handed down by "
            "various professionals who used mathematics."
        ), fontsize=11)
        page1.insert_text((72, 600), "1 See Hoyrup (1990).", fontsize=8)
        page1.insert_text((72, 750), "345", fontsize=10)
        page1.insert_text((72, 770), "https://doi.org/10.1017/example Published online", fontsize=6)

        page2 = doc.new_page()
        page2.insert_text((72, 80), (
            "In the classical period, mathematical texts were "
            "being established by elite theoreticians."
        ), fontsize=11)
        page2.insert_text((72, 200), "OBSCURE ORIGINS", fontsize=11)
        page2.insert_text((72, 230), (
            "The origins of Greek mathematics were a favorite topic. "
            "We have little certain evidence about these origins."
        ), fontsize=11)
        page2.insert_text((72, 600), "2 See Szabo (1978).", fontsize=8)
        page2.insert_text((72, 750), "346", fontsize=10)
        page2.insert_text((72, 770), "https://doi.org/10.1017/example Published online", fontsize=6)

        doc.save(path)
        doc.close()
        return path

    @pytest.fixture
    def config(self, tmp_path):
        cfg = Config()
        cfg.paths.output_dir = str(tmp_path / "output")
        cfg.paths.cache_dir = str(tmp_path / "cache")
        return cfg

    @patch("doc2md.pipeline.OllamaClient")
    def test_produces_output_file(self, MockClient, academic_pdf, config):
        mock_client = MockClient.return_value
        mock_client.generate_json.return_value = []
        outputs = process_file(academic_pdf, config)
        assert len(outputs) >= 1
        assert all(p.exists() for p in outputs)

    @patch("doc2md.pipeline.OllamaClient")
    def test_output_contains_section_heading(self, MockClient, academic_pdf, config):
        mock_client = MockClient.return_value
        mock_client.generate_json.return_value = []
        outputs = process_file(academic_pdf, config)
        content = outputs[0].read_text()
        assert "OBSCURE ORIGINS" in content

    @patch("doc2md.pipeline.OllamaClient")
    def test_output_strips_page_numbers(self, MockClient, academic_pdf, config):
        mock_client = MockClient.return_value
        mock_client.generate_json.return_value = []
        outputs = process_file(academic_pdf, config)
        content = outputs[0].read_text()
        # Page numbers should not appear as standalone lines
        for line in content.splitlines():
            stripped = line.strip()
            if stripped and stripped.isdigit() and len(stripped) <= 3:
                # Allow digits in footnote definitions
                assert line.startswith("[^"), f"Bare page number found: {line}"

    @patch("doc2md.pipeline.OllamaClient")
    def test_output_strips_url_footer(self, MockClient, academic_pdf, config):
        mock_client = MockClient.return_value
        mock_client.generate_json.return_value = []
        outputs = process_file(academic_pdf, config)
        content = outputs[0].read_text()
        assert "doi.org" not in content
        assert "Published online" not in content

    @patch("doc2md.pipeline.OllamaClient")
    def test_output_has_no_ligatures(self, MockClient, academic_pdf, config):
        mock_client = MockClient.return_value
        mock_client.generate_json.return_value = []
        outputs = process_file(academic_pdf, config)
        content = outputs[0].read_text()
        assert "\ufb01" not in content  # fi
        assert "\ufb02" not in content  # fl


# ---------------------------------------------------------------------------
# Test: Classifier falls back to raw text for OCR pages
# ---------------------------------------------------------------------------

class TestClassifierFallback:
    def test_ocr_page_uses_raw_text_segmentation(self):
        """Pages without block_dicts (OCR) should fall back to raw text segmentation."""
        page = Page(
            source_path=Path("/scan.png"),
            raw_text="INTRODUCTION\n\nBody text.\n\n1 A footnote.",
            extraction_method="surya",
        )
        blocks = classify_pages([page], MagicMock())
        types = [b.block_type for b in blocks]
        assert "heading" in types
        assert "body" in types

    def test_mixed_pdf_and_ocr_pages(self):
        """Pipeline handles a mix of PDF pages (with block_dicts) and OCR pages."""
        block_dicts = [{"type": 0, "bbox": (0, 100, 500, 120),
                        "lines": [{"spans": [_span("PDF body.", size=BODY)]}]}]
        pdf_page = _page_obj("PDF body.", block_dicts, page_height=842.0)
        ocr_page = Page(
            source_path=Path("/scan.png"),
            raw_text="OCR body text.",
            extraction_method="surya",
        )
        blocks = classify_pages([pdf_page, ocr_page], MagicMock())
        assert len(blocks) == 2
        assert blocks[0].page_index == 0
        assert blocks[1].page_index == 1
