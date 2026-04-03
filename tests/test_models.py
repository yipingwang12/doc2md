"""Tests for data models."""

import hashlib
from pathlib import Path

from doc2md.models import Chapter, Document, Page, TextBlock


class TestPage:
    def test_content_hash_auto_computed(self):
        page = Page(source_path=Path("/test.pdf"), raw_text="hello", extraction_method="pymupdf")
        expected = hashlib.sha256(b"hello").hexdigest()
        assert page.content_hash == expected

    def test_content_hash_preserved_if_provided(self):
        page = Page(
            source_path=Path("/test.pdf"),
            raw_text="hello",
            extraction_method="pymupdf",
            content_hash="custom_hash",
        )
        assert page.content_hash == "custom_hash"

    def test_page_number_defaults_none(self):
        page = Page(source_path=Path("/test.pdf"), raw_text="text", extraction_method="surya")
        assert page.page_number is None

    def test_different_text_different_hash(self):
        p1 = Page(source_path=Path("/a.pdf"), raw_text="text1", extraction_method="pymupdf")
        p2 = Page(source_path=Path("/a.pdf"), raw_text="text2", extraction_method="pymupdf")
        assert p1.content_hash != p2.content_hash


class TestTextBlock:
    def test_basic_body_block(self):
        block = TextBlock(text="paragraph", block_type="body", page_index=0)
        assert block.heading_level is None
        assert block.footnote_id is None
        assert block.citation_key is None

    def test_heading_block(self):
        block = TextBlock(text="Chapter 1", block_type="heading", page_index=0, heading_level=1)
        assert block.heading_level == 1

    def test_footnote_block(self):
        block = TextBlock(text="See note", block_type="footnote", page_index=3, footnote_id="5")
        assert block.footnote_id == "5"


class TestChapter:
    def test_empty_chapter(self):
        ch = Chapter(title="Introduction", heading_level=1)
        assert ch.blocks == []
        assert ch.footnotes == {}
        assert ch.bibliography == []

    def test_chapter_with_content(self):
        block = TextBlock(text="content", block_type="body", page_index=0)
        ch = Chapter(title="Ch1", heading_level=1, blocks=[block], footnotes={"1": "note"})
        assert len(ch.blocks) == 1
        assert ch.footnotes["1"] == "note"


class TestDocument:
    def test_empty_document(self):
        doc = Document(source_name="test_book")
        assert doc.pages == []
        assert doc.chapters == []
        assert doc.metadata == {}

    def test_document_with_pages(self):
        page = Page(source_path=Path("/a.pdf"), raw_text="text", extraction_method="pymupdf")
        doc = Document(source_name="paper", pages=[page])
        assert len(doc.pages) == 1
