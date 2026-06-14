"""Regex-based extraction of experimental method entities.

Covers sequencing technologies, genomic perturbation tools, flow cytometry,
and common computational methods. Ordered specific-before-general so that
e.g. 'CRISPR-Cas9' matches before the plain 'CRISPR' fallback.
"""

from __future__ import annotations

import re

from doc2md.papers.models import NamedEntity

# (compiled_pattern, canonical_id)
# Patterns are tried in order; each match position is emitted once.
_VOCAB: list[tuple[re.Pattern, str]] = [
    p for p in [
        # Single-cell multimodal
        (re.compile(r"\bCITE-seq\b", re.IGNORECASE), "cite-seq"),
        (re.compile(r"\bREAP-seq\b", re.IGNORECASE), "reap-seq"),
        # Single-cell sequencing
        (re.compile(r"\bscRNA-seq\b", re.IGNORECASE), "scrna-seq"),
        (re.compile(r"\bscATAC-seq\b", re.IGNORECASE), "scatac-seq"),
        (re.compile(r"\bsnRNA-seq\b", re.IGNORECASE), "snrna-seq"),
        (re.compile(r"\bsnATAC-seq\b", re.IGNORECASE), "snatac-seq"),
        # Spatial transcriptomics
        (re.compile(r"\bSTARmap\b"), "starmap"),
        (re.compile(r"\bSlide-seq\b", re.IGNORECASE), "slide-seq"),
        (re.compile(r"\bVisium\b"), "visium"),
        (re.compile(r"\bseqFISH\b", re.IGNORECASE), "seqfish"),
        (re.compile(r"\bsmFISH\b", re.IGNORECASE), "smfish"),
        (re.compile(r"\bFISH\b"), "fish"),
        # Bulk sequencing
        (re.compile(r"\bChIP-seq\b", re.IGNORECASE), "chip-seq"),
        (re.compile(r"\bCUT&RUN\b", re.IGNORECASE), "cut-and-run"),
        (re.compile(r"\bCUT&TAG\b", re.IGNORECASE), "cut-and-tag"),
        (re.compile(r"\bATAC-seq\b", re.IGNORECASE), "atac-seq"),
        (re.compile(r"\bRNA-seq\b", re.IGNORECASE), "rna-seq"),
        # scRNA-seq platforms
        (re.compile(r"\b10x\s+Genomics\b", re.IGNORECASE), "10x-genomics"),
        (re.compile(r"\bDrop-seq\b", re.IGNORECASE), "drop-seq"),
        (re.compile(r"\bInDrop\b", re.IGNORECASE), "indrop"),
        # CRISPR (specific before general)
        (re.compile(r"\bCRISPR-Cas9\b", re.IGNORECASE), "crispr-cas9"),
        (re.compile(r"\bCRISPRi\b", re.IGNORECASE), "crispri"),
        (re.compile(r"\bCRISPRa\b", re.IGNORECASE), "crispra"),
        (re.compile(r"\bCRISPR\b"), "crispr"),
        # RNAi
        (re.compile(r"\bsiRNA\b"), "sirna"),
        (re.compile(r"\bshRNA\b"), "shrna"),
        (re.compile(r"\bRNAi\b"), "rnai"),
        # Flow cytometry
        (re.compile(r"\bFACS\b"), "facs"),
        (re.compile(r"\bflow\s+cytometry\b", re.IGNORECASE), "flow-cytometry"),
        # Computational methods
        (re.compile(r"\bUMAP\b"), "umap"),
        (re.compile(r"\bt-SNE\b", re.IGNORECASE), "t-sne"),
        (re.compile(r"\btSNE\b", re.IGNORECASE), "t-sne"),
        (re.compile(r"\bcanonical\s+correlation\s+analysis\b", re.IGNORECASE), "cca"),
        # PCA only in clearly analytical contexts (avoid false positives)
        (re.compile(r"\bprincipal\s+component\s+analysis\b", re.IGNORECASE), "pca"),
    ]
    # Filter keeps all — list comprehension is a no-op here, kept for easy extension
    if p
]

_SECTIONS_TO_ANNOTATE = frozenset({"abstract", "introduction", "methods", "results"})


def extract_method_entities(text: str, section_label: str = "") -> list[NamedEntity]:
    """Extract method-type entities from text using regex vocabulary.

    Only annotates sections relevant to methodology reporting.
    Each match position is emitted at most once (first matching pattern wins).
    """
    if section_label not in _SECTIONS_TO_ANNOTATE:
        return []

    entities: list[NamedEntity] = []
    claimed: set[tuple[int, int]] = set()  # (start, end) spans already matched

    for pattern, canonical in _VOCAB:
        for m in pattern.finditer(text):
            span = (m.start(), m.end())
            # Skip if this span overlaps an already-claimed match
            if any(s <= m.start() < e or s < m.end() <= e for s, e in claimed):
                continue
            claimed.add(span)
            entities.append(NamedEntity(
                text=m.group(),
                entity_type="method",
                entity_id=f"method:{canonical}",
                source="regex",
                section_label=section_label,
                start=m.start(),
                end=m.end(),
            ))

    entities.sort(key=lambda e: e.start)
    return entities
