"""Tests for index linking: parse index entries, match to chapters, render links."""

from pathlib import Path

import pytest

from doc2md.assembly.index_linker import (
    ChapterFile,
    IndexEntry,
    PageRef,
    _render_entry_pageless,
    _term_variants,
    build_chapter_map,
    build_chapter_map_pageless,
    expand_abbreviated_end,
    find_chapter_for_page,
    link_index,
    parse_index_md,
    parse_page_refs,
    render_linked_index,
    render_linked_index_pageless,
)


# --- _term_variants ---

class TestTermVariants:
    def test_simple_term(self):
        assert "abacus" in _term_variants("abacus")

    def test_last_first_name(self):
        variants = _term_variants("Abelard, Peter")
        assert "peter abelard" in variants
        assert "abelard" in variants

    def test_phrase_with_preposition(self):
        variants = _term_variants("medicine in Africa")
        assert "medicine" in variants

    def test_title_with_of(self):
        variants = _term_variants("Summa perfectionis of Geber")
        assert "summa perfectionis" in variants

    def test_strip_parenthetical(self):
        variants = _term_variants("AMS (accelerated mass spectrometer) dating")
        assert "ams dating" in variants

    def test_strip_after_colon(self):
        variants = _term_variants("Beacon Hill: as fashionable neighborhood")
        assert "beacon hill" in variants

    def test_strip_after_semicolon(self):
        variants = _term_variants("pottery; women's involvement in industry")
        assert "pottery" in variants

    def test_strip_html_tags(self):
        variants = _term_variants("<b>Boston Town Records</b>")
        assert "boston town records" in variants

    def test_html_and_parenthetical_combined(self):
        variants = _term_variants("<i>Big Dig</i> (Central Artery/Tunnel project)")
        assert "big dig" in variants


# --- expand_abbreviated_end ---

class TestExpandAbbreviatedEnd:
    def test_two_digit(self):
        assert expand_abbreviated_end(325, "31") == 331

    def test_one_digit(self):
        assert expand_abbreviated_end(592, "3") == 593

    def test_same_length(self):
        assert expand_abbreviated_end(181, "95") == 195

    def test_full_end(self):
        assert expand_abbreviated_end(181, "195") == 195

    def test_four_digit_start(self):
        assert expand_abbreviated_end(1325, "31") == 1331

    def test_abbreviated_less_than_start_last_digits(self):
        # 443, "4" -> 444 (replace last 1 digit)
        assert expand_abbreviated_end(443, "4") == 444


# --- parse_page_refs ---

class TestParsePageRefs:
    def test_single_page(self):
        refs = parse_page_refs("26")
        assert refs == [PageRef(26)]

    def test_multiple_pages(self):
        refs = parse_page_refs("241, 316, 455")
        assert refs == [PageRef(241), PageRef(316), PageRef(455)]

    def test_range_abbreviated(self):
        refs = parse_page_refs("516–17")
        assert refs == [PageRef(516, 517)]

    def test_range_full(self):
        refs = parse_page_refs("592–593")
        assert refs == [PageRef(592, 593)]

    def test_range_with_hyphen(self):
        refs = parse_page_refs("325-31")
        assert refs == [PageRef(325, 331)]

    def test_mixed(self):
        refs = parse_page_refs("181–95, 261")
        assert refs == [PageRef(181, 195), PageRef(261)]

    def test_complex(self):
        refs = parse_page_refs("241, 316–31, 455, 503")
        assert refs == [PageRef(241), PageRef(316, 331), PageRef(455), PageRef(503)]

    def test_empty(self):
        assert parse_page_refs("") == []

    def test_no_numbers(self):
        assert parse_page_refs("no numbers here") == []


# --- parse_index_md ---

class TestParseIndexMd:
    def test_simple_entry(self):
        text = "# INDEX\n\nabacus, 516–17\n"
        entries = parse_index_md(text)
        assert len(entries) == 1
        assert entries[0].term == "abacus"
        assert entries[0].page_refs == [PageRef(516, 517)]

    def test_multiple_entries(self):
        text = "# INDEX\n\nabacus, 516–17\nAlbert of Saxony, 415, 426\n"
        entries = parse_index_md(text)
        assert len(entries) == 2
        assert entries[0].term == "abacus"
        assert entries[1].term == "Albert of Saxony"

    def test_entry_with_sub_entries(self):
        text = "# INDEX\n\nAlbertus Magnus\nalchemy, 391–2, 394\ncosmology, 451–2\n"
        entries = parse_index_md(text)
        assert len(entries) == 1
        assert entries[0].term == "Albertus Magnus"
        assert len(entries[0].sub_entries) == 2
        assert entries[0].sub_entries[0].term == "alchemy"
        assert entries[0].sub_entries[1].term == "cosmology"

    def test_continuation(self):
        text = "# INDEX\n\nalchemy, 385–403\npractical, 393–4\n\nalchemy (cont.)\ntheoretical, 392–3\n"
        entries = parse_index_md(text)
        # alchemy should have 3 sub-entries total (practical + theoretical)
        # plus its own page_refs
        alchemy = [e for e in entries if e.term == "alchemy"]
        assert len(alchemy) == 1
        assert alchemy[0].page_refs == [PageRef(385, 403)]
        sub_terms = [s.term for s in alchemy[0].sub_entries]
        assert "practical" in sub_terms
        assert "theoretical" in sub_terms

    def test_see_also(self):
        text = "# INDEX\n\nAlmagest (Ptolemy)\ntranslation of, 118, 346\nSee also Epitome\n"
        entries = parse_index_md(text)
        assert len(entries) == 1
        assert entries[0].see_also == ["Epitome"]

    def test_strips_page_number_headings(self):
        text = "# INDEX\n\nabacus, 516–17\n\n### 646\n\nAlbert, 415\n"
        entries = parse_index_md(text)
        terms = [e.term for e in entries]
        assert "abacus" in terms
        assert "Albert" in terms
        assert len(entries) == 2

    def test_strips_nb_note(self):
        text = "# INDEX\n\nN.B.: The index does not cover the notes.\n\nabacus, 516\n"
        entries = parse_index_md(text)
        assert len(entries) == 1
        assert entries[0].term == "abacus"

    def test_wrapped_page_refs(self):
        text = "# INDEX\n\nactive sciences, 245–6, 249–50, 261–3,\n537\n"
        entries = parse_index_md(text)
        assert len(entries) == 1
        assert entries[0].term == "active sciences"
        assert PageRef(537) in entries[0].page_refs

    def test_entry_with_apostrophe(self):
        text = "# INDEX\n\nd'Abano, Pietro, 222, 597–8, 603\n"
        entries = parse_index_md(text)
        assert len(entries) == 1
        assert entries[0].term == "d'Abano, Pietro"

    def test_see_cross_ref(self):
        text = "# INDEX\n\nAlhacen. See Ibn al-Haytham\n"
        entries = parse_index_md(text)
        assert len(entries) == 1
        assert entries[0].see_also == ["Ibn al-Haytham"]

    def test_see_also_at_end_of_line(self):
        """See also with targets on next line (v4 format)."""
        text = "# INDEX\n\nagriculture, 117. See also\ngardening; horticulture\n"
        entries = parse_index_md(text)
        assert len(entries) == 1
        assert entries[0].term == "agriculture"
        see_targets = [s for s in entries[0].see_also if s]
        assert any("gardening" in t for t in see_targets)

    def test_see_also_inline_with_targets(self):
        """'See also X' with targets on same line."""
        text = "# INDEX\n\nAlmagest (Ptolemy), 118\nSee also Epitome\n"
        entries = parse_index_md(text)
        assert entries[0].see_also == ["Epitome"]

    def test_no_see_also_also_corruption(self):
        """Ensure 'See also' never produces 'See also also' in output."""
        from doc2md.assembly.index_linker import render_linked_index
        text = "# INDEX\n\nagriculture, 117. See also\ngardening; horticulture\n"
        entries = parse_index_md(text)
        result = render_linked_index(entries, [], "idx")
        assert "See also also" not in result


# --- build_chapter_map ---

class TestBuildChapterMap:
    def test_parses_page_ranges(self, tmp_path):
        vol = tmp_path / "volume"
        ch1 = vol / "100_pp_27_61_islamic_culture"
        ch1.mkdir(parents=True)
        (ch1 / "chapter_01_.md").write_text("# Islamic Culture\n\nBody text about Islam.\n")
        ch2 = vol / "110_pp_62_83_mathematics"
        ch2.mkdir()
        (ch2 / "chapter_01_.md").write_text("# Mathematics\n\nBody about math.\n")

        chapters = build_chapter_map(vol)
        assert len(chapters) == 2
        assert chapters[0].page_start == 27
        assert chapters[0].page_end == 61
        assert chapters[1].page_start == 62

    def test_skips_roman_numeral_dirs(self, tmp_path):
        vol = tmp_path / "volume"
        fm = vol / "010_pp_i_xxx_frontmatter"
        fm.mkdir(parents=True)
        (fm / "chapter_01_.md").write_text("# Front\n")
        ch = vol / "100_pp_27_61_real"
        ch.mkdir()
        (ch / "chapter_01_.md").write_text("# Real\n\nText.\n")

        chapters = build_chapter_map(vol)
        assert len(chapters) == 1
        assert chapters[0].page_start == 27

    def test_skips_non_page_dirs(self, tmp_path):
        vol = tmp_path / "volume"
        idx = vol / "index"
        idx.mkdir(parents=True)
        (idx / "chapter_01_index.md").write_text("# INDEX\n")
        ch = vol / "100_pp_27_61_real"
        ch.mkdir()
        (ch / "chapter_01_.md").write_text("# Real\n\nText.\n")

        chapters = build_chapter_map(vol)
        assert len(chapters) == 1

    def test_sorts_by_page_start(self, tmp_path):
        vol = tmp_path / "volume"
        ch2 = vol / "200_pp_100_150_later"
        ch2.mkdir(parents=True)
        (ch2 / "chapter_01_.md").write_text("Later\n")
        ch1 = vol / "100_pp_27_61_earlier"
        ch1.mkdir(parents=True)
        (ch1 / "chapter_01_.md").write_text("Earlier\n")

        chapters = build_chapter_map(vol)
        assert chapters[0].page_start == 27
        assert chapters[1].page_start == 100

    def test_empty_for_no_range_dirs(self, tmp_path):
        vol = tmp_path / "volume"
        ch = vol / "greek_mathematics"
        ch.mkdir(parents=True)
        (ch / "chapter_01_.md").write_text("Text\n")

        assert build_chapter_map(vol) == []

    def test_multi_file_chapters(self, tmp_path):
        vol = tmp_path / "volume"
        ch = vol / "100_pp_27_61_topic"
        ch.mkdir(parents=True)
        (ch / "chapter_01_front_matter.md").write_text("Title page\n")
        (ch / "chapter_02_.md").write_text("Body text about topic.\n")

        chapters = build_chapter_map(vol)
        assert len(chapters) == 1
        assert "Title page" in chapters[0].text
        assert "Body text about topic" in chapters[0].text


# --- find_chapter_for_page ---

class TestFindChapterForPage:
    def _chapters(self):
        return [
            ChapterFile("ch1", 27, 61, [], "text1"),
            ChapterFile("ch2", 62, 83, [], "text2"),
            ChapterFile("ch3", 84, 108, [], "text3"),
        ]

    def test_page_in_range(self):
        ch = find_chapter_for_page(70, self._chapters())
        assert ch is not None
        assert ch.dir_name == "ch2"

    def test_page_at_start_boundary(self):
        ch = find_chapter_for_page(27, self._chapters())
        assert ch is not None
        assert ch.dir_name == "ch1"

    def test_page_at_end_boundary(self):
        ch = find_chapter_for_page(61, self._chapters())
        assert ch is not None
        assert ch.dir_name == "ch1"

    def test_page_out_of_range(self):
        assert find_chapter_for_page(200, self._chapters()) is None

    def test_page_before_all(self):
        assert find_chapter_for_page(1, self._chapters()) is None

    def test_prefers_narrowest_range(self):
        """Section divider (wide range) should lose to specific chapter."""
        chapters = [
            ChapterFile("section_divider", 149, 822, [], ""),
            ChapterFile("specific_chapter", 149, 195, [], "text"),
        ]
        ch = find_chapter_for_page(160, chapters)
        assert ch is not None
        assert ch.dir_name == "specific_chapter"


# --- render_linked_index ---

class TestRenderLinkedIndex:
    def _chapters(self):
        return [
            ChapterFile(
                "100_pp_27_61_islamic_culture", 27, 61, [],
                "text about abacus and Islamic culture",
            ),
            ChapterFile(
                "110_pp_62_83_mathematics", 62, 83, [],
                "text about algebra and mathematics",
            ),
        ]

    def test_linked_entry(self):
        entries = [IndexEntry("abacus", [PageRef(30)], [], [], "abacus, 30")]
        result = render_linked_index(entries, self._chapters(), "index_dir")
        assert "[30]" in result
        assert "100_pp_27_61_islamic_culture" in result

    def test_reversed_name_matches(self):
        """'Smith, John' matches chapter containing 'John Smith'."""
        chapters = [ChapterFile("ch1", 1, 50, [], "text about John Smith and his work")]
        entries = [IndexEntry("Smith, John", [PageRef(10)], [], [], "Smith, John, 10")]
        result = render_linked_index(entries, chapters, "idx")
        assert "[10]" in result

    def test_unmatched_stays_plain(self):
        entries = [IndexEntry("nonexistent", [PageRef(30)], [], [], "nonexistent, 30")]
        result = render_linked_index(entries, self._chapters(), "index_dir")
        assert "nonexistent, 30" in result
        assert "[30]" not in result

    def test_range_linked(self):
        entries = [IndexEntry("abacus", [PageRef(30, 45)], [], [], "abacus, 30–45")]
        result = render_linked_index(entries, self._chapters(), "index_dir")
        assert "[30–45]" in result

    def test_page_out_of_range_stays_plain(self):
        entries = [IndexEntry("abacus", [PageRef(999)], [], [], "abacus, 999")]
        result = render_linked_index(entries, self._chapters(), "index_dir")
        assert "abacus, 999" in result

    def test_sub_entries_linked(self):
        sub = IndexEntry("algebra", [PageRef(72)], [], [], "algebra, 72")
        entries = [IndexEntry("mathematics", [PageRef(62)], [sub], [], "")]
        result = render_linked_index(entries, self._chapters(), "index_dir")
        assert "[72]" in result

    def test_see_also(self):
        entries = [IndexEntry("Almagest", [PageRef(30)], [], ["Epitome"], "")]
        result = render_linked_index(entries, self._chapters(), "index_dir")
        assert "See also Epitome" in result


# --- link_index (integration) ---

class TestLinkIndex:
    def _make_volume(self, tmp_path):
        vol = tmp_path / "volume"
        ch = vol / "100_pp_27_61_topic"
        ch.mkdir(parents=True)
        (ch / "chapter_01_.md").write_text("# Topic\n\nText about abacus and algebra.\n")

        idx = vol / "370_pp_645_677_index"
        idx.mkdir()
        (idx / "chapter_01_index.md").write_text(
            "# INDEX\n\nabacus, 30\nalgebra, 45\nunknown_term, 30\n"
        )
        return vol

    def test_full_integration(self, tmp_path):
        vol = self._make_volume(tmp_path)
        result = link_index(vol)
        assert result is not None
        text = result.read_text()
        # abacus and algebra should be linked
        assert "[30]" in text
        assert "[45]" in text
        # unknown_term should stay plain
        assert "unknown_term, 30" in text

    def test_idempotent(self, tmp_path):
        """Running link_index twice produces the same output."""
        vol = self._make_volume(tmp_path)
        link_index(vol)
        first = (vol / "370_pp_645_677_index" / "chapter_01_index.md").read_text()
        link_index(vol)
        second = (vol / "370_pp_645_677_index" / "chapter_01_index.md").read_text()
        assert first == second

    def test_preserves_original(self, tmp_path):
        """Original index is saved as .orig.md."""
        vol = self._make_volume(tmp_path)
        idx = vol / "370_pp_645_677_index" / "chapter_01_index.md"
        original = idx.read_text()
        link_index(vol)
        orig_file = idx.with_suffix(".orig.md")
        assert orig_file.exists()
        assert orig_file.read_text() == original

    def test_no_index_chapter(self, tmp_path):
        vol = tmp_path / "volume"
        ch = vol / "100_pp_27_61_topic"
        ch.mkdir(parents=True)
        (ch / "chapter_01_.md").write_text("Text\n")
        assert link_index(vol) is None

    def test_no_page_range_dirs_uses_pageless(self, tmp_path):
        """Without _pp_ dirs, link_index falls back to pageless term matching."""
        vol = tmp_path / "volume"
        ch = vol / "010_greek_mathematics"
        ch.mkdir(parents=True)
        (ch / "chapter_01_greek_mathematics.md").write_text(
            "The abacus was used in Greek mathematics.\n"
        )
        idx = vol / "020_index"
        idx.mkdir()
        (idx / "chapter_01_index.md").write_text("# INDEX\n\nabacus, 30\n")
        result = link_index(vol)
        assert result is not None
        text = result.read_text()
        assert "[" in text  # should contain links
        assert "greek_mathematics" in text


# --- Year-as-page-ref filtering ---

class TestYearFiltering:
    """Years embedded in index terms (e.g. 'British Anatomy Act of 1832, 269')
    should not be linked as page references."""

    def _make_year_volume(self, tmp_path):
        vol = tmp_path / "volume"
        ch = vol / "010_pp_200_662_medicine"
        ch.mkdir(parents=True)
        (ch / "chapter_01_.md").write_text("# Medicine\n\nBritish Anatomy Act study.\n")
        idx = vol / "020_pp_663_700_index"
        idx.mkdir()
        (idx / "chapter_01_index.md").write_text(
            "# INDEX\n\nBritish Anatomy Act of 1832, 269\n"
        )
        return vol

    def test_year_not_treated_as_ref(self, tmp_path):
        """1832 exceeds max page (662) — must not appear as a standalone ref number."""
        vol = self._make_year_volume(tmp_path)
        result = link_index(vol)
        assert result is not None
        text = result.read_text()
        # "British Anatomy Act of, 1832," is the wrong form — year should stay in term
        assert "British Anatomy Act of," not in text

    def test_year_reattached_to_term(self, tmp_path):
        """Year stripped by the ref parser must be reattached to the term."""
        vol = self._make_year_volume(tmp_path)
        result = link_index(vol)
        assert result is not None
        text = result.read_text()
        assert "British Anatomy Act of 1832" in text

    def test_valid_page_ref_still_linked(self, tmp_path):
        """The real page ref (269, within max_page) must still be linked."""
        vol = self._make_year_volume(tmp_path)
        result = link_index(vol)
        assert result is not None
        text = result.read_text()
        assert "[269]" in text

    def test_normal_refs_unaffected(self, tmp_path):
        """Refs within the volume range must not be filtered."""
        vol = tmp_path / "volume"
        ch = vol / "010_pp_1_100_topic"
        ch.mkdir(parents=True)
        (ch / "chapter_01_.md").write_text("# Topic\n\nText about algebra.\n")
        idx = vol / "020_pp_101_120_index"
        idx.mkdir()
        (idx / "chapter_01_index.md").write_text(
            "# INDEX\n\nalgebra, 50\n"
        )
        result = link_index(vol)
        assert result is not None
        text = result.read_text()
        assert "[50]" in text

# --- Pageless linking tests ---


class TestBuildChapterMapPageless:
    def test_loads_all_chapter_dirs(self, tmp_path):
        vol = tmp_path / "volume"
        (vol / "010_preface").mkdir(parents=True)
        (vol / "010_preface" / "chapter_01_preface.md").write_text("Preface text.\n")
        (vol / "020_introduction").mkdir(parents=True)
        (vol / "020_introduction" / "chapter_01_introduction.md").write_text("Intro text.\n")
        (vol / "030_index").mkdir(parents=True)
        (vol / "030_index" / "chapter_01_index.md").write_text("Index text.\n")

        chapters = build_chapter_map_pageless(vol)
        assert len(chapters) == 2  # index dir excluded
        dir_names = [c.dir_name for c in chapters]
        assert "010_preface" in dir_names
        assert "020_introduction" in dir_names

    def test_skips_index_dir(self, tmp_path):
        vol = tmp_path / "volume"
        (vol / "010_chapter").mkdir(parents=True)
        (vol / "010_chapter" / "chapter_01_.md").write_text("Text.\n")
        (vol / "020_index").mkdir(parents=True)
        (vol / "020_index" / "chapter_01_index.md").write_text("Index.\n")

        chapters = build_chapter_map_pageless(vol)
        assert len(chapters) == 1
        assert "index" not in chapters[0].dir_name


class TestRenderEntryPageless:
    def _make_chapters(self) -> list[ChapterFile]:
        return [
            ChapterFile("010_preface", 0, 0, [], "The author thanks everyone."),
            ChapterFile("020_introduction", 0, 0, [], "Samuel Adams led the revolt."),
            ChapterFile("030_part_1", 0, 0, [], "Artifacts from ancient times."),
        ]

    def test_links_to_matching_chapters(self):
        chapters = self._make_chapters()
        entry = IndexEntry(
            term="Adams, Samuel",
            page_refs=[PageRef(101)],
            raw_text="Adams, Samuel, 101",
        )
        result = _render_entry_pageless(entry, chapters, "index")
        assert "[" in result
        assert "introduction" in result
        # Should not link to preface or part_1
        assert "preface" not in result
        assert "part_1" not in result

    def test_no_match_keeps_plain_text(self):
        chapters = self._make_chapters()
        entry = IndexEntry(
            term="Nonexistent Person",
            page_refs=[PageRef(42)],
            raw_text="Nonexistent Person, 42",
        )
        result = _render_entry_pageless(entry, chapters, "index")
        assert "[" not in result
        assert "42" in result

    def test_multiple_chapter_matches(self):
        chapters = [
            ChapterFile("010_ch1", 0, 0, [], "The cat sat on the mat."),
            ChapterFile("020_ch2", 0, 0, [], "Another cat appeared."),
        ]
        entry = IndexEntry(term="cat", page_refs=[PageRef(5)], raw_text="cat, 5")
        result = _render_entry_pageless(entry, chapters, "index")
        assert "ch1" in result
        assert "ch2" in result


class TestRenderLinkedIndexPageless:
    def test_full_render(self):
        chapters = [
            ChapterFile("010_introduction", 0, 0, [], "Boston was founded in 1630."),
            ChapterFile("020_part_1", 0, 0, [], "Artifacts from Shawmut peninsula."),
        ]
        entries = [
            IndexEntry(term="Boston", page_refs=[PageRef(1)], raw_text="Boston, 1"),
            IndexEntry(
                term="Shawmut",
                page_refs=[PageRef(7)],
                raw_text="Shawmut, 7",
            ),
        ]
        result = render_linked_index_pageless(entries, chapters, "index")
        assert "# INDEX" in result
        # Boston appears in introduction
        assert "introduction" in result
        # Shawmut appears in part_1
        assert "part_1" in result
