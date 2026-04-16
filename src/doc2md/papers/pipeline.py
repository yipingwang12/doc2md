"""Academic paper pipeline orchestrator.

Stages: extract → column-reflow → clean → classify/section-label
        → assemble → NER → write markdown + entities.json → update index.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import requests

from doc2md.extract.detect import extract_auto
from doc2md.assembly.cleaner import (
    detect_boilerplate_lines,
    detect_repeated_lines,
    normalize_ligatures,
    strip_headers_footers,
)
from doc2md.assembly.citations import link_citations
from doc2md.assembly.footnotes import link_footnotes
from doc2md.assembly.merger import merge_chapter_text
from doc2md.analysis.classifier import classify_pages
from doc2md.analysis.chapter_detector import detect_chapters
from doc2md.config import Config
from doc2md.output.markdown_writer import write_chapters
from doc2md.papers.column_extractor import reflow_column_pages
from doc2md.papers.index_builder import (
    build_entity_index,
    load_entity_index,
    merge_into_index,
    write_entity_index_json,
    write_entity_index_md,
)
from doc2md.papers.models import NamedEntity, PaperDocument, PaperMetadata
from doc2md.papers.ner.bern2 import annotate_text
from doc2md.papers.ner.normalizer import deduplicate_entities, merge_entity_sources
from doc2md.papers.ner.pubtator import fetch_entities_by_pmid
from doc2md.papers.section_classifier import label_blocks_by_section

logger = logging.getLogger(__name__)

_DOI_RE = re.compile(r"\b(10\.\d{4,}/\S+)")
_PMID_RE = re.compile(r"(?:PMID|PubMed)[:\s]+(\d{7,8})\b", re.IGNORECASE)


def _extract_metadata_from_pages(pages) -> PaperMetadata:
    """Heuristically extract DOI and PMID from first-page text."""
    first_text = pages[0].raw_text if pages else ""
    doi = None
    pmid = None
    m = _DOI_RE.search(first_text)
    if m:
        doi = m.group(1).rstrip(".")
    m = _PMID_RE.search(first_text)
    if m:
        pmid = m.group(1)
    return PaperMetadata(doi=doi, pmid=pmid)


def _run_ner(
    paper_doc: PaperDocument,
    labelled_blocks: list,
    config: Config,
) -> list[NamedEntity]:
    """Run NER: PubTator for abstract (if PMID known), BERN2 for remaining sections."""
    pcfg = config.papers.pubtator
    bcfg = config.papers.bern2

    pubtator_entities: list[NamedEntity] = []
    if paper_doc.metadata.pmid:
        try:
            pubtator_entities = fetch_entities_by_pmid(
                paper_doc.metadata.pmid,
                base_url=pcfg.base_url,
                rate_delay=pcfg.rate_limit_delay,
            )
            logger.info("PubTator: %d entities for PMID %s", len(pubtator_entities), paper_doc.metadata.pmid)
        except requests.RequestException as exc:
            logger.warning("PubTator failed for PMID %s (%s); falling back to BERN2 for all sections", paper_doc.metadata.pmid, exc)

    # Sections handled by BERN2: everything not covered by PubTator abstract lookup
    bern2_sections = {label for _, label in labelled_blocks
                      if label not in pcfg.pubtator_sections}

    bern2_entities: list[NamedEntity] = []
    for section_label in bern2_sections:
        section_text = " ".join(
            block.text for block, label in labelled_blocks if label == section_label
        ).strip()
        if not section_text:
            continue
        try:
            section_entities = annotate_text(
                section_text,
                section_label=section_label,
                base_url=bcfg.base_url,
                timeout=bcfg.timeout,
            )
            bern2_entities.extend(section_entities)
        except requests.RequestException as exc:
            logger.warning("BERN2 failed for section '%s' (%s); skipping NER for this section", section_label, exc)

    merged = merge_entity_sources(pubtator_entities, bern2_entities)
    return deduplicate_entities(merged)


def _write_entities_json(paper_doc: PaperDocument, output_dir: Path) -> None:
    """Write per-paper entities.json alongside the paper markdown."""
    import json
    from dataclasses import asdict
    path = output_dir / paper_doc.source_name / "entities.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(e) for e in paper_doc.entities], indent=2, ensure_ascii=False))


def _write_yaml_front_matter(meta: PaperMetadata, md_path: Path) -> None:
    """Prepend YAML front matter to an existing markdown file."""
    existing = md_path.read_text()
    authors_yaml = "\n".join(f"  - {a}" for a in meta.authors) if meta.authors else "  []"
    front = (
        f"---\n"
        f"title: {meta.title or 'Unknown'}\n"
        f"authors:\n{authors_yaml}\n"
        f"journal: {meta.journal or ''}\n"
        f"year: {meta.year or ''}\n"
        f"doi: {meta.doi or ''}\n"
        f"pmid: {meta.pmid or ''}\n"
        f"---\n\n"
    )
    md_path.write_text(front + existing)


def process_paper(
    path: Path,
    config: Config,
    force: bool = False,
    pmid: str | None = None,
) -> list[Path]:
    """Full academic paper pipeline for a single PDF.

    Returns list of written output paths (markdown files).
    """
    doc_name = path.stem

    # Stage 1: Extract (digital → PyMuPDF; scanned → OCR cascade) + two-column reflow
    pages = reflow_column_pages(extract_auto(
        path,
        min_chars=config.extraction.pymupdf_min_chars,
        gibberish_threshold=config.extraction.gibberish_threshold,
    ))
    if not pages:
        logger.warning("No pages extracted from %s", path)
        return []

    # Stage 2: Normalise + clean
    for page in pages:
        page.raw_text = normalize_ligatures(page.raw_text)
    repeated = detect_repeated_lines(pages)
    boilerplate = detect_boilerplate_lines(pages)
    pages = strip_headers_footers(pages, repeated | boilerplate)

    # Stage 3: Classify + detect chapters
    blocks = classify_pages(pages, llm_client=None, repeated_lines=repeated | boilerplate)
    chapters = detect_chapters(blocks, llm_client=None)

    # Stage 4: Section labelling
    all_blocks = [b for ch in chapters for b in ch.blocks]
    labelled = label_blocks_by_section(all_blocks)

    # Stage 5: Assemble
    assembled = []
    for chapter in chapters:
        chapter = link_footnotes(chapter)
        chapter = link_citations(chapter)
        chapter = merge_chapter_text(chapter)
        assembled.append(chapter)

    # Stage 6: Write markdown
    output_dir = Path(config.papers.papers_dir)
    paths = write_chapters(assembled, output_dir, doc_name)
    if not paths:
        return []

    # Stage 7: Metadata extraction
    metadata = _extract_metadata_from_pages(pages)
    if pmid:
        metadata.pmid = pmid
    if paths:
        _write_yaml_front_matter(metadata, paths[0])

    # Stage 8: NER
    paper_doc = PaperDocument(source_name=doc_name, metadata=metadata, pages=pages, chapters=assembled)
    paper_doc.entities = _run_ner(paper_doc, labelled, config)
    logger.info("NER: %d entities for %s", len(paper_doc.entities), doc_name)

    # Stage 9: Write entities.json
    _write_entities_json(paper_doc, output_dir)

    # Stage 10: Update cross-paper index
    index_path = output_dir / "entity_index.json"
    existing_index = load_entity_index(index_path)
    new_index = build_entity_index([paper_doc])
    merged_index = merge_into_index(existing_index, new_index)
    write_entity_index_json(merged_index, index_path)
    write_entity_index_md(merged_index, index_path.with_suffix(".md"))

    return paths


def process_papers(paths: list[Path], config: Config, force: bool = False) -> list[Path]:
    """Batch process a list of paper PDFs."""
    all_outputs: list[Path] = []
    for path in paths:
        outputs = process_paper(path, config, force=force)
        all_outputs.extend(outputs)
    return all_outputs
