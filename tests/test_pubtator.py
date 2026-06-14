"""Tests for PubTator 3.0 HTTP client."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from doc2md.papers.ner.pubtator import fetch_entities_by_pmid, parse_bioc_response

# Minimal BioC JSON response matching PubTator 3.0 format
_BIOC_GENE = {
    "PubTator3": [
        {
            "pmid": "12345678",
            "passages": [
                {
                    "infons": {"type": "abstract"},
                    "text": "BRCA1 mutations increase cancer risk.",
                    "annotations": [
                        {
                            "infons": {"identifier": "672", "type": "Gene"},
                            "text": "BRCA1",
                            "locations": [{"offset": 0, "length": 5}],
                        },
                        {
                            "infons": {"identifier": "MESH:D009369", "type": "Disease"},
                            "text": "cancer",
                            "locations": [{"offset": 26, "length": 6}],
                        },
                    ],
                }
            ],
        }
    ]
}

_BIOC_EMPTY = {"PubTator3": [{"pmid": "99999999", "passages": []}]}


class TestParseBiocResponse:
    def test_parses_gene_and_disease(self):
        entities = parse_bioc_response(_BIOC_GENE["PubTator3"][0])
        assert len(entities) == 2
        gene = next(e for e in entities if e.entity_type == "gene")
        assert gene.text == "BRCA1"
        assert gene.entity_id == "NCBIGene:672"
        assert gene.source == "pubtator"
        assert gene.start == 0
        assert gene.end == 5

    def test_parses_disease(self):
        entities = parse_bioc_response(_BIOC_GENE["PubTator3"][0])
        disease = next(e for e in entities if e.entity_type == "disease")
        assert disease.text == "cancer"
        assert disease.entity_id == "MeSH:D009369"

    def test_section_label_from_passage_type(self):
        entities = parse_bioc_response(_BIOC_GENE["PubTator3"][0])
        assert all(e.section_label == "abstract" for e in entities)

    def test_empty_passages_returns_empty(self):
        assert parse_bioc_response(_BIOC_EMPTY["PubTator3"][0]) == []

    def test_unknown_type_maps_to_other(self):
        doc = {
            "passages": [{
                "infons": {"type": "title"},
                "text": "text",
                "annotations": [{
                    "infons": {"identifier": "X:1", "type": "WeirdType"},
                    "text": "foo",
                    "locations": [{"offset": 0, "length": 3}],
                }],
            }]
        }
        entities = parse_bioc_response(doc)
        assert entities[0].entity_type == "other"

    def test_annotation_without_identifier_skipped(self):
        doc = {
            "passages": [{
                "infons": {"type": "abstract"},
                "text": "text",
                "annotations": [{
                    "infons": {"type": "Gene"},
                    "text": "GENE1",
                    "locations": [{"offset": 0, "length": 5}],
                    # no "identifier" key
                }],
            }]
        }
        entities = parse_bioc_response(doc)
        assert entities == []

    def test_end_offset_computed_from_length(self):
        entities = parse_bioc_response(_BIOC_GENE["PubTator3"][0])
        gene = next(e for e in entities if e.text == "BRCA1")
        assert gene.end == gene.start + len("BRCA1")


class TestFetchEntitiesByPmid:
    def test_calls_correct_url(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = _BIOC_GENE
        mock_resp.raise_for_status = MagicMock()
        with patch("doc2md.papers.ner.pubtator.requests.get", return_value=mock_resp) as mock_get:
            fetch_entities_by_pmid("12345678", rate_delay=0)
        url = mock_get.call_args[0][0]
        params = mock_get.call_args[1].get("params", {})
        assert "biocjson" in url.lower()
        assert params.get("pmids") == "12345678"

    def test_returns_parsed_entities(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = _BIOC_GENE
        mock_resp.raise_for_status = MagicMock()
        with patch("doc2md.papers.ner.pubtator.requests.get", return_value=mock_resp):
            entities = fetch_entities_by_pmid("12345678", rate_delay=0)
        assert len(entities) == 2
        assert any(e.text == "BRCA1" for e in entities)

    def test_raises_on_http_error(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("404")
        with patch("doc2md.papers.ner.pubtator.requests.get", return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                fetch_entities_by_pmid("00000000", rate_delay=0)

    def test_empty_pubtator3_key_returns_empty(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"PubTator3": []}
        mock_resp.raise_for_status = MagicMock()
        with patch("doc2md.papers.ner.pubtator.requests.get", return_value=mock_resp):
            entities = fetch_entities_by_pmid("12345678", rate_delay=0)
        assert entities == []
