"""Merge pages into chapters and resolve page breaks."""

from __future__ import annotations

from doc2md.assembly.cleaner import fix_hyphenation, join_broken_sentences
from doc2md.models import Chapter, TextBlock


def merge_chapter_text(chapter: Chapter) -> Chapter:
    """Merge consecutive body blocks, fixing page-break artifacts."""
    if not chapter.blocks:
        return chapter

    merged_blocks: list[TextBlock] = []

    for block in chapter.blocks:
        if block.block_type != "body":
            merged_blocks.append(block)
            continue

        if merged_blocks and merged_blocks[-1].block_type == "body":
            prev = merged_blocks[-1]
            joined = join_broken_sentences(prev.text, block.text)
            joined = fix_hyphenation(joined)
            merged_blocks[-1] = TextBlock(
                text=joined,
                block_type="body",
                page_index=prev.page_index,
            )
        else:
            text = fix_hyphenation(block.text)
            merged_blocks.append(TextBlock(
                text=text,
                block_type="body",
                page_index=block.page_index,
            ))

    return Chapter(
        title=chapter.title,
        heading_level=chapter.heading_level,
        blocks=merged_blocks,
        footnotes=chapter.footnotes,
        bibliography=chapter.bibliography,
    )
