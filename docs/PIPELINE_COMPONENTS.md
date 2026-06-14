# Pipeline Components

Detailed reference for output format, chapter splitter, index linking, cross-volume search, and academic paper pipeline.
See [PRD.md](../PRD.md) for pipeline overview and stage descriptions.

## Output Format

Each document produces a directory under `output_dir` containing one `.md` file per chapter:

```
results/
  book_title/
    chapter_01_front_matter.md
    chapter_02_introduction.md
    ...
```

Each chapter file contains:
- Heading hierarchy (Markdown `#`/`##`/etc.)
- Body text with joined page breaks and fixed hyphenation
- Figure captions as blockquotes (`> caption`)
- Index entries as list items
- Footnotes section (`[^N]: text`)
- Numbered bibliography under `## References`

## Chapter Splitter (Implemented)

Post-processing tool that splits a single-file markdown book into per-chapter directories. Implemented in `output/chapter_splitter.py`, invoked via `doc2md split`.

### How it works

1. **TOC detection** — finds "Contents" section; uses a 150-line window to distinguish TOC entries from body occurrences (prevents false `toc_end` when Endnotes subsections repeat section names like `## PREFACE`); identifies first out-of-window body occurrence to locate where body content begins
2. **Section-level detection** — finds PART headers; named sections (Preface, Acknowledgments, Introduction, Endnotes, Notes, Conclusion, Bibliography, Index — case-sensitive to avoid ALL-CAPS subsection false matches); titled sections (CONCLUSION, APPENDIX, etc.); `Chapter One/Two/.../N: Title` via `_CHAPTER_RE` for books using that format; handles wrapped multi-line titles and HTML tag stripping; all patterns accept optional `(?:#+\s*)?` prefix to handle markdown heading-prefixed lines from Claude API output
3. **Artifact-level detection** (`--artifacts`) — within PART sections, finds individual items via numbered headings (`N. Title`) or first figure references (`FIGURE N.1`); backs up to preceding blank line for figure-only splits; extracts titles from TOC and Appendix

### Directory naming

- With page ranges (Cambridge): `010_pp_1_6_introduction/`
- Without page ranges (Boston): `010_introduction/`, `050_1_mattapan_banded_rhyolite/`

Original single-file directory archived as `.orig` to avoid duplication.

## Index Linking (Implemented)

Post-processing step that parses index chapters, matches entries to content chapters, and rewrites the index with markdown hyperlinks. Implemented in `assembly/index_linker.py`, invoked via `doc2md link-index <volume_dir>`.

### Two linking modes

1. **Page-range mode** (Cambridge) — directories named `NNN_pp_START_END_title`; `build_chapter_map()` maps page numbers to chapters; each index page ref links to its covering chapter
2. **Pageless mode** (Boston/Libby) — directories without `_pp_` naming; `build_chapter_map_pageless()` loads all chapters; each index term is searched across all chapters via `_term_in_chapter()`; links to every matching chapter

Falls back automatically: tries page-range mode first, pageless if no `_pp_` dirs found.

### Term matching

`_term_variants()` generates search variants:
- Reversed names: "Abelard, Peter" → "Peter Abelard", "Abelard"
- Parenthetical stripping: "AMS (accelerated mass spectrometer) dating" → "AMS dating"
- Colon/semicolon stripping: "Beacon Hill: as fashionable neighborhood" → "Beacon Hill"
- HTML tag stripping: `<b>Boston Town Records</b>` → "Boston Town Records"
- Preposition phrase dropping: "medicine in Africa" → "medicine"

### Index parsing

`parse_index_md()` handles main entries, sub-entries, `(cont.)` continuations, abbreviated page ranges (`516–17` → 516–517), "See also" cross-refs (plain and italic `*See also ...*`), wrapped continuation lines (detected by mid-sentence line endings), and bibliography spillover detection (stops at double blank lines or `[^YEAR]:` patterns).

`_split_term_and_refs()` strips markdown inline emphasis (`*N*` → `N`) before applying `_TRAILING_REFS_RE`, so italic illustration page refs (common in Claude API output) are extracted correctly. Returns clean (markdown-stripped) term for reliable chapter text matching.

### Idempotency

Saves original index as `.orig.md` on first run. Subsequent runs always read from `.orig.md`, preventing corruption from re-parsing linked output.

### Results

| Volume | Links | Link rate | Status |
|---|---:|---:|---|
| v2 Medieval | 3,043 | 72% | Clean |
| v3 Early Modern | 2,136 | 82% | Clean |
| v4 18th Century | 2,822 | 59% | 113 corrupt "See also" lines (semicolon format) |
| v5 Modern Phys/Math | 3,271 | 88% | Clean |
| v6 Modern Bio/Earth | 2,654 | 80% | Clean |
| v7 Modern Social | 2,753 | 87% | Clean |
| v8 National/Global | 2,082 | 80% | Clean |
| Boston Artifacts (Surya) | 1,666 | 85% | Pageless mode, 59 artifact-level chapters |
| Boston Artifacts (Claude API) | 396 | — | Pageless mode, 35 chapters; 388 unique terms linked |
| **Total** | **20,823** | | **7 of 8 clean** |

### Known issues

1. **V4 semicolon-delimited format** — v4's index `.orig.md` was corrupted by a previous buggy run (linked output was saved back as the original). The parser is now correct for new extractions; v4 needs re-extraction from the PDF to regenerate a clean index.

2. ~~**Years parsed as page numbers**~~ — fixed: `_filter_year_refs()` in `link_index` computes `max_page = max(ch.page_end for ch in chapters)` and moves refs exceeding that threshold back into the term text.

3. ~~**Italic page refs unlinked (pageless mode)**~~ — fixed: `_split_term_and_refs()` strips `*N*` markdown before `_TRAILING_REFS_RE`; pageless renderer no longer exits early on entries with empty `page_refs`; `*See also*` italic wrapper now recognized by the "See also" extractor.

4. **Unmatched generic sub-entries** — terms like "overview", "general discussion", "in optics" don't appear verbatim in chapter text (~15–20% of refs). Correctly left as plain text by the conservative matching approach.

5. **`index` block type unused** — the segmenter still classifies index content as `body` blocks. The `index` type in `TextBlock` is defined and handled by `markdown_writer.py` but never assigned. Orthogonal to linking.

## Cross-Volume Entity Search

### Overview

Search for a person, concept, or term across all processed volumes and extract surrounding paragraphs. Implemented in `assembly/search.py`, invoked via `doc2md search <term>`.

### Phase 1: Index-guided search (Implemented)

Leverages the 18,761 existing index links as a pre-built entity-to-passage map. Zero additional dependencies.

`doc2md search <term> [--context N]`:

1. Scans all volumes' linked index files for the search term
2. Follows markdown links to extract referenced chapter paragraphs
3. Groups results by volume/chapter with display names (e.g. "Islamic Culture (pp. 27–61)")
4. Outputs matching passages with optional surrounding paragraph context

### Future phases

#### Phase 2: Full-text search (add `sqlite-utils`)

`doc2md build-search` chunks all chapters into paragraphs, indexes in SQLite FTS5. Combine with Phase 1: index-guided results first (high precision), FTS5 second (high recall). Covers volumes without indexes (v1, Boston Artifacts).

#### Phase 3: Semantic search + coreference (add `sentence-transformers`, `faiss-cpu`, `fastcoref`)

Embed paragraphs with a local model, index in FAISS, run coreference resolution on retrieved passages to expand "Einstein" → "he" / "the physicist". Optionally pass through Ollama for synthesis.

#### Why not GraphRAG first

GraphRAG requires LLM calls for every chunk during indexing — expensive on a 3M-word corpus. Phases 1–3 get 90% of value with minimal compute. GraphRAG would add value for complex multi-hop queries but can wait until simpler phases prove insufficient.

## Academic Paper Pipeline (Implemented)

Ingests academic PDFs (e.g. Cell journal), converts to structured markdown, runs biomedical entity recognition, and generates a cross-paper entity index. Tested on Stuart et al. 2019 (Seurat v3, *Cell*).

### PDF extraction

**PyMuPDF remains the right tool for digital PDFs.** Cell papers are born-digital; PyMuPDF extracts text directly from PDF objects at ~0.12 sec/page with perfect fidelity. Marker and MinerU were evaluated as alternatives: both are 10–90× slower on digital PDFs (Marker uses PyMuPDF internally as its first step), and both show documented regressions on two-column journal layouts. Scanned content already has the Surya cascade. No change to the extraction layer is needed.

**Two-column layout**: PyMuPDF's `get_text("dict")` reads blocks in document order, which for two-column PDFs may interleave columns. Mitigation: use `sort=True` in `get_text()` to get spatial reading order, or detect column bounds via `chrome_cropper.detect_column_bounds()` (already implemented).

**GROBID** (not adopted) would add structured metadata extraction (authors, DOI, section headers in TEI/XML) but outputs XML rather than readable markdown, requires a running server, and is slower. Worth revisiting if reliable metadata extraction proves difficult with heuristics.

### NotebookLM evaluation

Evaluated and **rejected for this use case**. NotebookLM is a RAG chat interface: it answers questions across uploaded PDFs but cannot systematically extract entities, produces no machine-readable output (copy-paste only), and has no export beyond Google Sheets via the manual Data Tables feature. Hallucination rate ~13% makes it unsuitable for a structured index. No documented use case of systematic entity extraction from a paper corpus exists.

### Biomedical NER: PubTator 3.0 + BERN2 cascade

Two complementary tools; use in cascade:

**PubTator 3.0** (primary): NCBI's pre-computed annotation service covering 36M PubMed abstracts + 6M PMC full-text articles, updated weekly. Query by PMID → returns structured JSON/BioC with normalized entity IDs (NCBI Gene IDs, MeSH terms). ~67 seconds for 200 papers at the 3 req/sec rate limit. Entity types: genes, diseases, chemicals, variants, species, cell lines. F1: genes 84.6, variants 98.5, species 95.2. Nearly all Cell papers are PMC-indexed, so annotations are pre-computed. Known weakness: low precision in methods sections (complex protocols, abbreviations).

**BERN2** (fallback): processes arbitrary text via HTTP API or local install; ~55 min for 200 papers via API (use local install for bulk). Better than PubTator on diseases (F1 88.6 vs 79.2) and chemicals (92.8 vs 81.9). Covers 9 entity types vs PubTator's 6 (adds cell types, DNA/RNA). Use for papers not in PMC or to supplement PubTator on entity types it undershoots.

Neither tool handles experimental methods (CRISPR, ChIP-seq, etc.) well. **Regex layer implemented** (`papers/ner/methods.py`): 35-pattern vocabulary covering sequencing methods (scRNA-seq, ChIP-seq, ATAC-seq, CITE-seq, etc.), CRISPR variants (specific-before-general ordering), spatial transcriptomics (Visium, seqFISH, STARmap), RNAi, flow cytometry, and computational methods (UMAP, t-SNE, PCA, CCA). Runs on abstract/introduction/methods/results sections; skips references/discussion. Ollama hook for complex protocol extraction is future work.

### Cross-paper entity index

Once entities are normalized to canonical IDs (NCBI Gene ID, MeSH CUI), cross-paper indexing is a **simple inverted index**: `{entity_id → [{paper, section, context}]}`. Normalization — the hard part — is already done by PubTator/BERN2. Implementation is ~1–2 weeks of Python/SQLite. Phase 1 output: `entity_index.json` + `entity_index.md` per corpus.

**GraphRAG and LlamaIndex KnowledgeGraphIndex** were evaluated. Both add *relationship extraction* (subject-verb-object triples via LLM calls), not entity identification. GraphRAG costs ~$10–20 in LLM API calls for 200 papers and adds 3–4 weeks of engineering. The payoff is multi-hop relational queries ("genes that activate a protein in Cell Line X") vs. co-occurrence queries ("papers mentioning Gene X"). For Phase 1 the simple inverted index covers the stated need; graph extraction is a natural Phase 2.

### Proposed pipeline

```
PDF → PyMuPDF extract → clean/segment (paper sections) → PMID lookup → PubTator annotations
                                                        ↘ (not in PMC) → BERN2 on raw text
→ merge + normalize entities → inverted index → entity_index.json + entity_index.md
```

### Implemented pipeline stages

```
doc2md papers process <pdf>          # full pipeline: extract → clean → segment → NER → markdown + entities.json + entity_index
```

Stages: PyMuPDF extract → two-column reflow → normalize ligatures → strip watermarks/symbols → header/footer removal → classify blocks → detect chapters → section labelling → link footnotes/citations → merge text → write markdown → enrich metadata → NER (PubTator + BERN2) → write entities.json → update entity_index.json + entity_index.md → figure extraction.

**Metadata enrichment** (`papers/metadata.py`): four-source cascade (PDF metadata → first-page font heuristics → PubMed efetch XML → CrossRef REST API), each source only fills empty fields.

**Figure extraction** (`papers/figure_extractor.py`): raster images via `get_images(full=True)` + `extract_image(xref)` (skip < 150px); vector fallback via `get_pixmap(clip=bbox)` on type-1 image blocks; caption matched as nearest text block starting with "Figure"/"Fig." within 150pt. Per-page deduplication: when multiple images share the same caption ID, the largest (by area) wins; uncaptioned subpanels are dropped when any captioned figure exists on the page (kept with fallback IDs `p{page}i{idx}` only on fully uncaptioned pages). Saves to `output_dir/figures/` with `figures.json` index.

**Preprint watermark filter**: strips bioRxiv/medRxiv CC-BY notices from `raw_text` (cleaner) and from block dicts (segmenter). Also strips symbol-only lines (U+25CF ●, U+2022 •, etc.) that are PDF encoding artifacts from data tables/figures — both in `strip_preprint_watermarks()` and in `_is_boilerplate()`.

**Figure panel label filter**: single-letter or N/M fraction blocks (e.g. "A", "2/24") detected by `_is_figure_panel_label()` and dropped before heading classification. **Math expression filter** (`_is_math_expression()`): blocks containing `=`, `−`, `ˆ`, `˜`, or Unicode Greek/math symbols are dropped — applied to the large-font, heading-font, AND all-caps branches. Equations like `C = BW T` and `I = N` pass `_is_all_caps_heading()` because all their letters happen to be uppercase; the math filter now catches these in all three branches.

### Processing log: Stuart et al. 2019 (Seurat v3)

- **Source**: bioRxiv preprint PDF downloaded from bioRxiv (`10.1101/460147`), 24 pages, 19 MB
- **Extraction**: PyMuPDF, all 24 pages have block_dicts; two-column reflow applied
- **NER**: PubTator (PMID 31178118) + regex method extractor (147 method entities: scRNA-seq, ATAC-seq, CITE-seq, STARmap, UMAP, CCA, etc.); BERN2 public API down at test time
- **Figures**: 8 extracted — Figures 1, 2, 4, 5 captioned; page 6 has 4 unlabeled subpanels (fallback IDs p6i0–p6i3, likely Figure 3 panels)
- **Headings fixed**: `C = BW T` and `I = N` (Methods equations) were misclassified as headings via the ALL_CAPS branch; fixed by adding `_is_math_expression()` guard there
- **Runtime**: ~21 sec (network-bound by PubTator lookup; local extraction ~3 sec)

### Known paper pipeline issues (found via Playwright e-reader audit)

1. **Superscripts as footnote refs** — author affiliation numbers (`[^1]`, `[^2]`), citation superscripts, and subscript gene names (`CD[^4]`, `Gad[^2]`) are all emitted as `[^N]` markdown footnote syntax. The reader renders these as 321 footnote links against only ~5 actual definitions. Root cause: superscript spans in PyMuPDF are not distinguished from true footnote markers during extraction; need a heuristic to suppress mid-line superscripts that are citation/affiliation numbers.

2. **Figure refs not clickable** — 31 "Figure N" text references appear in the markdown, but none are wired to the figure modal in the reader. The modal only activates for images embedded inline; text refs need to be converted to `<span data-fig="N">Figure N</span>` anchors during rendering.

3. **`Reference`/`Query` diagram labels as headings** — these single-word figure-axis labels appear as `### Reference` / `### Query` throughout the Results section. They cannot be filtered by `_is_math_expression` or `_is_figure_panel_label`; suppressing them requires page-level figure detection (e.g. skip heading classification for blocks that overlap with an image bounding box).

4. **Library card title** — the papers folder shows `"Papers1 chapters"` (no separator between title span and chapter-count span). Reader `build_library.py` uses the results subfolder name (`papers`) as the book title; should use the YAML `title` field from the first chapter's front matter instead.

5. **Topbar shows folder name** — reader topbar displays `"Papers"` instead of the paper's actual title. Same root cause as #4.

6. **Author metadata parsing** — affiliation superscripts (`1`, `2`, `*`) are extracted as separate list items in the YAML `authors` field. The metadata extractor needs to strip trailing superscript tokens from author name strings.

7. **Garbled table text** — comparison table cells produce `"80$3B"` artifacts (PDF encoding of method name abbreviations). Not caught by the preprint watermark filter; needs a separate table-cell artifact filter or a minimum word-length heuristic.
