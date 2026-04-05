"""Tests for reader/build_library.py."""

import sys
from pathlib import Path

import pytest

# Add reader/ to path so we can import build_library
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "reader"))

from build_library import build_library, extract_title, prettify_dir_name


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
