"""Tests for NER entity normalizer."""

from doc2md.papers.models import NamedEntity
from doc2md.papers.ner.normalizer import (
    deduplicate_entities,
    map_entity_type,
    merge_entity_sources,
)


def _entity(text, etype, eid, source="pubtator", start=0, end=5, section="abstract"):
    return NamedEntity(
        text=text, entity_type=etype, entity_id=eid,
        source=source, section_label=section, start=start, end=end,
    )


class TestMapEntityType:
    def test_known_pubtator_types(self):
        assert map_entity_type("gene") == "gene"
        assert map_entity_type("disease") == "disease"
        assert map_entity_type("chemical") == "chemical"
        assert map_entity_type("species") == "species"
        assert map_entity_type("variant") == "variant"
        assert map_entity_type("cell_line") == "cell_line"
        assert map_entity_type("cell_type") == "cell_type"

    def test_known_bern2_types(self):
        assert map_entity_type("cellline") == "cell_line"
        assert map_entity_type("celltype") == "cell_type"
        assert map_entity_type("protein") == "gene"
        assert map_entity_type("drug") == "chemical"
        assert map_entity_type("mutation") == "variant"

    def test_unknown_maps_to_other(self):
        assert map_entity_type("foobar") == "other"
        assert map_entity_type("") == "other"


class TestMergeEntitySources:
    def test_non_overlapping_all_included(self):
        pub = [_entity("BRCA1", "gene", "NCBIGene:672", start=0, end=5)]
        bern = [_entity("cancer", "disease", "MeSH:D1", "bern2", start=20, end=26)]
        result = merge_entity_sources(pub, bern)
        assert len(result) == 2

    def test_overlapping_span_pubtator_wins(self):
        pub = [_entity("BRCA1", "gene", "NCBIGene:672", "pubtator", start=0, end=5)]
        bern = [_entity("BRCA1", "gene", "NCBIGene:672", "bern2", start=0, end=5)]
        result = merge_entity_sources(pub, bern)
        assert len(result) == 1
        assert result[0].source == "pubtator"

    def test_partial_overlap_both_kept(self):
        # Different start/end = not an exact span match → conservative, keep both
        pub = [_entity("BRCA", "gene", "NCBIGene:672", start=0, end=4)]
        bern = [_entity("BRCA1", "gene", "NCBIGene:672", "bern2", start=0, end=5)]
        result = merge_entity_sources(pub, bern)
        assert len(result) == 2

    def test_empty_inputs(self):
        assert merge_entity_sources([], []) == []
        assert merge_entity_sources([_entity("A", "gene", "id:1")], []) == [_entity("A", "gene", "id:1")]
        assert merge_entity_sources([], [_entity("A", "gene", "id:1", "bern2")]) == [
            _entity("A", "gene", "id:1", "bern2")
        ]


class TestDeduplicateEntities:
    def test_exact_duplicates_removed(self):
        e1 = _entity("BRCA1", "gene", "NCBIGene:672", start=0, end=5)
        e2 = _entity("BRCA1", "gene", "NCBIGene:672", start=0, end=5)
        result = deduplicate_entities([e1, e2])
        assert len(result) == 1

    def test_same_id_different_span_both_kept(self):
        e1 = _entity("BRCA1", "gene", "NCBIGene:672", start=0, end=5)
        e2 = _entity("BRCA1", "gene", "NCBIGene:672", start=100, end=105)
        result = deduplicate_entities([e1, e2])
        assert len(result) == 2

    def test_different_ids_both_kept(self):
        e1 = _entity("BRCA1", "gene", "NCBIGene:672", start=0, end=5)
        e2 = _entity("TP53", "gene", "NCBIGene:7157", start=0, end=4)
        result = deduplicate_entities([e1, e2])
        assert len(result) == 2

    def test_empty_returns_empty(self):
        assert deduplicate_entities([]) == []

    def test_preserves_order(self):
        entities = [
            _entity("A", "gene", "id:1", start=0, end=1),
            _entity("B", "gene", "id:2", start=5, end=6),
            _entity("C", "gene", "id:3", start=10, end=11),
        ]
        result = deduplicate_entities(entities)
        assert [e.text for e in result] == ["A", "B", "C"]
