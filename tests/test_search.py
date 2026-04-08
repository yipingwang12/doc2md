"""Tests for cross-volume index-guided entity search."""

from pathlib import Path

import pytest

from doc2md.assembly.search import (
    SearchHit,
    SearchResult,
    extract_paragraphs,
    format_results,
    match_term,
    parse_linked_index_line,
    search_all,
    search_volume,
)


# --- parse_linked_index_line ---

class TestParseLinkedIndexLine:
    def test_single_link(self):
        line = "abacus, [516–517](../300_pp_512_531_mathematics/chapter_01_.md)"
        term, links = parse_linked_index_line(line)
        assert term == "abacus"
        assert links == [("516–517", "../300_pp_512_531_mathematics/chapter_01_.md")]

    def test_multiple_links(self):
        line = (
            "d'Abano, Pietro, [222](../170_pp_207_239_schools/chapter_01_.md), "
            "[597–598](../340_pp_590_610_anatomy/chapter_01_.md)"
        )
        term, links = parse_linked_index_line(line)
        assert term == "d'Abano, Pietro"
        assert len(links) == 2
        assert links[0] == ("222", "../170_pp_207_239_schools/chapter_01_.md")
        assert links[1] == ("597–598", "../340_pp_590_610_anatomy/chapter_01_.md")

    def test_no_links(self):
        line = "alchemy, 385–403"
        term, links = parse_linked_index_line(line)
        assert term == "alchemy, 385–403"
        assert links == []

    def test_sub_entry_with_link(self):
        line = "alchemy, [391–392](../280_pp_385_403_alchemy/chapter_01_.md)"
        term, links = parse_linked_index_line(line)
        assert term == "alchemy"
        assert len(links) == 1

    def test_mixed_linked_and_unlinked(self):
        line = "translators, [34–35](../100_pp_27_61_islamic/chapter_01_.md), 116–118"
        term, links = parse_linked_index_line(line)
        assert term == "translators"
        assert len(links) == 1
        assert links[0][0] == "34–35"

    def test_empty_line(self):
        term, links = parse_linked_index_line("")
        assert term == ""
        assert links == []

    def test_heading_line(self):
        term, links = parse_linked_index_line("# INDEX")
        assert term == "# INDEX"
        assert links == []

    def test_see_also_line(self):
        line = "See also Epitome"
        term, links = parse_linked_index_line(line)
        assert term == "See also Epitome"
        assert links == []


# --- match_term ---

class TestMatchTerm:
    def test_exact_match(self):
        assert match_term("abacus", "abacus") is True

    def test_case_insensitive(self):
        assert match_term("Abacus", "abacus") is True

    def test_reversed_name(self):
        assert match_term("Peter Abelard", "Abelard, Peter") is True

    def test_query_substring_of_term(self):
        assert match_term("alchemy", "alchemy and chemistry") is True

    def test_term_substring_of_query(self):
        assert match_term("medieval alchemy", "alchemy") is True

    def test_no_match(self):
        assert match_term("quantum", "abacus") is False

    def test_empty_query(self):
        assert match_term("", "abacus") is False

    def test_partial_name_match(self):
        assert match_term("Albertus", "Albertus Magnus") is True


# --- extract_paragraphs ---

class TestExtractParagraphs:
    def test_single_paragraph(self):
        text = "First paragraph.\n\nThe abacus was used widely.\n\nThird paragraph."
        result = extract_paragraphs(text, "abacus")
        assert len(result) == 1
        assert "abacus" in result[0]

    def test_multiple_paragraphs(self):
        text = "The abacus appeared.\n\nUnrelated text.\n\nThe abacus again."
        result = extract_paragraphs(text, "abacus")
        assert len(result) == 2

    def test_no_match(self):
        text = "Nothing relevant here.\n\nOr here either."
        result = extract_paragraphs(text, "abacus")
        assert result == []

    def test_strips_page_headings(self):
        text = "### 512\n\nThe abacus was common.\n\n### 513\n\nMore text."
        result = extract_paragraphs(text, "abacus")
        assert len(result) == 1
        assert "### 512" not in result[0]

    def test_context_paragraphs(self):
        text = "Before.\n\nThe abacus here.\n\nAfter.\n\nFar away."
        result = extract_paragraphs(text, "abacus", context=1)
        assert len(result) == 3
        assert "Before." in result[0]
        assert "abacus" in result[1]
        assert "After." in result[2]

    def test_context_no_duplicate(self):
        """Adjacent matches with context shouldn't duplicate paragraphs."""
        text = "Before.\n\nFirst abacus.\n\nSecond abacus.\n\nAfter."
        result = extract_paragraphs(text, "abacus", context=1)
        assert len(result) == 4

    def test_term_variant_matching(self):
        text = "Peter Abelard was a philosopher.\n\nUnrelated."
        result = extract_paragraphs(text, "Abelard, Peter")
        assert len(result) == 1

    def test_case_insensitive(self):
        text = "The ABACUS was common.\n\nOther text."
        result = extract_paragraphs(text, "abacus")
        assert len(result) == 1


# --- search_volume ---

def _make_linked_volume(tmp_path, name, chapters, index_lines):
    """Create a test volume with linked index and chapter files.

    chapters: list of (dir_name, md_filename, text)
    index_lines: list of str (linked index lines)
    """
    vol = tmp_path / name
    for dir_name, md_name, text in chapters:
        ch_dir = vol / dir_name
        ch_dir.mkdir(parents=True, exist_ok=True)
        (ch_dir / md_name).write_text(text)

    idx_dir = vol / "900_pp_900_950_index"
    idx_dir.mkdir(parents=True, exist_ok=True)
    (idx_dir / "chapter_01_index.md").write_text(
        "# INDEX\n\n" + "\n".join(index_lines) + "\n"
    )
    return vol


class TestSearchVolume:
    def test_finds_term_in_linked_index(self, tmp_path):
        vol = _make_linked_volume(
            tmp_path, "vol1",
            [("100_pp_27_61_topic", "chapter_01_.md",
              "# Topic\n\nThe abacus was widely used in medieval times.\n")],
            ["abacus, [30](../100_pp_27_61_topic/chapter_01_.md)"],
        )
        hits = search_volume(vol, "abacus")
        assert len(hits) == 1
        assert hits[0].volume == "vol1"
        assert hits[0].index_term == "abacus"
        assert any("abacus" in p for p in hits[0].paragraphs)

    def test_skips_volume_without_index(self, tmp_path):
        vol = tmp_path / "vol_no_index"
        ch = vol / "100_pp_27_61_topic"
        ch.mkdir(parents=True)
        (ch / "chapter_01_.md").write_text("Text\n")
        hits = search_volume(vol, "abacus")
        assert hits == []

    def test_dedup_same_chapter(self, tmp_path):
        vol = _make_linked_volume(
            tmp_path, "vol2",
            [("100_pp_27_61_topic", "chapter_01_.md",
              "# Topic\n\nAlchemy and abacus discussed together.\n")],
            [
                "abacus, [30](../100_pp_27_61_topic/chapter_01_.md)",
                "Abacus computing, [45](../100_pp_27_61_topic/chapter_01_.md)",
            ],
        )
        hits = search_volume(vol, "abacus")
        # Same chapter deduped into one hit
        chapter_paths = [h.chapter_path for h in hits]
        assert len(set(chapter_paths)) == len(chapter_paths)

    def test_broken_link_skipped(self, tmp_path):
        vol = _make_linked_volume(
            tmp_path, "vol3",
            [],  # no chapter files
            ["abacus, [30](../missing_dir/chapter_01_.md)"],
        )
        hits = search_volume(vol, "abacus")
        assert hits == []

    def test_sub_entry_match(self, tmp_path):
        """Sub-entry term 'alchemy' is found when searching for 'alchemy'."""
        vol = _make_linked_volume(
            tmp_path, "vol4",
            [("100_pp_27_61_topic", "chapter_01_.md",
              "# Topic\n\nAlbertus Magnus studied alchemy extensively.\n")],
            [
                "Albertus Magnus",
                "alchemy, [30](../100_pp_27_61_topic/chapter_01_.md)",
            ],
        )
        hits = search_volume(vol, "alchemy")
        assert len(hits) == 1
        assert any("alchemy" in p for p in hits[0].paragraphs)


# --- search_all ---

class TestSearchAll:
    def test_multiple_volumes(self, tmp_path):
        _make_linked_volume(
            tmp_path, "vol_a",
            [("100_pp_27_61_math", "chapter_01_.md",
              "# Math\n\nThe abacus in mathematics.\n")],
            ["abacus, [30](../100_pp_27_61_math/chapter_01_.md)"],
        )
        _make_linked_volume(
            tmp_path, "vol_b",
            [("100_pp_27_61_culture", "chapter_01_.md",
              "# Culture\n\nThe abacus in culture.\n")],
            ["abacus, [30](../100_pp_27_61_culture/chapter_01_.md)"],
        )
        result = search_all(tmp_path, "abacus")
        assert len(result.hits) == 2
        volumes = {h.volume for h in result.hits}
        assert "vol_a" in volumes
        assert "vol_b" in volumes

    def test_empty_results(self, tmp_path):
        _make_linked_volume(
            tmp_path, "vol_c",
            [("100_pp_27_61_topic", "chapter_01_.md", "# Topic\n\nText.\n")],
            ["abacus, [30](../100_pp_27_61_topic/chapter_01_.md)"],
        )
        result = search_all(tmp_path, "quantum")
        assert result.hits == []


# --- format_results ---

class TestFormatResults:
    def test_grouped_output(self):
        hits = [
            SearchHit(
                volume="cambridge_science_v2",
                chapter_dir="100_pp_27_61_islamic_culture",
                chapter_path=Path("/fake/path.md"),
                index_term="abacus",
                page_ref="30",
                paragraphs=["The abacus was widely used."],
            ),
        ]
        result = SearchResult(query="abacus", hits=hits)
        output = format_results(result)
        assert "cambridge_science_v2" in output
        assert "islamic culture" in output.lower()
        assert "pp. 27–61" in output
        assert "abacus" in output

    def test_empty_results(self):
        result = SearchResult(query="quantum", hits=[])
        output = format_results(result)
        assert "No results" in output or output == ""
