"""Pipeline orchestrator: runs all stages in sequence."""

from __future__ import annotations

import logging
from pathlib import Path

from doc2md.analysis.chapter_detector import detect_chapters
from doc2md.analysis.classifier import classify_pages
from doc2md.analysis.llm_client import OllamaClient
from doc2md.assembly.citations import link_citations
from doc2md.assembly.cleaner import (
    detect_boilerplate_lines,
    detect_repeated_lines,
    normalize_ligatures,
    strip_headers_footers,
)
from doc2md.assembly.footnotes import link_footnotes
from doc2md.assembly.merger import merge_chapter_text
from doc2md.cache import Cache
from doc2md.config import Config
from doc2md.extract.detect import extract_auto
from doc2md.extract.ocr_extract import extract_screenshots
from doc2md.extract.screenshot_extract import (
    extract_screenshot_spread,
    is_browser_screenshot,
    is_libby_spread,
)
from doc2md.ingest.file_scanner import ScanResult, scan_directories
from doc2md.models import Document, Page
from doc2md.ordering.dedup import deduplicate
from doc2md.ordering.reorder import detect_page_numbers, find_page_gaps, reorder_pages
from doc2md.output.markdown_writer import write_chapters

logger = logging.getLogger(__name__)


def process_file(path: Path, config: Config, force: bool = False) -> list[Path]:
    """Process a single PDF or screenshot folder through the full pipeline."""
    cache = Cache(config.paths.cache_dir)

    if not force and cache.is_complete(path):
        logger.info("Skipping already-processed: %s", path)
        return []

    llm_client = OllamaClient(
        base_url=config.llm.base_url,
        model=config.llm.model,
        timeout=config.llm.timeout,
        max_retries=config.llm.max_retries,
    )

    doc_name = path.stem if path.is_file() else path.name
    is_libby = path.is_dir() and is_libby_spread(path)
    is_browser = path.is_dir() and not is_libby and is_browser_screenshot(path)
    is_ordered = is_libby or is_browser

    # Stage 1: Extract
    completed = cache.get_completed_stages(path)
    if "extract" not in completed or force:
        if path.is_dir():
            if is_libby:
                pages = extract_screenshot_spread(path)
            else:
                pages = extract_screenshots(path, auto_number=is_ordered)
        else:
            pages = extract_auto(
                path,
                min_chars=config.extraction.pymupdf_min_chars,
                gibberish_threshold=config.extraction.gibberish_threshold,
            )
        cache.mark_stage(path, "extract")
    else:
        # Re-extract since we don't persist intermediate pages yet
        if path.is_dir():
            if is_libby:
                pages = extract_screenshot_spread(path)
            else:
                pages = extract_screenshots(path, auto_number=is_ordered)
        else:
            pages = extract_auto(path)

    if not pages:
        logger.warning("No pages extracted from %s", path)
        return []

    # Stage 1b: Normalize ligatures
    for page in pages:
        page.raw_text = normalize_ligatures(page.raw_text)

    # Stage 2: Clean headers/footers
    repeated = detect_repeated_lines(pages)
    boilerplate = detect_boilerplate_lines(pages)
    pages = strip_headers_footers(pages, repeated | boilerplate)

    # Stage 3: Dedup and reorder (for unordered screenshots only)
    if path.is_dir() and not is_ordered:
        pages = deduplicate(pages, llm_client=llm_client)
        pages = detect_page_numbers(pages, llm_client)
        pages = reorder_pages(pages)
        gaps = find_page_gaps(pages)
        if gaps:
            logger.warning("Missing pages detected: %s", gaps)
    cache.mark_stage(path, "order")

    # Stage 4: Classify
    all_repeated = repeated | boilerplate
    blocks = classify_pages(pages, llm_client, repeated_lines=all_repeated)
    cache.mark_stage(path, "classify")

    # Stage 5: Detect chapters
    chapters = detect_chapters(blocks, llm_client)

    # Stage 6: Assemble
    assembled = []
    for chapter in chapters:
        chapter = link_footnotes(chapter)
        chapter = link_citations(chapter)
        chapter = merge_chapter_text(chapter)
        assembled.append(chapter)
    cache.mark_stage(path, "assemble")

    # Stage 7: Write output
    output_dir = Path(config.paths.output_dir)
    paths = write_chapters(assembled, output_dir, doc_name)
    cache.mark_stage(path, "output", output_path=str(paths[0].parent) if paths else None)

    return paths


def process_all(config: Config, force: bool = False) -> list[Path]:
    """Discover and process all files."""
    result = scan_directories(config.paths.local_pdf_dirs)
    all_outputs = []

    for pdf in result.pdfs:
        outputs = process_file(pdf, config, force)
        all_outputs.extend(outputs)

    for folder in result.screenshot_folders:
        outputs = process_file(folder, config, force)
        all_outputs.extend(outputs)

    return all_outputs
