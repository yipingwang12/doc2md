"""Tests for Markdown output rendering."""

from doc2md.models import Chapter, TextBlock
from doc2md.output.markdown_writer import render_chapter, slugify, write_chapters


def _block(text: str, btype: str = "body", level: int | None = None) -> TextBlock:
    return TextBlock(text=text, block_type=btype, page_index=0, heading_level=level)


class TestRenderChapter:
    def test_basic_chapter(self):
        ch = Chapter(title="Introduction", heading_level=1, blocks=[_block("Hello world.")])
        md = render_chapter(ch)
        assert md.startswith("# Introduction")
        assert "Hello world." in md

    def test_subheadings(self):
        ch = Chapter(
            title="Methods", heading_level=1,
            blocks=[
                _block("Background", "heading", 2),
                _block("Some text."),
            ],
        )
        md = render_chapter(ch)
        assert "### Background" in md

    def test_captions(self):
        ch = Chapter(
            title="Ch1", heading_level=1,
            blocks=[_block("Figure 1: A diagram", "caption")],
        )
        md = render_chapter(ch)
        assert "> Figure 1: A diagram" in md

    def test_footnotes(self):
        ch = Chapter(
            title="Ch1", heading_level=1,
            blocks=[_block("Text here.")],
            footnotes={"1": "First note.", "2": "Second note."},
        )
        md = render_chapter(ch)
        assert "[^1]: First note." in md
        assert "[^2]: Second note." in md

    def test_bibliography(self):
        ch = Chapter(
            title="Ch1", heading_level=1,
            blocks=[],
            bibliography=["Smith (2020). Title.", "Jones (2019). Title."],
        )
        md = render_chapter(ch)
        assert "## References" in md
        assert "1. Smith (2020). Title." in md
        assert "2. Jones (2019). Title." in md

    def test_empty_chapter(self):
        ch = Chapter(title="Empty", heading_level=1, blocks=[])
        md = render_chapter(ch)
        assert "# Empty" in md

    def test_index_blocks(self):
        ch = Chapter(
            title="Index", heading_level=1,
            blocks=[_block("algorithms, 12-15", "index"), _block("data structures, 20", "index")],
        )
        md = render_chapter(ch)
        assert "- algorithms, 12-15" in md
        assert "- data structures, 20" in md

    def test_footnotes_sorted_numerically(self):
        ch = Chapter(
            title="Ch1", heading_level=1, blocks=[],
            footnotes={"10": "tenth", "2": "second", "1": "first"},
        )
        md = render_chapter(ch)
        lines = [l for l in md.splitlines() if l.startswith("[^")]
        assert lines[0].startswith("[^1]")
        assert lines[1].startswith("[^2]")
        assert lines[2].startswith("[^10]")


class TestSlugify:
    def test_basic(self):
        assert slugify("Chapter 1: Introduction") == "chapter_1_introduction"

    def test_special_chars(self):
        assert slugify("What's New?") == "whats_new"

    def test_long_title_truncated(self):
        long = "A" * 100
        assert len(slugify(long)) <= 60


class TestWriteChapters:
    def test_writes_files(self, tmp_path):
        chapters = [
            Chapter(title="Intro", heading_level=1, blocks=[_block("Hello.")]),
            Chapter(title="Methods", heading_level=1, blocks=[_block("Data.")]),
        ]
        paths = write_chapters(chapters, tmp_path, "my_book")
        assert len(paths) == 2
        assert all(p.exists() for p in paths)
        assert paths[0].name == "chapter_01_intro.md"
        assert paths[1].name == "chapter_02_methods.md"

    def test_file_content(self, tmp_path):
        chapters = [Chapter(title="Ch1", heading_level=1, blocks=[_block("Content.")])]
        paths = write_chapters(chapters, tmp_path, "test")
        content = paths[0].read_text()
        assert "# Ch1" in content
        assert "Content." in content

    def test_creates_directory(self, tmp_path):
        chapters = [Chapter(title="Ch1", heading_level=1, blocks=[])]
        write_chapters(chapters, tmp_path / "deep" / "nested", "book")
        assert (tmp_path / "deep" / "nested" / "book").is_dir()
