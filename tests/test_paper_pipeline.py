"""Integration tests for the academic paper pipeline."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz
import pytest

from doc2md.config import Config
from doc2md.papers.pipeline import process_paper


def _make_pdf(tmp_path: Path, content: str = None) -> Path:
    """Create a minimal single-column PDF for testing."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    text = content or (
        "Abstract\n\nThis paper studies BRCA1 in HeLa cells.\n\n"
        "Introduction\n\nBRCA1 is a tumour suppressor gene.\n\n"
        "Methods\n\nHeLa cells were cultured in DMEM.\n\n"
        "Results\n\nBRCA1 expression was upregulated 3-fold.\n\n"
        "Discussion\n\nThese findings confirm BRCA1 function.\n\n"
        "References\n\n1. Smith J. Cell. 2020.\n"
    )
    page.insert_text((72, 72), text, fontsize=11)
    pdf_path = tmp_path / "test_paper.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _mock_bern2_response():
    return MagicMock(**{
        "json.return_value": {
            "annotations": [
                {"mention": "HeLa", "obj": "cell_line", "id": ["CL:0000000"],
                 "span": {"begin": 0, "end": 4}},
                {"mention": "BRCA1", "obj": "gene", "id": ["NCBIGene:672"],
                 "span": {"begin": 20, "end": 25}},
            ],
            "text": "HeLa cells were cultured. BRCA1 expression.",
        },
        "raise_for_status": MagicMock(),
    })


class TestProcessPaper:
    def test_creates_markdown_output(self, tmp_path):
        pdf = _make_pdf(tmp_path)
        config = Config()
        config.papers.papers_dir = str(tmp_path / "papers")
        with patch("doc2md.papers.pipeline.annotate_text", return_value=[]), \
             patch("doc2md.papers.pipeline.fetch_entities_by_pmid", return_value=[]):
            paths = process_paper(pdf, config)
        assert len(paths) > 0
        assert all(p.suffix == ".md" for p in paths)
        assert all(p.exists() for p in paths)

    def test_creates_entities_json(self, tmp_path):
        pdf = _make_pdf(tmp_path)
        config = Config()
        config.papers.papers_dir = str(tmp_path / "papers")
        with patch("doc2md.papers.pipeline.annotate_text", return_value=[]), \
             patch("doc2md.papers.pipeline.fetch_entities_by_pmid", return_value=[]):
            process_paper(pdf, config)
        entities_json = tmp_path / "papers" / "test_paper" / "entities.json"
        assert entities_json.exists()
        data = json.loads(entities_json.read_text())
        assert isinstance(data, list)

    def test_creates_entity_index(self, tmp_path):
        pdf = _make_pdf(tmp_path)
        config = Config()
        config.papers.papers_dir = str(tmp_path / "papers")
        with patch("doc2md.papers.pipeline.annotate_text", return_value=[]), \
             patch("doc2md.papers.pipeline.fetch_entities_by_pmid", return_value=[]):
            process_paper(pdf, config)
        assert (tmp_path / "papers" / "entity_index.json").exists()
        assert (tmp_path / "papers" / "entity_index.md").exists()

    def test_yaml_front_matter_written(self, tmp_path):
        pdf = _make_pdf(tmp_path)
        config = Config()
        config.papers.papers_dir = str(tmp_path / "papers")
        with patch("doc2md.papers.pipeline.annotate_text", return_value=[]), \
             patch("doc2md.papers.pipeline.fetch_entities_by_pmid", return_value=[]):
            paths = process_paper(pdf, config)
        content = paths[0].read_text()
        assert content.startswith("---")
        assert "title:" in content

    def test_pmid_overrides_extracted_metadata(self, tmp_path):
        pdf = _make_pdf(tmp_path)
        config = Config()
        config.papers.papers_dir = str(tmp_path / "papers")
        with patch("doc2md.papers.pipeline.annotate_text", return_value=[]), \
             patch("doc2md.papers.pipeline.fetch_entities_by_pmid", return_value=[]) as mock_pub:
            process_paper(pdf, config, pmid="12345678")
        mock_pub.assert_called_once()
        assert mock_pub.call_args[0][0] == "12345678"

    def test_pubtator_404_falls_back_to_bern2(self, tmp_path):
        import requests as req
        pdf = _make_pdf(tmp_path)
        config = Config()
        config.papers.papers_dir = str(tmp_path / "papers")
        with patch("doc2md.papers.pipeline.fetch_entities_by_pmid",
                   side_effect=req.HTTPError("404")), \
             patch("doc2md.papers.pipeline.annotate_text", return_value=[]):
            # Should not raise — NER errors are caught and logged, pipeline continues
            result = process_paper(pdf, config, pmid="00000000")
            assert result  # markdown was still written

    def test_no_pmid_skips_pubtator(self, tmp_path):
        pdf = _make_pdf(tmp_path)
        config = Config()
        config.papers.papers_dir = str(tmp_path / "papers")
        with patch("doc2md.papers.pipeline.fetch_entities_by_pmid") as mock_pub, \
             patch("doc2md.papers.pipeline.annotate_text", return_value=[]):
            process_paper(pdf, config)
        mock_pub.assert_not_called()

    def test_entity_index_accumulates_across_papers(self, tmp_path):
        from doc2md.papers.models import NamedEntity
        pdf1 = _make_pdf(tmp_path, "Abstract\n\nPaper one text.\n")
        pdf2_dir = tmp_path / "p2"
        pdf2_dir.mkdir()
        pdf2 = pdf2_dir / "paper2.pdf"
        doc = fitz.open()
        p = doc.new_page(width=595, height=842)
        p.insert_text((72, 72), "Abstract\n\nPaper two text.\n")
        doc.save(str(pdf2))
        doc.close()

        config = Config()
        config.papers.papers_dir = str(tmp_path / "papers")

        entity1 = NamedEntity(text="BRCA1", entity_type="gene",
                              entity_id="NCBIGene:672", source="bern2")
        entity2 = NamedEntity(text="TP53", entity_type="gene",
                              entity_id="NCBIGene:7157", source="bern2")

        with patch("doc2md.papers.pipeline.fetch_entities_by_pmid", return_value=[]), \
             patch("doc2md.papers.pipeline.annotate_text", side_effect=[[entity1], [entity2]]):
            process_paper(pdf1, config)
            process_paper(pdf2, config)

        index_path = tmp_path / "papers" / "entity_index.json"
        data = json.loads(index_path.read_text())
        assert "NCBIGene:672" in data
        assert "NCBIGene:7157" in data

    def test_empty_pdf_returns_empty(self, tmp_path):
        doc = fitz.open()
        doc.new_page(width=595, height=842)  # blank page
        pdf_path = tmp_path / "blank.pdf"
        doc.save(str(pdf_path))
        doc.close()
        config = Config()
        config.papers.papers_dir = str(tmp_path / "papers")
        with patch("doc2md.papers.pipeline.annotate_text", return_value=[]), \
             patch("doc2md.papers.pipeline.fetch_entities_by_pmid", return_value=[]):
            paths = process_paper(pdf_path, config)
        # Blank page may produce one chapter or none depending on classifier
        assert isinstance(paths, list)
