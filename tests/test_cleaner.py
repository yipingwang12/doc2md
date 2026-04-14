"""Tests for header/footer stripping and text cleaning."""

from pathlib import Path

from doc2md.assembly.cleaner import (
    detect_repeated_lines,
    fix_hyphenation,
    join_broken_sentences,
    normalize_ligatures,
    strip_headers_footers,
)
from doc2md.models import Page


def _page(text: str) -> Page:
    return Page(source_path=Path("/fake.pdf"), raw_text=text, extraction_method="pymupdf")


class TestDetectRepeatedLines:
    def test_finds_repeated_header(self):
        pages = [_page("HEADER\nbody1"), _page("HEADER\nbody2"), _page("HEADER\nbody3")]
        repeated = detect_repeated_lines(pages)
        assert "HEADER" in repeated

    def test_finds_repeated_footer(self):
        pages = [_page("body1\nFOOTER"), _page("body2\nFOOTER"), _page("body3\nFOOTER")]
        repeated = detect_repeated_lines(pages)
        assert "FOOTER" in repeated

    def test_no_repeats(self):
        pages = [_page("unique1"), _page("unique2"), _page("unique3")]
        repeated = detect_repeated_lines(pages)
        assert len(repeated) == 0

    def test_ignores_below_threshold(self):
        pages = [_page("HEADER\nbody1\nextra")]
        repeated = detect_repeated_lines(pages, min_occurrences=3)
        assert len(repeated) == 0


class TestStripHeadersFooters:
    def test_removes_repeated(self):
        pages = [_page("HEADER\ncontent\nFOOTER")]
        result = strip_headers_footers(pages, {"HEADER", "FOOTER"})
        assert "HEADER" not in result[0].raw_text
        assert "FOOTER" not in result[0].raw_text
        assert "content" in result[0].raw_text

    def test_no_repeated_returns_unchanged(self):
        pages = [_page("content")]
        result = strip_headers_footers(pages, set())
        assert result[0].raw_text == "content"


class TestNormalizeLigatures:
    def test_ligature_fi(self):
        assert normalize_ligatures("ﬁnd") == "find"

    def test_ligature_fl(self):
        assert normalize_ligatures("ﬂow") == "flow"

    def test_pua_digit_single(self):
        """U+F731 = '1' in decorative PDF font."""
        assert normalize_ligatures("\uF731") == "1"

    def test_pua_digit_multi(self):
        """U+F731 U+F730 = '10'."""
        assert normalize_ligatures("\uF731\uF730") == "10"

    def test_pua_all_digits(self):
        """U+F730–U+F739 map to '0'–'9'."""
        pua = "".join(chr(0xF730 + i) for i in range(10))
        assert normalize_ligatures(pua) == "0123456789"

    def test_pua_lowercase_letters(self):
        """U+F761–U+F77A map to 'a'–'z'."""
        pua = "".join(chr(0xF700 + ord(c)) for c in "volume")
        assert normalize_ligatures(pua) == "volume"

    def test_pua_mixed_with_normal_text(self):
        """PUA chars mixed with regular text."""
        text = "# \uF731\uF735\n\n### THE TWELFTH-CENTURY"
        assert normalize_ligatures(text) == "# 15\n\n### THE TWELFTH-CENTURY"

    def test_pua_chapter_title_real_case(self):
        """Real case from cambridge_science_v2: chapter number as PUA."""
        text = "\uF731"
        assert normalize_ligatures(text) == "1"

    def test_control_char_ayin(self):
        """U+0002 (STX) → ʿ (ayin) in Semitic transliteration."""
        assert normalize_ligatures("Sa\x02adya") == "Saʿadya"

    def test_control_char_alef(self):
        """U+0003 (ETX) → ʾ (alef) in Semitic transliteration."""
        assert normalize_ligatures("Shmu\x03el") == "Shmuʾel"

    def test_control_chars_mixed_with_ligatures(self):
        """Control chars and ligatures in same text."""
        assert normalize_ligatures("ﬁnd Sa\x02adya") == "find Saʿadya"

    def test_no_pua_unchanged(self):
        assert normalize_ligatures("normal text 123") == "normal text 123"

    def test_ligatures_and_pua_combined(self):
        text = "ﬁnd chapter \uF732\uF737"
        assert normalize_ligatures(text) == "find chapter 27"

    def test_macron_between_letters(self):
        """Standalone macron U+00AF → combining macron on following vowel."""
        assert normalize_ligatures("Ab\u00afu") == "Abu\u0304"

    def test_macron_abbasid(self):
        """Real case: ʿAbb¯asid → ʿAbbāsid."""
        assert normalize_ligatures("\u02bfAbb\u00afasid") == "\u02bfAbba\u0304sid"

    def test_macron_dotless_i(self):
        """Macron + dotless-i (¯ı) → ī."""
        assert normalize_ligatures("Al\u00af\u0131") == "Al\u012b"

    def test_dot_below_before_macron(self):
        """Period as dot-below before macron: t.¯ı → ṭī."""
        assert normalize_ligatures("Lat.\u00af\u0131f") == "Lat\u0323\u012bf"

    def test_dot_below_before_vowel(self):
        """Period as dot-below before lowercase vowel: .a → combining dot below + a."""
        assert normalize_ligatures("Ah.mad") == "Ah\u0323mad"

    def test_dot_below_not_sentence_period(self):
        """Period at end of word is NOT a dot-below."""
        assert normalize_ligatures("end. Next") == "end. Next"

    def test_macron_not_at_word_boundary(self):
        """Standalone macron not between letters is unchanged."""
        assert normalize_ligatures("foo \u00af bar") == "foo \u00af bar"

    def test_transliteration_full_name(self):
        """Real case: Ab¯u Zakar¯ıy¯aʾ → Abū Zakarīyāʾ."""
        result = normalize_ligatures("Ab\u00afu Zakar\u00af\u0131y\u00afa\u02be")
        assert result == "Abu\u0304 Zakar\u012bya\u0304\u02be"


class TestFixHyphenation:
    def test_joins_hyphenated_word(self):
        assert fix_hyphenation("con-\ntinue") == "continue"

    def test_preserves_real_hyphens(self):
        assert fix_hyphenation("well-known\nfact") == "well-known\nfact"

    def test_no_hyphenation(self):
        assert fix_hyphenation("normal text") == "normal text"


class TestJoinBrokenSentences:
    def test_joins_mid_sentence(self):
        result = join_broken_sentences("the quick brown", "fox jumps")
        assert result == "the quick brown fox jumps"

    def test_preserves_sentence_boundary(self):
        result = join_broken_sentences("End of sentence.", "Start of next.")
        assert "\n\n" in result

    def test_empty_texts(self):
        result = join_broken_sentences("", "text")
        assert "text" in result

    def test_uppercase_start_not_joined(self):
        result = join_broken_sentences("end of paragraph", "New paragraph starts")
        assert "\n\n" in result
