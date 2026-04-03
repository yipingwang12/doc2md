"""Integration tests for the pipeline orchestrator."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz
import pytest

from doc2md.config import Config
from doc2md.pipeline import process_file


@pytest.fixture
def sample_pdf(tmp_path):
    """Create a multi-page PDF with chapter structure."""
    path = tmp_path / "test_paper.pdf"
    doc = fitz.open()
    texts = [
        "Chapter 1: Introduction\n\nThis paper explores the topic of natural language processing. "
        "We build on prior work [1] to develop new methods.\n\n"
        "1 See Smith (2020) for background.",
        "The methods section describes our approach in detail. "
        "We use transformer-based models as the foundation.\n\n"
        "Figure 1: Architecture diagram of the proposed model.",
        "Chapter 2: Methods\n\nOur approach consists of three steps. "
        "First, we preprocess the data. Second, we train the model.\n\n"
        "References\n\n1. Smith J. (2020). NLP Methods. Journal of AI.",
    ]
    for text in texts:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=11)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def config(tmp_path):
    cfg = Config()
    cfg.paths.output_dir = str(tmp_path / "output")
    cfg.paths.cache_dir = str(tmp_path / "cache")
    return cfg


class TestProcessFile:
    @patch("doc2md.pipeline.OllamaClient")
    def test_full_pipeline_digital_pdf(self, MockClient, sample_pdf, config):
        mock_client = MockClient.return_value

        # Classification responses (one per page)
        mock_client.generate_json.side_effect = [
            # Page 1 classification
            [
                {"text": "Chapter 1: Introduction", "type": "heading", "heading_level": 1, "footnote_id": None},
                {"text": "This paper explores the topic of natural language processing. We build on prior work [1] to develop new methods.", "type": "body", "heading_level": None, "footnote_id": None},
                {"text": "See Smith (2020) for background.", "type": "footnote", "heading_level": None, "footnote_id": "1"},
            ],
            # Page 2 classification
            [
                {"text": "The methods section describes our approach in detail. We use transformer-based models as the foundation.", "type": "body", "heading_level": None, "footnote_id": None},
                {"text": "Figure 1: Architecture diagram of the proposed model.", "type": "caption", "heading_level": None, "footnote_id": None},
            ],
            # Page 3 classification
            [
                {"text": "Chapter 2: Methods", "type": "heading", "heading_level": 1, "footnote_id": None},
                {"text": "Our approach consists of three steps. First, we preprocess the data. Second, we train the model.", "type": "body", "heading_level": None, "footnote_id": None},
                {"text": "Smith J. (2020). NLP Methods. Journal of AI.", "type": "reference", "heading_level": None, "footnote_id": None},
            ],
            # Chapter boundary detection
            [
                {"heading_index": 0, "is_chapter_start": True},
                {"heading_index": 1, "is_chapter_start": True},
            ],
        ]

        outputs = process_file(sample_pdf, config)

        assert len(outputs) >= 1
        assert all(p.exists() for p in outputs)
        assert all(p.suffix == ".md" for p in outputs)

        # Check first chapter content
        content = outputs[0].read_text()
        assert "Introduction" in content or "Chapter 1" in content

    @patch("doc2md.pipeline.OllamaClient")
    def test_caching_skips_reprocess(self, MockClient, sample_pdf, config):
        mock_client = MockClient.return_value
        mock_client.generate_json.side_effect = [
            [{"text": "text", "type": "body", "heading_level": None, "footnote_id": None}],
            [],  # chapter boundary
        ]

        # First run
        process_file(sample_pdf, config, force=True)
        # Second run should be skipped
        outputs = process_file(sample_pdf, config, force=False)
        assert outputs == []

    @patch("doc2md.extract.ocr_extract.ocr_image", return_value="")
    @patch("doc2md.pipeline.OllamaClient")
    def test_empty_pdf_produces_empty_chapter(self, MockClient, mock_ocr, tmp_path, config):
        """An empty PDF still produces output (an empty 'Untitled' chapter)."""
        path = tmp_path / "empty.pdf"
        doc = fitz.open()
        doc.new_page()
        doc.save(path)
        doc.close()

        mock_client = MockClient.return_value
        outputs = process_file(path, config)
        # Empty page has no text, classifier skips it, but chapter detector
        # creates a single "Untitled" chapter with no blocks
        assert len(outputs) == 1
        assert outputs[0].exists()
