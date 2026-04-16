"""Metadata enrichment for academic paper documents.

Sources (applied in order, each only fills empty fields):
  PDF embedded → first-page font heuristics → PubMed eutils → Crossref
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from doc2md.models import Page
from doc2md.papers.models import PaperMetadata

logger = logging.getLogger(__name__)


def enrich_from_pdf_metadata(path: Path, meta: PaperMetadata) -> None:
    """Fill missing fields from PDF embedded metadata dict."""
    try:
        import fitz
        doc = fitz.open(str(path))
        pdf_meta = doc.metadata
        doc.close()
    except Exception as exc:
        logger.warning("Could not read PDF metadata from %s: %s", path, exc)
        return
    if not meta.title and pdf_meta.get("title", "").strip():
        meta.title = pdf_meta["title"].strip()
    if not meta.authors and pdf_meta.get("author", "").strip():
        meta.authors = [a.strip() for a in pdf_meta["author"].split(";") if a.strip()]


def enrich_from_pubmed(pmid: str, meta: PaperMetadata) -> None:
    """Fill missing fields from PubMed eutils efetch (XML)."""
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    try:
        resp = requests.get(
            url,
            params={"db": "pubmed", "id": pmid, "rettype": "abstract", "retmode": "xml"},
            timeout=20,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except Exception as exc:
        logger.warning("PubMed metadata fetch failed for PMID %s: %s", pmid, exc)
        return

    article = root.find(".//MedlineCitation/Article")
    if article is None:
        return

    if not meta.title:
        el = article.find("ArticleTitle")
        if el is not None and el.text:
            meta.title = el.text.strip()

    if not meta.authors:
        authors = []
        for author in article.findall(".//AuthorList/Author"):
            last = author.findtext("LastName", "")
            fore = author.findtext("ForeName", "")
            name = f"{fore} {last}".strip()
            if name:
                authors.append(name)
        if authors:
            meta.authors = authors

    if not meta.journal:
        el = article.find(".//Journal/Title")
        if el is not None and el.text:
            meta.journal = el.text.strip()

    if not meta.year:
        el = article.find(".//Journal/JournalIssue/PubDate/Year")
        if el is not None and el.text:
            try:
                meta.year = int(el.text)
            except ValueError:
                pass


def enrich_from_crossref(doi: str, meta: PaperMetadata) -> None:
    """Fill missing fields from Crossref REST API."""
    url = f"https://api.crossref.org/works/{doi}"
    try:
        resp = requests.get(url, params={"mailto": "doc2md"}, timeout=20)
        resp.raise_for_status()
        work = resp.json().get("message", {})
    except Exception as exc:
        logger.warning("Crossref metadata fetch failed for DOI %s: %s", doi, exc)
        return

    if not meta.title:
        titles = work.get("title", [])
        if titles:
            meta.title = titles[0].strip()

    if not meta.authors:
        authors = []
        for author in work.get("author", []):
            given = author.get("given", "")
            family = author.get("family", "")
            name = f"{given} {family}".strip()
            if name:
                authors.append(name)
        if authors:
            meta.authors = authors

    if not meta.journal:
        container = work.get("container-title", [])
        if container:
            meta.journal = container[0]

    if not meta.year:
        date_parts = work.get("issued", {}).get("date-parts", [[]])
        if date_parts and date_parts[0]:
            try:
                meta.year = int(date_parts[0][0])
            except (TypeError, ValueError):
                pass


def enrich_from_first_page(pages: list[Page], meta: PaperMetadata) -> None:
    """Heuristically parse title and authors from first-page block structure."""
    if not pages or not pages[0].block_dicts:
        return

    # Collect (max_font_size, text) for each text block on first page
    candidates: list[tuple[float, str]] = []
    for b in pages[0].block_dicts:
        if b.get("type") != 0:
            continue
        lines = b.get("lines", [])
        max_size = max(
            (span["size"] for line in lines for span in line.get("spans", []) if span.get("text", "").strip()),
            default=0.0,
        )
        text = " ".join(
            span["text"] for line in lines for span in line.get("spans", [])
        ).strip()
        if text and max_size > 0:
            candidates.append((max_size, text))

    if not candidates:
        return

    candidates.sort(key=lambda x: -x[0])

    if not meta.title:
        for _, text in candidates:
            if 5 < len(text) < 300 and "\n" not in text:
                meta.title = text
                break

    if not meta.authors and len(candidates) >= 2:
        for _, text in candidates[1:]:
            if "," in text and 10 < len(text) < 500:
                if sum(1 for c in text if c.isalpha()) > 5:
                    meta.authors = [a.strip() for a in text.split(",") if a.strip()]
                    break


def enrich_metadata(path: Path, pages: list[Page], meta: PaperMetadata) -> None:
    """Enrich metadata from all available sources.

    Order: PDF embedded → first-page heuristics → PubMed (if PMID) → Crossref (if DOI).
    Each source only fills fields not already populated.
    """
    enrich_from_pdf_metadata(path, meta)
    enrich_from_first_page(pages, meta)
    if meta.pmid:
        enrich_from_pubmed(meta.pmid, meta)
    if meta.doi:
        enrich_from_crossref(meta.doi, meta)
