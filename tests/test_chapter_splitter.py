"""Tests for chapter_splitter module."""

import textwrap

import pytest

from doc2md.output.chapter_splitter import ChapterDef, detect_chapters, split_markdown


# --- detect_chapters tests ---


def _lines(text: str) -> list[str]:
    return textwrap.dedent(text).strip().splitlines()


class TestDetectChapters:
    def test_detects_named_sections(self):
        lines = _lines("""
            # Title

            Contents
            <b>Preface</b>
            Acknowledgments
            Introduction

            <b>Preface</b>
            Some preface body text here.

            Acknowledgments
            Thanks to everyone.

            Introduction
            The book begins here.
        """)
        chapters = detect_chapters(lines)
        titles = [c.title for c in chapters]
        assert "Preface" in titles
        assert "Acknowledgments" in titles
        assert "Introduction" in titles

    def test_detects_part_headers(self):
        lines = _lines("""
            # Title

            Contents
            <b>Preface</b>
            1. First Item

            <b>Preface</b>
            Body text.

            PART 1 Shawmut
            THE TIME BEFORE BOSTON (12,000-400 BP)
            Body text about part 1.

            PART 2 Puritanical
            Foundations (1629-1700)
            Body text about part 2.
        """)
        chapters = detect_chapters(lines)
        part_chapters = [c for c in chapters if "Part" in c.title]
        assert len(part_chapters) == 2
        assert "Shawmut" in part_chapters[0].title
        assert "Puritanical" in part_chapters[1].title
        # Part 2 title wraps
        assert "Foundations" in part_chapters[1].title

    def test_detects_conclusion_appendix(self):
        lines = _lines("""
            # Title

            Contents
            <b>Preface</b>
            1. Item

            <b>Preface</b>
            Body.

            CONCLUSION. The Future of Archaeology in
            <b>Boston</b>
            Body text.

            APPENDIX. Artifact Provenances
            1. Item details.
        """)
        chapters = detect_chapters(lines)
        titles = [c.title for c in chapters]
        conclusion = [t for t in titles if "Conclusion" in t]
        appendix = [t for t in titles if "Appendix" in t]
        assert len(conclusion) == 1
        assert "Boston" in conclusion[0]
        assert len(appendix) == 1
        assert "Provenances" in appendix[0]

    def test_detects_back_matter(self):
        lines = _lines("""
            # Title

            Contents
            <b>Preface</b>

            <b>Preface</b>
            Body.

            Notes
            INTRODUCTION
            1. Some note.

            Bibliography
            Author 2020.

            Index
            Page numbers in italics.
            abolitionist, 71
        """)
        chapters = detect_chapters(lines)
        titles = [c.title for c in chapters]
        assert "Notes" in titles
        assert "Bibliography" in titles
        assert "Index" in titles

    def test_skips_toc_region(self):
        """PART/section references in TOC should not be detected as chapters."""
        lines = _lines("""
            # Title

            Contents
            <b>Preface</b>
            Acknowledgments
            Introduction
            PART 1 Ancient Times
            1. Artifact One
            2. Artifact Two
            PART 2 Modern Times
            3. Artifact Three

            <b>Preface</b>
            This is the actual preface body text.

            PART 1 Ancient Times
            Body text about ancient times.

            PART 2 Modern Times
            Body text about modern times.
        """)
        chapters = detect_chapters(lines)
        part_chapters = [c for c in chapters if "Part" in c.title]
        # Should only detect the body PART headers, not the TOC ones
        assert len(part_chapters) == 2

    def test_end_lines_filled(self):
        lines = _lines("""
            # Title

            Contents
            <b>Preface</b>

            <b>Preface</b>
            Body.

            Introduction
            Body.

            Notes
            Some notes.
        """)
        chapters = detect_chapters(lines)
        assert len(chapters) == 3
        # First chapter's end_line == second chapter's start_line
        assert chapters[0].end_line == chapters[1].start_line
        assert chapters[1].end_line == chapters[2].start_line
        # Last chapter's end_line is None
        assert chapters[2].end_line is None

    def test_empty_input(self):
        assert detect_chapters([]) == []

    def test_no_chapters_detected(self):
        lines = _lines("""
            Just some random text.
            No structure here.
        """)
        assert detect_chapters(lines) == []

    def test_artifact_level_splits_within_parts(self):
        lines = _lines("""
            Contents
            <b>Preface</b>
            1. First Widget
            2. Second Widget

            <b>Preface</b>
            Body.

            PART 1 Widgets
            Intro to widgets.

            FIGURE 1.1
            A picture of widget one.
            Widget one is great.

            FIGURE 2.1
            A picture of widget two.
            Widget two is also great.

            Notes
            Some notes.
        """)
        chapters = detect_chapters(lines, artifact_level=True)
        titles = [c.title for c in chapters]
        assert "Preface" in titles
        assert "Notes" in titles
        # Should have artifact chapters instead of PART
        assert any("1. First Widget" in t for t in titles)
        assert any("2. Second Widget" in t for t in titles)
        # PART should still appear as intro section
        assert any("Part 1" in t for t in titles)

    def test_artifact_level_false_keeps_parts(self):
        lines = _lines("""
            Contents
            <b>Preface</b>
            1. Widget

            <b>Preface</b>
            Body.

            PART 1 Widgets
            Widget content with FIGURE 1.1 here.

            Notes
            Some notes.
        """)
        chapters = detect_chapters(lines, artifact_level=False)
        titles = [c.title for c in chapters]
        assert any("Part 1" in t for t in titles)
        assert not any("Widget" == t for t in titles)


# --- split_markdown tests ---


class TestSplitMarkdown:
    def test_splits_into_directories(self, tmp_path):
        md_content = textwrap.dedent("""\
            # Title

            Contents
            <b>Preface</b>

            <b>Preface</b>
            Preface body text.

            Introduction
            Intro body text.

            Notes
            Some notes here.
        """)
        md_file = tmp_path / "book.md"
        md_file.write_text(md_content)
        output_dir = tmp_path / "output"

        paths = split_markdown(md_file, output_dir)

        assert len(paths) == 3
        # Check directories were created with numbered prefixes
        dir_names = sorted(d.parent.name for d in paths)
        assert dir_names[0].startswith("010_")
        assert dir_names[1].startswith("020_")
        assert dir_names[2].startswith("030_")

    def test_content_preserved(self, tmp_path):
        md_content = textwrap.dedent("""\
            # Title

            Contents
            <b>Preface</b>

            <b>Preface</b>
            Line one.
            Line two.

            Introduction
            Intro text.
        """)
        md_file = tmp_path / "book.md"
        md_file.write_text(md_content)
        output_dir = tmp_path / "output"

        paths = split_markdown(md_file, output_dir)

        preface_text = paths[0].read_text()
        assert "Line one." in preface_text
        assert "Line two." in preface_text
        # Preface content should NOT contain Introduction content
        assert "Intro text." not in preface_text

        intro_text = paths[1].read_text()
        assert "Intro text." in intro_text

    def test_page_range_directory_naming(self, tmp_path):
        md_content = "Chapter one.\nChapter two.\n"
        md_file = tmp_path / "book.md"
        md_file.write_text(md_content)
        output_dir = tmp_path / "output"

        chapter_defs = [
            ChapterDef(title="Introduction", start_line=0, end_line=1, page_start=1, page_end=10),
            ChapterDef(title="Chapter One", start_line=1, page_start=11, page_end=30),
        ]
        paths = split_markdown(md_file, output_dir, chapter_defs)

        assert "_pp_1_10_" in paths[0].parent.name
        assert "_pp_11_30_" in paths[1].parent.name

    def test_no_page_range_directory_naming(self, tmp_path):
        md_content = "Chapter one.\nChapter two.\n"
        md_file = tmp_path / "book.md"
        md_file.write_text(md_content)
        output_dir = tmp_path / "output"

        chapter_defs = [
            ChapterDef(title="Introduction", start_line=0, end_line=1),
            ChapterDef(title="Chapter One", start_line=1),
        ]
        paths = split_markdown(md_file, output_dir, chapter_defs)

        assert "_pp_" not in paths[0].parent.name
        assert "_pp_" not in paths[1].parent.name
        assert "010_introduction" == paths[0].parent.name
        assert "020_chapter_one" == paths[1].parent.name

    def test_explicit_chapter_defs(self, tmp_path):
        md_content = "Line 0\nLine 1\nLine 2\nLine 3\n"
        md_file = tmp_path / "book.md"
        md_file.write_text(md_content)
        output_dir = tmp_path / "output"

        chapter_defs = [
            ChapterDef(title="First", start_line=0, end_line=2),
            ChapterDef(title="Second", start_line=2),
        ]
        paths = split_markdown(md_file, output_dir, chapter_defs)

        assert paths[0].read_text() == "Line 0\nLine 1\n"
        assert paths[1].read_text() == "Line 2\nLine 3\n"

    def test_empty_chapter_defs(self, tmp_path):
        md_file = tmp_path / "book.md"
        md_file.write_text("some text")
        assert split_markdown(md_file, tmp_path / "out", []) == []
