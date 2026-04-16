"""Tests for cross-paper entity index builder."""

import json
from pathlib import Path

from doc2md.papers.index_builder import (
    build_entity_index,
    load_entity_index,
    merge_into_index,
    write_entity_index_json,
    write_entity_index_md,
)
from doc2md.papers.models import EntityIndex, EntityOccurrence, NamedEntity, PaperDocument, PaperMetadata


def _paper(name, entities):
    return PaperDocument(
        source_name=name,
        metadata=PaperMetadata(title=name),
        entities=entities,
    )


def _entity(text, etype, eid, section="abstract", context=""):
    return NamedEntity(text=text, entity_type=etype, entity_id=eid, source="pubtator",
                       section_label=section, context=context)


class TestBuildEntityIndex:
    def test_single_paper_single_entity(self):
        paper = _paper("smith_2024", [_entity("BRCA1", "gene", "NCBIGene:672", context="BRCA1 is important.")])
        index = build_entity_index([paper])
        assert "NCBIGene:672" in index
        entry = index["NCBIGene:672"]
        assert entry.display_name == "BRCA1"
        assert entry.entity_type == "gene"
        assert len(entry.occurrences) == 1
        assert entry.occurrences[0].paper_source == "smith_2024"

    def test_two_papers_same_entity(self):
        p1 = _paper("smith_2024", [_entity("BRCA1", "gene", "NCBIGene:672")])
        p2 = _paper("jones_2023", [_entity("BRCA1", "gene", "NCBIGene:672")])
        index = build_entity_index([p1, p2])
        assert len(index["NCBIGene:672"].occurrences) == 2

    def test_different_entities_separate_entries(self):
        entities = [
            _entity("BRCA1", "gene", "NCBIGene:672"),
            _entity("cancer", "disease", "MeSH:D001943"),
        ]
        index = build_entity_index([_paper("smith", entities)])
        assert "NCBIGene:672" in index
        assert "MeSH:D001943" in index

    def test_empty_papers_returns_empty(self):
        assert build_entity_index([]) == {}

    def test_paper_with_no_entities(self):
        index = build_entity_index([_paper("empty", [])])
        assert index == {}

    def test_occurrence_section_and_context(self):
        entity = _entity("HeLa", "cell_line", "CL:0000000", section="methods", context="HeLa cells were used.")
        index = build_entity_index([_paper("test", [entity])])
        occ = index["CL:0000000"].occurrences[0]
        assert occ.section == "methods"
        assert "HeLa" in occ.context


class TestMergeIntoIndex:
    def test_new_entity_added(self):
        existing: dict = {}
        new = build_entity_index([_paper("smith", [_entity("BRCA1", "gene", "NCBIGene:672")])])
        merged = merge_into_index(existing, new)
        assert "NCBIGene:672" in merged

    def test_new_occurrence_appended(self):
        base = build_entity_index([_paper("smith", [_entity("BRCA1", "gene", "NCBIGene:672")])])
        addition = build_entity_index([_paper("jones", [_entity("BRCA1", "gene", "NCBIGene:672")])])
        merged = merge_into_index(base, addition)
        assert len(merged["NCBIGene:672"].occurrences) == 2

    def test_duplicate_occurrence_not_added(self):
        base = build_entity_index([_paper("smith", [_entity("BRCA1", "gene", "NCBIGene:672")])])
        same = build_entity_index([_paper("smith", [_entity("BRCA1", "gene", "NCBIGene:672")])])
        merged = merge_into_index(base, same)
        # same paper_source + section → deduplicated
        assert len(merged["NCBIGene:672"].occurrences) == 1


class TestWriteEntityIndexJson:
    def test_writes_valid_json(self, tmp_path):
        index = build_entity_index([_paper("smith", [_entity("BRCA1", "gene", "NCBIGene:672")])])
        out = tmp_path / "entity_index.json"
        write_entity_index_json(index, out)
        data = json.loads(out.read_text())
        assert "NCBIGene:672" in data

    def test_round_trip(self, tmp_path):
        index = build_entity_index([_paper("smith", [_entity("BRCA1", "gene", "NCBIGene:672")])])
        out = tmp_path / "entity_index.json"
        write_entity_index_json(index, out)
        loaded = load_entity_index(out)
        assert "NCBIGene:672" in loaded
        assert loaded["NCBIGene:672"].display_name == "BRCA1"

    def test_empty_index_writes_empty_json(self, tmp_path):
        out = tmp_path / "entity_index.json"
        write_entity_index_json({}, out)
        assert json.loads(out.read_text()) == {}


class TestLoadEntityIndex:
    def test_missing_file_returns_empty(self, tmp_path):
        result = load_entity_index(tmp_path / "nonexistent.json")
        assert result == {}

    def test_loads_written_index(self, tmp_path):
        index = build_entity_index([_paper("p", [_entity("TP53", "gene", "NCBIGene:7157")])])
        path = tmp_path / "idx.json"
        write_entity_index_json(index, path)
        loaded = load_entity_index(path)
        assert "NCBIGene:7157" in loaded


class TestWriteEntityIndexMd:
    def test_produces_markdown_with_entity_ids(self, tmp_path):
        index = build_entity_index([
            _paper("smith", [_entity("BRCA1", "gene", "NCBIGene:672")]),
            _paper("jones", [_entity("cancer", "disease", "MeSH:D001943")]),
        ])
        out = tmp_path / "entity_index.md"
        write_entity_index_md(index, out)
        content = out.read_text()
        assert "BRCA1" in content
        assert "smith" in content
        assert "NCBIGene:672" in content or "gene" in content

    def test_empty_index_writes_minimal_file(self, tmp_path):
        out = tmp_path / "entity_index.md"
        write_entity_index_md({}, out)
        assert out.exists()
