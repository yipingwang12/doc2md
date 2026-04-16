"""Tests for paper-specific data models."""

from pathlib import Path

from doc2md.models import Chapter, Page, TextBlock
from doc2md.papers.models import (
    EntityIndex,
    EntityOccurrence,
    NamedEntity,
    PaperDocument,
    PaperMetadata,
)


class TestPaperMetadata:
    def test_defaults(self):
        m = PaperMetadata()
        assert m.pmid is None
        assert m.doi is None
        assert m.title == ""
        assert m.authors == []
        assert m.journal == ""
        assert m.year is None

    def test_full_construction(self):
        m = PaperMetadata(
            pmid="12345678",
            doi="10.1016/j.cell.2024.01.001",
            title="BRCA1 in DNA repair",
            authors=["Smith J", "Jones A"],
            journal="Cell",
            year=2024,
        )
        assert m.pmid == "12345678"
        assert m.doi == "10.1016/j.cell.2024.01.001"
        assert m.year == 2024
        assert len(m.authors) == 2

    def test_authors_list_not_shared(self):
        m1 = PaperMetadata()
        m2 = PaperMetadata()
        m1.authors.append("Smith J")
        assert m2.authors == []


class TestNamedEntity:
    def test_defaults(self):
        e = NamedEntity(text="BRCA1", entity_type="gene", entity_id="NCBIGene:672", source="pubtator")
        assert e.section_label == ""
        assert e.start == 0
        assert e.end == 0
        assert e.context == ""

    def test_full_construction(self):
        e = NamedEntity(
            text="TP53",
            entity_type="gene",
            entity_id="NCBIGene:7157",
            source="bern2",
            section_label="results",
            start=42,
            end=46,
            context="We found that TP53 was upregulated.",
        )
        assert e.text == "TP53"
        assert e.entity_id == "NCBIGene:7157"
        assert e.source == "bern2"
        assert e.start == 42
        assert e.end == 46

    def test_entity_types(self):
        for etype in ("gene", "disease", "chemical", "species", "variant", "cell_line", "cell_type", "other"):
            e = NamedEntity(text="x", entity_type=etype, entity_id="id:1", source="pubtator")
            assert e.entity_type == etype


class TestPaperDocument:
    def test_defaults(self):
        doc = PaperDocument(source_name="smith_2024")
        assert doc.metadata.pmid is None
        assert doc.pages == []
        assert doc.chapters == []
        assert doc.entities == []

    def test_with_metadata(self):
        meta = PaperMetadata(pmid="111", title="Test Paper")
        doc = PaperDocument(source_name="test", metadata=meta)
        assert doc.metadata.pmid == "111"

    def test_entities_list_not_shared(self):
        d1 = PaperDocument(source_name="a")
        d2 = PaperDocument(source_name="b")
        e = NamedEntity(text="BRCA1", entity_type="gene", entity_id="NCBIGene:672", source="pubtator")
        d1.entities.append(e)
        assert d2.entities == []

    def test_with_pages_and_chapters(self):
        page = Page(source_path=Path("/paper.pdf"), raw_text="text", extraction_method="pymupdf")
        chapter = Chapter(title="Abstract", heading_level=1)
        doc = PaperDocument(source_name="test", pages=[page], chapters=[chapter])
        assert len(doc.pages) == 1
        assert len(doc.chapters) == 1


class TestEntityOccurrence:
    def test_construction(self):
        occ = EntityOccurrence(
            paper_source="smith_2024",
            section="results",
            context="BRCA1 was upregulated in HeLa cells.",
        )
        assert occ.paper_source == "smith_2024"
        assert occ.section == "results"
        assert "BRCA1" in occ.context


class TestEntityIndex:
    def test_defaults(self):
        idx = EntityIndex(entity_id="NCBIGene:672", entity_type="gene", display_name="BRCA1")
        assert idx.occurrences == []

    def test_with_occurrences(self):
        occ1 = EntityOccurrence(paper_source="smith_2024", section="abstract", context="ctx1")
        occ2 = EntityOccurrence(paper_source="jones_2023", section="results", context="ctx2")
        idx = EntityIndex(
            entity_id="NCBIGene:672",
            entity_type="gene",
            display_name="BRCA1",
            occurrences=[occ1, occ2],
        )
        assert len(idx.occurrences) == 2
        assert idx.occurrences[0].paper_source == "smith_2024"

    def test_occurrences_list_not_shared(self):
        i1 = EntityIndex(entity_id="id:1", entity_type="gene", display_name="X")
        i2 = EntityIndex(entity_id="id:2", entity_type="gene", display_name="Y")
        i1.occurrences.append(EntityOccurrence("p", "s", "c"))
        assert i2.occurrences == []


class TestTextBlockSectionLabel:
    """Verify the new section_label field on the shared TextBlock model."""

    def test_defaults_none(self):
        block = TextBlock(text="text", block_type="body", page_index=0)
        assert block.section_label is None

    def test_can_be_set(self):
        block = TextBlock(text="Abstract", block_type="heading", page_index=0, section_label="abstract")
        assert block.section_label == "abstract"
