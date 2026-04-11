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
