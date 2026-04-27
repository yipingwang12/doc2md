"""OCR prompts for ClaudeApiEngine.

BASE_PROMPT applies to all books.
Book-specific sections in _EXTRAS are appended for known sources.
Use build_prompt(book) to get the combined prompt.
"""

from __future__ import annotations

BASE_PROMPT = """\
Transcribe every word on this book page verbatim into Markdown. Do NOT summarize or paraphrase.
- Headings: use # / ## / ### based on apparent visual hierarchy
- Body text: reproduce word-for-word, joining hyphenated line-breaks
- Footnote markers in body text: keep inline as `[^N]`
- Footnote definitions: emit as `[^N]: text` ONLY if the full footnote text is visible on this page; never invent placeholder definitions
- Figure captions: emit as `> caption text`
- Page numbers, running headers/footers: omit
- Purely decorative images with no text: output nothing
Output only the Markdown, no preamble or explanation."""


_EXTRAS: dict[str, str] = {

    "boston": """\
Book-specific notes (A History of Boston in 50 Artifacts):
- This is a single-column Libby half-page; no column reordering needed
- Running header (top line repeating the book or chapter title): omit
- PART headings appear as "PART N Title" — use `# PART N: Title`
- Artifact headings appear as "N. Title" (e.g. "3. Fishweir Stakes") — use `# N. Title`
- Figure captions appear below artifact photos — use `> caption text`
- In the Notes section, full footnote definitions are visible — emit them as `[^N]: text`
- Index entries use italic page numbers for illustrations (e.g. "alewife, 17, *18*") — preserve the italics""",

    "morocco": """\
Book-specific notes (Morocco: Globalization and Its Consequences):
- Pages use a two-column layout: transcribe the LEFT column in full first, then the RIGHT column
- The very top line of the page is a running header (book title or chapter name): omit it
- Chapter-title pages show a centered chapter number ("One", "Two", "Three" …) and subtitle — use `# Chapter [Number]: Subtitle`
- Section subheadings appear in bold or ALL CAPS within chapters — use `##`
- Endnote markers in the body are small superscript numbers — transcribe as `[^N]`
- In the Endnotes section, full definitions are visible — emit them as `[^N]: text`
- The Bibliography lists numbered references — transcribe as a numbered list
- The Index has two columns of alphabetical entries — transcribe left column first, then right
- Occasional maps or charts with no readable text: output nothing""",

}


def build_prompt(book: str | None = None) -> str:
    """Return the OCR prompt for the given book key (or base prompt if None/unknown)."""
    if book and book in _EXTRAS:
        return BASE_PROMPT + "\n\n" + _EXTRAS[book]
    return BASE_PROMPT


KNOWN_BOOKS = list(_EXTRAS.keys())
