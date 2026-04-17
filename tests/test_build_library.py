"""Tests for reader/build_library.py."""

import sys
from pathlib import Path

import pytest

# Add reader/ to path so we can import build_library
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "reader"))

from build_library import build_library, count_body_words, extract_title, extract_yaml_front_matter, prettify_dir_name


@pytest.fixture
def fake_results(tmp_path):
    """Create a minimal results directory structure."""
    results = tmp_path / "results"
    book = results / "test_book_v1"
    ch1 = book / "intro_chapter"
    ch1.mkdir(parents=True)
    (ch1 / "chapter_01_intro.md").write_text("# Introduction\n\nBody text here.\n")

    ch2 = book / "second_topic"
    ch2.mkdir()
    (ch2 / "chapter_01_second.md").write_text("No heading here\n\nJust text.\n")

    # Skipped directory
    idx = book / "index"
    idx.mkdir()
    (idx / "chapter_01_index.md").write_text("# Index\n\nA, B, C\n")

    # Empty directory (no md files)
    empty = book / "empty_dir"
    empty.mkdir()

    return results


def test_extract_title_with_heading(tmp_path):
    md = tmp_path / "test.md"
    md.write_text("# My Title\n\nBody.\n")
    assert extract_title(md) == "My Title"


def test_extract_title_no_heading(tmp_path):
    md = tmp_path / "test.md"
    md.write_text("Just a paragraph.\n\nAnother one.\n")
    assert extract_title(md) is None


def test_extract_title_h2_not_h1(tmp_path):
    md = tmp_path / "test.md"
    md.write_text("## This is H2\n\n# This is H1\n")
    assert extract_title(md) == "This is H1"


def test_extract_title_numeric_h1_falls_back_to_h3(tmp_path):
    """When # heading is just a number, use ### heading instead."""
    md = tmp_path / "test.md"
    md.write_text("# 2\n\n### THE LEGACY OF THE\n\"SCIENTIFIC REVOLUTION\"\n\n### Science\n")
    assert extract_title(md) == 'THE LEGACY OF THE "SCIENTIFIC REVOLUTION"'


def test_extract_title_multiline_h3(tmp_path):
    """### heading with ALL-CAPS continuation line."""
    md = tmp_path / "test.md"
    md.write_text("# 15\n\n### MECHANICS AND\nEXPERIMENTAL PHYSICS\n\nbody text here\n")
    assert extract_title(md) == "MECHANICS AND EXPERIMENTAL PHYSICS"


def test_extract_title_missing_file(tmp_path):
    assert extract_title(tmp_path / "nonexistent.md") is None


def test_prettify_dir_name_simple():
    assert prettify_dir_name("greek_mathematics") == "Greek Mathematics"


def test_prettify_dir_name_numeric_prefix():
    assert prettify_dir_name("100_pp_27_61_islamic_culture") == "Islamic Culture"


def test_prettify_dir_name_leading_digits():
    assert prettify_dir_name("030_the_new_nature") == "The New Nature"


def test_build_library_structure(fake_results):
    lib = build_library(fake_results)
    assert "books" in lib
    assert len(lib["books"]) == 1

    book = lib["books"][0]
    assert book["id"] == "test_book_v1"
    assert len(book["chapters"]) == 2


def test_build_library_skips_front_matter(fake_results):
    lib = build_library(fake_results)
    chapter_ids = [c["id"] for c in lib["books"][0]["chapters"]]
    assert "index" not in chapter_ids


def test_build_library_skips_empty_dirs(fake_results):
    lib = build_library(fake_results)
    chapter_ids = [c["id"] for c in lib["books"][0]["chapters"]]
    assert "empty_dir" not in chapter_ids


def test_build_library_extracts_title(fake_results):
    lib = build_library(fake_results)
    chapters = {c["id"]: c for c in lib["books"][0]["chapters"]}
    assert chapters["intro_chapter"]["title"] == "Introduction"


def test_build_library_fallback_title(fake_results):
    lib = build_library(fake_results)
    chapters = {c["id"]: c for c in lib["books"][0]["chapters"]}
    assert chapters["second_topic"]["title"] == "Second Topic"


def test_build_library_paths_relative(fake_results):
    lib = build_library(fake_results)
    ch = lib["books"][0]["chapters"][0]
    assert ch["path"].startswith("results/")
    assert ch["path"].endswith(".md")


def test_build_library_nonexistent_dir(tmp_path):
    lib = build_library(tmp_path / "does_not_exist")
    assert lib == {"books": []}


def test_build_library_unknown_volume_uses_prettified_name(fake_results):
    lib = build_library(fake_results)
    assert lib["books"][0]["title"] == "Test Book V1"


def test_build_library_multi_file_chapters(tmp_path):
    """When a chapter dir has front_matter + content files, use content for title."""
    results = tmp_path / "results"
    book = results / "book"
    ch = book / "010_pp_1_20_intro"
    ch.mkdir(parents=True)
    (ch / "chapter_01_front_matter.md").write_text("# Front Matter\n\nTitle page.\n")
    (ch / "chapter_02_intro.md").write_text("# 1\n\n### INTRODUCTION\n\nbody text here.\n")

    lib = build_library(results)
    chapter = lib["books"][0]["chapters"][0]
    assert chapter["title"] == "INTRODUCTION"
    assert chapter["paths"] is not None
    assert len(chapter["paths"]) == 2
    assert chapter["words"] == count_body_words(ch / "chapter_01_front_matter.md") + \
        count_body_words(ch / "chapter_02_intro.md")


def test_build_library_deduplicates_section_dividers(tmp_path):
    """Section divider PDFs with identical content are skipped."""
    results = tmp_path / "results"
    book = results / "book"
    content = "# Part I\n\n### THE NEW NATURE\n\nBody text.\n"

    divider = book / "030_the_new_nature"
    divider.mkdir(parents=True)
    (divider / "chapter_01_part_i.md").write_text(content)

    actual = book / "031_pp_1_20_the_new_nature"
    actual.mkdir(parents=True)
    (actual / "chapter_01_part_i.md").write_text(content)

    lib = build_library(results)
    assert len(lib["books"][0]["chapters"]) == 1


def test_build_library_skips_frontmatter_dirs(tmp_path):
    """Dirs with 'frontmatter' in name are skipped."""
    results = tmp_path / "results"
    book = results / "book"
    fm = book / "010_pp_i_xxx_frontmatter"
    fm.mkdir(parents=True)
    (fm / "chapter_01_front_matter.md").write_text("# TOC\n")
    ch = book / "020_pp_1_20_intro"
    ch.mkdir(parents=True)
    (ch / "chapter_01_intro.md").write_text("# Introduction\n\nBody.\n")

    lib = build_library(results)
    ids = [c["id"] for c in lib["books"][0]["chapters"]]
    assert "010_pp_i_xxx_frontmatter" not in ids
    assert "020_pp_1_20_intro" in ids


# --- Tests for extract_yaml_front_matter ---

_FRONT_MATTER_MD = """\
---
title: Comprehensive integration of single cell data
authors:
  - Tim Stuart 1
  - Avi Srivastava 2
journal: Cell
year: 2019
doi: 10.1016/j.cell.2019.05.031
pmid: 31178118
---

# Introduction

Body text here.
"""


def test_extract_yaml_front_matter_title(tmp_path):
    md = tmp_path / "paper.md"
    md.write_text(_FRONT_MATTER_MD)
    result = extract_yaml_front_matter(md)
    assert result["title"] == "Comprehensive integration of single cell data"


def test_extract_yaml_front_matter_authors_list(tmp_path):
    md = tmp_path / "paper.md"
    md.write_text(_FRONT_MATTER_MD)
    result = extract_yaml_front_matter(md)
    assert isinstance(result["authors"], list)
    assert "Tim Stuart 1" in result["authors"]
    assert "Avi Srivastava 2" in result["authors"]


def test_extract_yaml_front_matter_scalar_fields(tmp_path):
    md = tmp_path / "paper.md"
    md.write_text(_FRONT_MATTER_MD)
    result = extract_yaml_front_matter(md)
    assert result["journal"] == "Cell"
    assert result["year"] == "2019"
    assert result["doi"] == "10.1016/j.cell.2019.05.031"
    assert result["pmid"] == "31178118"


def test_extract_yaml_front_matter_no_front_matter(tmp_path):
    md = tmp_path / "plain.md"
    md.write_text("# Just a heading\n\nBody text.\n")
    result = extract_yaml_front_matter(md)
    assert result == {}


def test_extract_yaml_front_matter_missing_file(tmp_path):
    result = extract_yaml_front_matter(tmp_path / "nonexistent.md")
    assert result == {}


# --- Tests for build_library YAML integration ---

def test_build_library_uses_yaml_title(tmp_path):
    """YAML front matter title overrides heading-based title."""
    results = tmp_path / "results"
    book = results / "papers"
    ch = book / "smith_2024"
    ch.mkdir(parents=True)
    (ch / "chapter_01_main.md").write_text(
        "---\ntitle: My Paper Title\nauthors:\n  - Jane Smith\njournal: Nature\nyear: 2024\ndoi: \npmid: \n---\n\n"
        "# Some Other Heading\n\nBody text here.\n"
    )
    lib = build_library(results)
    chapter = lib["books"][0]["chapters"][0]
    assert chapter["title"] == "My Paper Title"


def test_build_library_paper_metadata_field(tmp_path):
    """paper_metadata is included in chapter entries when YAML present."""
    results = tmp_path / "results"
    book = results / "papers"
    ch = book / "smith_2024"
    ch.mkdir(parents=True)
    (ch / "chapter_01_main.md").write_text(
        "---\ntitle: My Paper Title\nauthors:\n  - Jane Smith\njournal: Nature\nyear: 2024\ndoi: \npmid: \n---\n\n"
        "# Heading\n\nBody.\n"
    )
    lib = build_library(results)
    chapter = lib["books"][0]["chapters"][0]
    assert "paper_metadata" in chapter
    assert chapter["paper_metadata"]["journal"] == "Nature"


def test_build_library_no_paper_metadata_without_yaml(tmp_path):
    """Chapters without YAML front matter don't get paper_metadata."""
    results = tmp_path / "results"
    book = results / "mybook"
    ch = book / "intro"
    ch.mkdir(parents=True)
    (ch / "chapter_01_intro.md").write_text("# Introduction\n\nBody.\n")
    lib = build_library(results)
    chapter = lib["books"][0]["chapters"][0]
    assert "paper_metadata" not in chapter
