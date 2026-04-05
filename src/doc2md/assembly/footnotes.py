"""Link footnote markers in body text to footnote definitions."""

from __future__ import annotations

import re

from doc2md.models import Chapter, TextBlock


def link_footnotes(chapter: Chapter) -> Chapter:
    """Extract footnote blocks and link markers in body text."""
    footnotes: dict[str, str] = {}
    body_blocks: list[TextBlock] = []
    last_footnote_id: str | None = None

    for block in chapter.blocks:
        if block.block_type == "footnote" and block.footnote_id:
            footnotes[block.footnote_id] = block.text
            last_footnote_id = block.footnote_id
        elif block.block_type == "footnote":
            if last_footnote_id:
                footnotes[last_footnote_id] += "\n" + block.text
            # else: orphan footnote with no prior ID — discard
        else:
            body_blocks.append(block)

    # Insert markdown footnote markers in body text
    linked_blocks = []
    for block in body_blocks:
        if block.block_type == "body":
            text = _insert_footnote_markers(block.text, footnotes)
            linked_blocks.append(TextBlock(
                text=text,
                block_type=block.block_type,
                page_index=block.page_index,
                heading_level=block.heading_level,
            ))
        else:
            linked_blocks.append(block)

    return Chapter(
        title=chapter.title,
        heading_level=chapter.heading_level,
        blocks=linked_blocks,
        footnotes={**chapter.footnotes, **footnotes},
        bibliography=chapter.bibliography,
    )


def _insert_footnote_markers(text: str, footnotes: dict[str, str]) -> str:
    """Replace bare footnote numbers with markdown [^N] syntax."""
    for fid in footnotes:
        # Match superscript-style markers like "word1" or "word 1"
        # but not numbers that are part of words
        pattern = rf"(?<=[a-zA-Z.,;:!?\"\'])(\s?)({re.escape(fid)})(?=[\s.,;:!?\"\']|$)"
        replacement = rf"\1[^{fid}]"
        text = re.sub(pattern, replacement, text)
    return text
