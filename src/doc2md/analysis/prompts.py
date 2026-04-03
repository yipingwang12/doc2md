"""LLM prompt templates for structural analysis."""

PAGE_NUMBER_DETECTION = """Given the following OCR text from a book page, extract the page number.
Return JSON: {{"page_number": <int or null>, "confidence": <float 0-1>}}
If there is no visible page number, return null for page_number.

Text:
---
{page_text}
---"""

BLOCK_CLASSIFICATION = """You are analyzing a page from an academic text. Classify each paragraph into one of these types: heading, body, footnote, caption, reference, index.

For headings, also provide the level (1=chapter, 2=section, 3=subsection).
For footnotes, extract the footnote number.

Return a JSON array of objects:
[{{"text": "...", "type": "heading|body|footnote|caption|reference|index", "heading_level": null|1|2|3, "footnote_id": null|"1"|"2"|...}}]

Page text:
---
{page_text}
---"""

CHAPTER_BOUNDARY_DETECTION = """Given these headings extracted from a document in order, identify which ones are chapter-level boundaries. A chapter boundary is typically:
- "Chapter N: Title", "Part N", or a heading-1 level marker
- A major topic shift indicated by a prominent heading

Headings:
{headings_json}

Return a JSON array:
[{{"heading_index": <int>, "is_chapter_start": true|false}}]"""

DUPLICATE_DETECTION = """Are these two page texts from the same page of a book? They may have minor OCR differences. Return JSON: {{"is_duplicate": true|false, "confidence": <float 0-1>}}

Page A (first 300 chars):
---
{text_a}
---

Page B (first 300 chars):
---
{text_b}
---"""


def format_page_number(page_text: str) -> str:
    return PAGE_NUMBER_DETECTION.format(page_text=page_text[:500])


def format_block_classification(page_text: str) -> str:
    return BLOCK_CLASSIFICATION.format(page_text=page_text)


def format_chapter_boundary(headings_json: str) -> str:
    return CHAPTER_BOUNDARY_DETECTION.format(headings_json=headings_json)


def format_duplicate_detection(text_a: str, text_b: str) -> str:
    return DUPLICATE_DETECTION.format(text_a=text_a[:300], text_b=text_b[:300])
