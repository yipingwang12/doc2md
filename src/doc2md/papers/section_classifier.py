"""Academic paper section classification.

Maps heading text to canonical section labels using a rule-based lookup
with normalisation. Non-matching headings leave the current section unchanged.
"""

from __future__ import annotations

import re

from doc2md.models import TextBlock

# Maps normalised heading patterns → canonical section label
CANONICAL_SECTIONS: dict[str, str] = {
    "abstract": "abstract",
    "summary": "abstract",
    "introduction": "introduction",
    "background": "introduction",
    "methods": "methods",
    "method": "methods",
    "materials and methods": "methods",
    "materials & methods": "methods",
    "experimental procedures": "methods",
    "experimental section": "methods",
    "star methods": "methods",
    "key resources table": "methods",
    "results": "results",
    "results and discussion": "results",
    "findings": "results",
    "discussion": "discussion",
    "conclusion": "discussion",
    "conclusions": "discussion",
    "concluding remarks": "discussion",
    "perspectives": "discussion",
    "references": "references",
    "bibliography": "references",
    "literature cited": "references",
    "works cited": "references",
    "supplemental information": "supplementary",
    "supplementary information": "supplementary",
    "supplementary materials": "supplementary",
    "supplemental materials": "supplementary",
    "supplementary data": "supplementary",
    "acknowledgments": "metadata",
    "acknowledgements": "metadata",
    "author contributions": "metadata",
    "funding": "metadata",
    "declaration of interests": "metadata",
    "conflict of interest": "metadata",
    "data availability": "metadata",
}

_NUMBER_PREFIX = re.compile(r"^\d+[\.\)]\s*")


def classify_section_heading(heading_text: str) -> str | None:
    """Map a heading string to a canonical section label, or None if unrecognised."""
    normalised = _NUMBER_PREFIX.sub("", heading_text.strip()).lower()
    return CANONICAL_SECTIONS.get(normalised)


def label_blocks_by_section(blocks: list[TextBlock]) -> list[tuple[TextBlock, str]]:
    """Annotate each block with its section label.

    Blocks before the first recognised heading receive the label "preamble".
    Blocks after an unrecognised heading retain the previous section label.
    Mutates each block's section_label field in-place and also returns it.
    """
    result: list[tuple[TextBlock, str]] = []
    current_label = "preamble"

    for block in blocks:
        if block.block_type == "heading":
            candidate = classify_section_heading(block.text)
            if candidate is not None:
                current_label = candidate
        block.section_label = current_label
        result.append((block, current_label))

    return result
