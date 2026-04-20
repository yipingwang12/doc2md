"""Tests for regex-based experimental method entity extraction."""

from doc2md.papers.ner.methods import extract_method_entities


def _entities(text, section="methods"):
    return extract_method_entities(text, section)


def _ids(text, section="methods"):
    return [e.entity_id for e in _entities(text, section)]


class TestSectionFilter:
    def test_methods_section_annotated(self):
        assert _entities("We used CRISPR-Cas9.", "methods") != []

    def test_results_section_annotated(self):
        assert _entities("UMAP was applied.", "results") != []

    def test_abstract_section_annotated(self):
        assert _entities("scRNA-seq data.", "abstract") != []

    def test_references_section_skipped(self):
        assert _entities("RNA-seq protocol.", "references") == []

    def test_discussion_section_skipped(self):
        assert _entities("ChIP-seq.", "discussion") == []


class TestSequencingMethods:
    def test_scrna_seq(self):
        assert "method:scrna-seq" in _ids("We performed scRNA-seq on 10,000 cells.")

    def test_scatac_seq(self):
        assert "method:scatac-seq" in _ids("scATAC-seq profiles were generated.")

    def test_chip_seq(self):
        assert "method:chip-seq" in _ids("ChIP-seq for H3K27ac.")

    def test_rna_seq(self):
        assert "method:rna-seq" in _ids("Bulk RNA-seq was performed.")

    def test_atac_seq(self):
        assert "method:atac-seq" in _ids("ATAC-seq peaks were called.")

    def test_cite_seq(self):
        assert "method:cite-seq" in _ids("CITE-seq simultaneously measures RNA and protein.")

    def test_fish(self):
        assert "method:smfish" in _ids("smFISH probes detected mRNA.")
        assert "method:seqfish" in _ids("seqFISH+ was used for spatial profiling.")


class TestCrisprSpecificity:
    def test_crispr_cas9_preferred_over_crispr(self):
        ids = _ids("CRISPR-Cas9 knockout screen.")
        assert "method:crispr-cas9" in ids
        assert "method:crispr" not in ids

    def test_crispri(self):
        assert "method:crispri" in _ids("CRISPRi repression of target genes.")

    def test_crispr_generic(self):
        assert "method:crispr" in _ids("CRISPR library screening.")


class TestComputationalMethods:
    def test_umap(self):
        assert "method:umap" in _ids("Cells were visualised with UMAP.")

    def test_tsne(self):
        assert "method:t-sne" in _ids("t-SNE projection of embeddings.")
        assert "method:t-sne" in _ids("tSNE dimensionality reduction.")

    def test_pca(self):
        assert "method:pca" in _ids("principal component analysis was applied.")

    def test_cca(self):
        assert "method:cca" in _ids("We used canonical correlation analysis.")


class TestPlatforms:
    def test_10x_genomics(self):
        assert "method:10x-genomics" in _ids("Libraries prepared with 10x Genomics Chromium.")

    def test_drop_seq(self):
        assert "method:drop-seq" in _ids("Drop-seq was used for droplet encapsulation.")

    def test_facs(self):
        assert "method:facs" in _ids("Cells were sorted by FACS.")

    def test_flow_cytometry(self):
        assert "method:flow-cytometry" in _ids("Flow cytometry confirmed surface markers.")


class TestEntityFields:
    def test_entity_type_is_method(self):
        entities = _entities("scRNA-seq was used.")
        assert all(e.entity_type == "method" for e in entities)

    def test_source_is_regex(self):
        entities = _entities("UMAP projection.")
        assert all(e.source == "regex" for e in entities)

    def test_span_offsets(self):
        text = "We used CRISPR-Cas9 and UMAP."
        entities = _entities(text)
        for e in entities:
            assert text[e.start:e.end] == e.text

    def test_no_duplicate_spans(self):
        text = "CRISPR-Cas9 CRISPR UMAP scRNA-seq."
        entities = _entities(text)
        spans = [(e.start, e.end) for e in entities]
        assert len(spans) == len(set(spans))

    def test_results_sorted_by_position(self):
        text = "UMAP embedding. scRNA-seq data. CRISPR screen."
        entities = _entities(text, "results")
        starts = [e.start for e in entities]
        assert starts == sorted(starts)
