"""Tests for BERN2 HTTP client."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from doc2md.papers.ner.bern2 import annotate_text, parse_bern2_response

_BERN2_RESPONSE = {
    "annotations": [
        {
            "mention": "HeLa",
            "obj": "cell_line",
            "id": ["CL:0000000"],
            "span": {"begin": 0, "end": 4},
        },
        {
            "mention": "BRCA1",
            "obj": "gene",
            "id": ["NCBIGene:672"],
            "span": {"begin": 20, "end": 25},
        },
        {
            "mention": "breast cancer",
            "obj": "disease",
            "id": ["MESH:D001943"],
            "span": {"begin": 40, "end": 53},
        },
    ],
    "text": "HeLa cells express BRCA1 associated with breast cancer risk.",
}

_BERN2_EMPTY = {"annotations": [], "text": "Plain text with no entities."}

_BERN2_NO_ID = {
    "annotations": [
        {
            "mention": "UNKNOWN",
            "obj": "gene",
            "id": [],          # empty id list
            "span": {"begin": 0, "end": 7},
        }
    ],
    "text": "UNKNOWN gene expression.",
}


class TestParseBern2Response:
    def test_parses_cell_line_gene_disease(self):
        entities = parse_bern2_response(_BERN2_RESPONSE, section_label="results")
        assert len(entities) == 3
        types = {e.entity_type for e in entities}
        assert "cell_line" in types
        assert "gene" in types
        assert "disease" in types

    def test_source_is_bern2(self):
        entities = parse_bern2_response(_BERN2_RESPONSE)
        assert all(e.source == "bern2" for e in entities)

    def test_section_label_propagated(self):
        entities = parse_bern2_response(_BERN2_RESPONSE, section_label="methods")
        assert all(e.section_label == "methods" for e in entities)

    def test_offsets_correct(self):
        entities = parse_bern2_response(_BERN2_RESPONSE)
        hela = next(e for e in entities if e.text == "HeLa")
        assert hela.start == 0
        assert hela.end == 4

    def test_entity_id_taken_from_first_id(self):
        entities = parse_bern2_response(_BERN2_RESPONSE)
        gene = next(e for e in entities if e.entity_type == "gene")
        assert gene.entity_id == "NCBIGene:672"

    def test_empty_id_list_uses_fallback(self):
        entities = parse_bern2_response(_BERN2_NO_ID)
        assert len(entities) == 1
        assert entities[0].entity_id.startswith("bern2:")

    def test_empty_annotations_returns_empty(self):
        assert parse_bern2_response(_BERN2_EMPTY) == []

    def test_unknown_obj_type_maps_to_other(self):
        data = {
            "annotations": [{
                "mention": "foo",
                "obj": "weird_type",
                "id": ["X:1"],
                "span": {"begin": 0, "end": 3},
            }],
            "text": "foo bar.",
        }
        entities = parse_bern2_response(data)
        assert entities[0].entity_type == "other"


class TestAnnotateText:
    def test_posts_to_correct_endpoint(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = _BERN2_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        with patch("doc2md.papers.ner.bern2.requests.post", return_value=mock_resp) as mock_post:
            annotate_text("HeLa cells.", base_url="http://bern2.korea.ac.kr")
        url = mock_post.call_args[0][0]
        assert "bern2.korea.ac.kr" in url
        assert "plain" in url.lower()

    def test_returns_parsed_entities(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = _BERN2_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        with patch("doc2md.papers.ner.bern2.requests.post", return_value=mock_resp):
            entities = annotate_text("HeLa cells express BRCA1.", section_label="results")
        assert any(e.text == "HeLa" for e in entities)
        assert all(e.section_label == "results" for e in entities)

    def test_raises_on_timeout(self):
        with patch(
            "doc2md.papers.ner.bern2.requests.post",
            side_effect=requests.Timeout("timed out"),
        ):
            with pytest.raises(requests.Timeout):
                annotate_text("text", base_url="http://bern2.korea.ac.kr")

    def test_raises_on_http_error(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("500")
        with patch("doc2md.papers.ner.bern2.requests.post", return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                annotate_text("text")
