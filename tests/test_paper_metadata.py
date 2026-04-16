"""Tests for paper metadata enrichment."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from doc2md.models import Page
from doc2md.papers.metadata import (
    enrich_from_crossref,
    enrich_from_first_page,
    enrich_from_pdf_metadata,
    enrich_from_pubmed,
    enrich_metadata,
)
from doc2md.papers.models import PaperMetadata


def _page(text: str, block_dicts=None) -> Page:
    return Page(
        source_path=Path("/fake.pdf"),
        raw_text=text,
        extraction_method="pymupdf",
        block_dicts=block_dicts,
    )


def _text_block(text: str, size: float = 10.0, y: float = 100.0) -> dict:
    return {
        "type": 0,
        "bbox": (0, y, 500, y + 20),
        "lines": [{"spans": [{"text": text, "size": size, "font": "F", "flags": 0}]}],
    }


PUBMED_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <Article>
        <ArticleTitle>Comprehensive Integration of Single-Cell Data</ArticleTitle>
        <AuthorList>
          <Author>
            <LastName>Stuart</LastName>
            <ForeName>Tim</ForeName>
          </Author>
          <Author>
            <LastName>Butler</LastName>
            <ForeName>Andrew</ForeName>
          </Author>
        </AuthorList>
        <Journal>
          <Title>Cell</Title>
          <JournalIssue>
            <PubDate>
              <Year>2019</Year>
            </PubDate>
          </JournalIssue>
        </Journal>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>"""

CROSSREF_JSON = {
    "message": {
        "title": ["Comprehensive Integration of Single-Cell Data"],
        "author": [
            {"given": "Tim", "family": "Stuart"},
            {"given": "Andrew", "family": "Butler"},
        ],
        "container-title": ["Cell"],
        "issued": {"date-parts": [[2019, 6, 13]]},
    }
}


class TestEnrichFromPdfMetadata:
    def test_fills_title_and_author(self, tmp_path):
        import fitz
        doc = fitz.open()
        doc.set_metadata({"title": "Test Paper", "author": "Smith, J; Jones, A"})
        pdf_path = tmp_path / "test.pdf"
        doc.new_page()
        doc.save(str(pdf_path))
        doc.close()

        meta = PaperMetadata()
        enrich_from_pdf_metadata(pdf_path, meta)
        assert meta.title == "Test Paper"
        assert "Smith, J" in meta.authors

    def test_does_not_overwrite_existing_title(self, tmp_path):
        import fitz
        doc = fitz.open()
        doc.set_metadata({"title": "PDF Title"})
        pdf_path = tmp_path / "test.pdf"
        doc.new_page()
        doc.save(str(pdf_path))
        doc.close()

        meta = PaperMetadata(title="Existing Title")
        enrich_from_pdf_metadata(pdf_path, meta)
        assert meta.title == "Existing Title"

    def test_missing_pdf_handled_gracefully(self):
        meta = PaperMetadata()
        enrich_from_pdf_metadata(Path("/nonexistent.pdf"), meta)
        assert meta.title == ""


class TestEnrichFromPubmed:
    @patch("doc2md.papers.metadata.requests.get")
    def test_fills_all_fields(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = PUBMED_XML
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        meta = PaperMetadata()
        enrich_from_pubmed("31178118", meta)

        assert meta.title == "Comprehensive Integration of Single-Cell Data"
        assert "Tim Stuart" in meta.authors
        assert "Andrew Butler" in meta.authors
        assert meta.journal == "Cell"
        assert meta.year == 2019

    @patch("doc2md.papers.metadata.requests.get")
    def test_does_not_overwrite_existing_title(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = PUBMED_XML
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        meta = PaperMetadata(title="Already set")
        enrich_from_pubmed("31178118", meta)
        assert meta.title == "Already set"

    @patch("doc2md.papers.metadata.requests.get")
    def test_network_failure_handled_gracefully(self, mock_get):
        import requests
        mock_get.side_effect = requests.RequestException("timeout")

        meta = PaperMetadata()
        enrich_from_pubmed("31178118", meta)
        assert meta.title == ""

    @patch("doc2md.papers.metadata.requests.get")
    def test_calls_correct_url(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = PUBMED_XML
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        enrich_from_pubmed("31178118", PaperMetadata())
        call_kwargs = mock_get.call_args
        assert "eutils.ncbi.nlm.nih.gov" in call_kwargs[0][0]
        assert call_kwargs[1]["params"]["id"] == "31178118"


class TestEnrichFromCrossref:
    @patch("doc2md.papers.metadata.requests.get")
    def test_fills_all_fields(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = CROSSREF_JSON
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        meta = PaperMetadata()
        enrich_from_crossref("10.1016/j.cell.2019.05.031", meta)

        assert meta.title == "Comprehensive Integration of Single-Cell Data"
        assert "Tim Stuart" in meta.authors
        assert meta.journal == "Cell"
        assert meta.year == 2019

    @patch("doc2md.papers.metadata.requests.get")
    def test_does_not_overwrite_existing_year(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = CROSSREF_JSON
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        meta = PaperMetadata(year=2020)
        enrich_from_crossref("10.1016/j.cell.2019.05.031", meta)
        assert meta.year == 2020

    @patch("doc2md.papers.metadata.requests.get")
    def test_network_failure_handled_gracefully(self, mock_get):
        import requests
        mock_get.side_effect = requests.RequestException("timeout")

        meta = PaperMetadata()
        enrich_from_crossref("10.1016/j.cell.2019.05.031", meta)
        assert meta.title == ""


class TestEnrichFromFirstPage:
    def test_title_from_largest_font(self):
        blocks = [
            _text_block("Comprehensive Integration of Single-Cell Data", size=18.0, y=50),
            _text_block("Tim Stuart, Andrew Butler", size=11.0, y=80),
            _text_block("Body text paragraph starts here.", size=10.0, y=120),
        ]
        meta = PaperMetadata()
        enrich_from_first_page([_page("", block_dicts=blocks)], meta)
        assert "Comprehensive" in meta.title

    def test_does_not_overwrite_existing_title(self):
        blocks = [_text_block("PDF Title", size=18.0)]
        meta = PaperMetadata(title="Existing")
        enrich_from_first_page([_page("", block_dicts=blocks)], meta)
        assert meta.title == "Existing"

    def test_no_block_dicts_skipped(self):
        meta = PaperMetadata()
        enrich_from_first_page([_page("Some text")], meta)
        assert meta.title == ""

    def test_empty_pages_skipped(self):
        meta = PaperMetadata()
        enrich_from_first_page([], meta)
        assert meta.title == ""

    def test_authors_from_comma_separated_block(self):
        blocks = [
            _text_block("Paper Title Here", size=18.0, y=50),
            _text_block("Smith J, Jones A, Brown K", size=11.0, y=80),
        ]
        meta = PaperMetadata()
        enrich_from_first_page([_page("", block_dicts=blocks)], meta)
        assert len(meta.authors) >= 2


class TestEnrichMetadata:
    @patch("doc2md.papers.metadata.enrich_from_pubmed")
    @patch("doc2md.papers.metadata.enrich_from_crossref")
    @patch("doc2md.papers.metadata.enrich_from_first_page")
    @patch("doc2md.papers.metadata.enrich_from_pdf_metadata")
    def test_all_sources_called(self, mock_pdf, mock_first, mock_crossref, mock_pubmed):
        meta = PaperMetadata(pmid="12345678", doi="10.1016/test")
        enrich_metadata(Path("/fake.pdf"), [], meta)
        mock_pdf.assert_called_once()
        mock_first.assert_called_once()
        mock_pubmed.assert_called_once_with("12345678", meta)
        mock_crossref.assert_called_once_with("10.1016/test", meta)

    @patch("doc2md.papers.metadata.enrich_from_pubmed")
    @patch("doc2md.papers.metadata.enrich_from_crossref")
    @patch("doc2md.papers.metadata.enrich_from_first_page")
    @patch("doc2md.papers.metadata.enrich_from_pdf_metadata")
    def test_pubmed_skipped_without_pmid(self, mock_pdf, mock_first, mock_crossref, mock_pubmed):
        meta = PaperMetadata()
        enrich_metadata(Path("/fake.pdf"), [], meta)
        mock_pubmed.assert_not_called()
        mock_crossref.assert_not_called()

    @patch("doc2md.papers.metadata.enrich_from_pubmed")
    @patch("doc2md.papers.metadata.enrich_from_crossref")
    @patch("doc2md.papers.metadata.enrich_from_first_page")
    @patch("doc2md.papers.metadata.enrich_from_pdf_metadata")
    def test_crossref_skipped_without_doi(self, mock_pdf, mock_first, mock_crossref, mock_pubmed):
        meta = PaperMetadata(pmid="12345678")
        enrich_metadata(Path("/fake.pdf"), [], meta)
        mock_pubmed.assert_called_once()
        mock_crossref.assert_not_called()
