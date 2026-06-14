"""CLI entry point using click."""

from __future__ import annotations

from pathlib import Path

import click

from doc2md.config import load_config


@click.group()
@click.option("--config", "config_path", type=click.Path(exists=False), default="config.toml")
@click.pass_context
def main(ctx, config_path):
    """doc2md: Convert PDFs and screenshots to structured Markdown."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(Path(config_path))


@main.command()
@click.pass_context
def sync(ctx):
    """Sync screenshots from Google Drive via rclone."""
    config = ctx.obj["config"]
    from doc2md.ingest.rclone_sync import sync as rclone_sync
    local_dir = Path(config.paths.output_dir).parent / "synced"
    rclone_sync(config.paths.google_drive_remote, local_dir, config.rclone.flags)
    click.echo(f"Synced to {local_dir}")


@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--output-dir", type=click.Path(), default=None)
@click.option("--force", is_flag=True, help="Ignore cache, reprocess everything.")
@click.option("--model", default=None, help="Override LLM model.")
@click.pass_context
def process(ctx, path, output_dir, force, model):
    """Process a specific PDF or screenshot folder."""
    config = ctx.obj["config"]
    if output_dir:
        config.paths.output_dir = output_dir
    if model:
        config.llm.model = model
    click.echo(f"Processing: {path}")
    from doc2md.pipeline import process_file
    outputs = process_file(Path(path), config, force)
    for p in outputs:
        click.echo(f"  Written: {p}")


@main.command()
@click.option("--force", is_flag=True)
@click.pass_context
def run(ctx, force):
    """Full pipeline: sync + discover + process all."""
    config = ctx.obj["config"]
    from doc2md.pipeline import process_all
    outputs = process_all(config, force)
    click.echo(f"Processed {len(outputs)} chapters total.")
    for p in outputs:
        click.echo(f"  Written: {p}")


@main.command()
@click.pass_context
def status(ctx):
    """Show cache status."""
    from doc2md.cache import Cache
    config = ctx.obj["config"]
    cache = Cache(config.paths.cache_dir)
    entries = cache.status()
    if not entries:
        click.echo("No files processed yet.")
        return
    for path, stages in entries.items():
        click.echo(f"  {path}: {', '.join(stages)}")


@main.command()
@click.pass_context
def clean(ctx):
    """Clear cache for reprocessing."""
    from doc2md.cache import Cache
    config = ctx.obj["config"]
    cache = Cache(config.paths.cache_dir)
    cache.clear()
    click.echo("Cache cleared.")


@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--output-dir", type=click.Path(), default=None,
              help="Override output directory (default: same parent as input).")
@click.option("--artifacts", is_flag=True,
              help="Split at individual artifact/item level within PARTs.")
def split(path, output_dir, artifacts):
    """Split a single-file markdown book into per-chapter directories."""
    from doc2md.output.chapter_splitter import split_markdown
    md_path = Path(path)
    out = Path(output_dir) if output_dir else md_path.parent.parent
    paths = split_markdown(md_path, out, artifact_level=artifacts)
    if not paths:
        click.echo("No chapters detected.")
        return
    # Archive original directory to avoid duplication with split output
    source_dir = md_path.parent
    if source_dir.parent == out and source_dir.exists():
        archive = source_dir.with_name(source_dir.name + ".orig")
        if not archive.exists():
            source_dir.rename(archive)
            click.echo(f"Archived original: {source_dir.name} → {archive.name}")
    click.echo(f"Split into {len(paths)} chapters:")
    for p in paths:
        click.echo(f"  {p.parent.name}/{p.name}")


@main.command(name="link-index")
@click.argument("volume_dir", type=click.Path(exists=True))
def link_index_cmd(volume_dir):
    """Link index entries to chapter files in a volume's output directory."""
    from doc2md.assembly.index_linker import link_index
    result = link_index(Path(volume_dir))
    if result:
        click.echo(f"Index linked: {result}")
    else:
        click.echo("No index chapter found or no chapter directories available.")


@main.command()
@click.argument("term")
@click.option("--output-dir", type=click.Path(), default=None,
              help="Override results directory.")
@click.option("--context", "-c", default=0, type=int,
              help="Number of surrounding paragraphs to include.")
@click.pass_context
def search(ctx, term, output_dir, context):
    """Search for a term across all volumes' indexes."""
    from doc2md.assembly.search import search_all, format_results
    config = ctx.obj["config"]
    results_dir = Path(output_dir) if output_dir else Path(config.paths.output_dir)
    result = search_all(results_dir, term, context)
    click.echo(format_results(result))


# ---------------------------------------------------------------------------
# Papers sub-group
# ---------------------------------------------------------------------------

@click.group()
def papers():
    """Academic paper pipeline: PDF → Markdown + entity index."""


@papers.command(name="process")
@click.argument("path", type=click.Path(exists=True))
@click.option("--pmid", default=None, help="Override PMID for NER lookup.")
@click.option("--output-dir", type=click.Path(), default=None,
              help="Override papers output directory.")
@click.option("--force", is_flag=True, help="Reprocess even if already done.")
@click.pass_context
def papers_process(ctx, path, pmid, output_dir, force):
    """Process a single academic paper PDF."""
    from doc2md.papers.pipeline import process_paper
    config = ctx.obj["config"]
    if output_dir:
        config.papers.papers_dir = output_dir
    click.echo(f"Processing paper: {path}")
    paths = process_paper(Path(path), config, force=force, pmid=pmid)
    for p in paths:
        click.echo(f"  Written: {p}")
    if not paths:
        click.echo("  No output produced.")


@papers.command(name="build-index")
@click.option("--papers-dir", type=click.Path(exists=True), default=None,
              help="Directory containing processed papers (default: config.papers.papers_dir).")
@click.pass_context
def papers_build_index(ctx, papers_dir):
    """Rebuild entity index from all papers' entities.json files."""
    import json
    from dataclasses import asdict
    from doc2md.papers.index_builder import (
        build_entity_index, write_entity_index_json, write_entity_index_md,
    )
    from doc2md.papers.models import NamedEntity, PaperDocument
    config = ctx.obj["config"]
    base = Path(papers_dir) if papers_dir else Path(config.papers.papers_dir)

    paper_docs = []
    for entities_file in sorted(base.glob("*/entities.json")):
        source_name = entities_file.parent.name
        raw = json.loads(entities_file.read_text())
        entities = [NamedEntity(**e) for e in raw]
        paper_docs.append(PaperDocument(source_name=source_name, entities=entities))

    index = build_entity_index(paper_docs)
    write_entity_index_json(index, base / "entity_index.json")
    write_entity_index_md(index, base / "entity_index.md")
    click.echo(f"Indexed {len(index)} entities across {len(paper_docs)} papers.")
    click.echo(f"  Written: {base / 'entity_index.json'}")


@papers.command(name="search-entity")
@click.argument("entity_query")
@click.option("--index", "index_path", type=click.Path(), default=None,
              help="Path to entity_index.json.")
@click.option("--type", "entity_type", default=None,
              help="Filter by entity type (gene, disease, chemical, …).")
@click.pass_context
def papers_search_entity(ctx, entity_query, index_path, entity_type):
    """Search for an entity across all processed papers."""
    from doc2md.papers.index_builder import load_entity_index
    config = ctx.obj["config"]
    idx_path = Path(index_path) if index_path else Path(config.papers.papers_dir) / "entity_index.json"
    index = load_entity_index(idx_path)

    query = entity_query.lower()
    matches = [
        entry for entry in index.values()
        if query in entry.display_name.lower() or query in entry.entity_id.lower()
    ]
    if entity_type:
        matches = [e for e in matches if e.entity_type == entity_type]

    if not matches:
        click.echo(f"No entities found matching '{entity_query}'.")
        return

    for entry in sorted(matches, key=lambda e: e.display_name.lower()):
        click.echo(f"\n{entry.display_name} [{entry.entity_type}] ({entry.entity_id})")
        for occ in entry.occurrences:
            click.echo(f"  {occ.paper_source} / {occ.section}: {occ.context[:120]}")


main.add_command(papers)
