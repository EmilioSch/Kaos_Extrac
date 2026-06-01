#!/usr/bin/env python3
"""
kaosextract.py — KaosExtract CLI
==================================
AI-powered knowledge extraction from books.

COMMANDS:
  ingest    — Add books/sources to the system (PDF → TXT)
  sources   — List available source files
  templates — List available templates
  estimate  — Estimate token cost without API calls
  run       — Run the full extraction pipeline
  batch     — Process multiple entities from a file
"""

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.rule import Rule
from rich.text import Text
from rich.columns import Columns
from rich import box

sys.path.insert(0, str(Path(__file__).parent))
console = Console()


# ── Shared UI helpers ──────────────────────────────────────────────────────────

def _print_logo():
    """Print compact header logo for subcommands."""
    console.print(
        "[bold cyan]▸ KAOS[/bold cyan][bold white]EXTRACT[/bold white]  "
        "[dim]AI knowledge extraction from books[/dim]"
    )
    console.print(Rule(style="dim blue"))
    console.print()


# ── ingest ─────────────────────────────────────────────────────────────────────

def cmd_ingest(args):
    from pipeline.ingest import ingest_file, ingest_directory

    _print_logo()
    source = Path(args.source)
    category = args.category or "books"

    console.print(Panel(
        f"[bold white]Source  :[/bold white]  {source}\n"
        f"[bold white]Category:[/bold white]  [cyan]{category}[/cyan]\n"
        f"[bold white]Force   :[/bold white]  {'Yes' if args.force else 'No'}",
        title="[bold cyan]📥  Ingest[/bold cyan]",
        border_style="cyan",
        padding=(0, 1),
    ))

    if source.is_dir():
        pattern = args.pattern or "*.pdf"
        console.print(f"  Scanning [bold]{source}[/bold] for [yellow]{pattern}[/yellow]...\n")
        results = ingest_directory(source, category=category, force=args.force, pattern=pattern)

        table = Table(box=box.ROUNDED, border_style="dim cyan", header_style="bold cyan", padding=(0,1))
        table.add_column("File", style="white")
        table.add_column("Saved as", style="green")
        table.add_column("Size", justify="right")
        for r in results:
            table.add_row(r["original_name"], r["saved_as"], f"{r['char_count']:,} chars")
        if results:
            console.print(table)
        console.print(f"\n  [green]✓[/green] {len(results)} file(s) ingested.")
    else:
        try:
            meta = ingest_file(source, category=category, force=args.force)
            console.print(Panel(
                f"[dim]Saved as :[/dim]  [bold green]{meta['saved_as']}[/bold green]\n"
                f"[dim]Size     :[/dim]  {meta['size_bytes']:,} bytes\n"
                f"[dim]Chars    :[/dim]  {meta['char_count']:,}\n"
                f"[dim]Converted:[/dim]  {meta['conversion']}\n"
                f"[dim]OCR fixed:[/dim]  {'Yes' if meta['ocr_repaired'] else 'No'}",
                title="[bold green]✓ Ingested[/bold green]",
                border_style="green",
                padding=(0, 1),
            ))
        except FileExistsError as e:
            console.print(f"[yellow]⚠ {e}[/yellow]")
            sys.exit(1)
        except Exception as e:
            console.print(f"[red]✗ Error: {e}[/red]")
            sys.exit(1)


# ── sources ────────────────────────────────────────────────────────────────────

def cmd_sources(args):
    from pipeline.ingest import list_sources

    _print_logo()
    console.print("  [bold cyan]Available Sources[/bold cyan]\n")
    sources = list_sources()

    if not sources:
        console.print(Panel(
            "[yellow]No source files found in upload/\n\n"
            "Add your books with:\n"
            "[bold]  python kaosextract.py ingest my_book.pdf[/bold][/yellow]",
            border_style="yellow",
            title="[yellow]⚠ Empty[/yellow]",
        ))
        return

    total_files = 0
    total_chars = 0

    for category, files in sources.items():
        table = Table(
            title=f"📁  {category.upper()}",
            box=box.ROUNDED,
            border_style="dim blue",
            header_style="bold cyan",
            padding=(0, 1),
            title_style="bold white",
        )
        table.add_column("Filename", style="white", min_width=30)
        table.add_column("Size (MB)", justify="right", style="yellow")
        table.add_column("Characters", justify="right", style="green")

        for f in files:
            bar = "█" * min(int(f["size_mb"] * 3), 15) + "░" * max(0, 15 - int(f["size_mb"] * 3))
            table.add_row(f["name"], f"{f['size_mb']:.1f}", f"{f['chars']:,}")
            total_files += 1
            total_chars += f["chars"]

        console.print(table)
        console.print()

    console.print(
        f"  [dim]Total:[/dim] [bold]{total_files}[/bold] files  "
        f"[dim]|[/dim]  [bold]{total_chars:,}[/bold] characters"
    )


# ── templates ──────────────────────────────────────────────────────────────────

def cmd_templates(args):
    from core.template_loader import list_templates, load_template

    _print_logo()
    console.print("  [bold cyan]Available Templates[/bold cyan]\n")
    template_names = list_templates()

    if not template_names:
        console.print("[yellow]No templates found in templates/[/yellow]")
        return

    for name in template_names:
        try:
            t = load_template(name)
            total_sections = sum(len(m.get("sections", [])) for m in t.modules)

            # Build modules summary
            mod_lines = ""
            for m in t.modules:
                complexity = m.get("complexity", "standard")
                icon = "⚡" if complexity == "complex" else "○"
                mod_lines += f"  {icon} Module {m['id']}: {m['name']} ({len(m.get('sections',[]))} sections)\n"

            console.print(Panel(
                f"[dim]Name    :[/dim]  [bold white]{t.name}[/bold white]  [dim]v{t.version}[/dim]\n"
                f"[dim]Language:[/dim]  {t.language} → {t.output_language}\n"
                f"[dim]Entity  :[/dim]  {t.entity_label}\n"
                f"[dim]Modules :[/dim]  {len(t.modules)} modules, {total_sections} sections total\n"
                f"\n{mod_lines.rstrip()}",
                title=f"[bold cyan]{name}[/bold cyan]",
                border_style="cyan",
                padding=(0, 2),
            ))
        except Exception as e:
            console.print(f"[red]✗ {name}: {e}[/red]")

    console.print(
        "\n  [dim]Add a template:[/dim] create [bold]templates/my_template.yaml[/bold]"
        " (see [bold]templates/custom_template.yaml[/bold] for the blank format)"
    )


# ── estimate ───────────────────────────────────────────────────────────────────

def cmd_estimate(args):
    from core.template_loader import load_template
    from core.file_loader import SourceLoader

    _print_logo()
    template = load_template(args.template)
    loader = SourceLoader(template=template)
    groups = loader.get_source_groups()
    entity = args.entity

    console.print(Panel(
        f"[dim]Entity  :[/dim]  [bold yellow]{entity}[/bold yellow]\n"
        f"[dim]Template:[/dim]  [cyan]{template.name}[/cyan]",
        title="[bold cyan]💰  Cost Estimate[/bold cyan]",
        border_style="cyan",
        padding=(0, 1),
    ))
    console.print()

    table = Table(
        box=box.ROUNDED,
        border_style="dim blue",
        header_style="bold cyan",
        padding=(0, 1),
    )
    table.add_column("Source", style="white", min_width=35)
    table.add_column("Size", justify="right", style="yellow")
    table.add_column("Mentions", justify="right")
    table.add_column("Strategy", style="dim")

    total_chars = 0
    for group_name, files in groups.items():
        for f in files:
            if not f.exists():
                continue
            size_mb = f.stat().st_size / 1_000_000
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                aliases = [entity.lower()] + template.get_aliases_for_entity(entity)
                mentions = sum(text.lower().count(a) for a in aliases)
                is_large = f.stat().st_size > 2_000_000
                strategy = "[cyan]Dense Window[/cyan]" if is_large else f"Window ×{mentions}"
                chars = min(len(text), 360_000 if is_large else 120_000)
                if mentions > 0:
                    total_chars += chars
                mention_str = f"[green]{mentions:,}[/green]" if mentions > 0 else "[dim]—[/dim]"
                table.add_row(f.name[:45], f"{size_mb:.1f} MB", mention_str, strategy)
            except Exception:
                table.add_row(f.name[:45], f"{size_mb:.1f} MB", "[red]ERROR[/red]", "—")

    if groups:
        console.print(table)
    else:
        console.print("  [yellow]No sources found. Add books with: python kaosextract.py ingest[/yellow]")
        return

    # Token + cost estimates
    est_tokens_in = int(total_chars * 0.25)
    modules_count = len(template.modules)
    total_sections = sum(len(m.get("sections", [])) for m in template.modules)
    est_tokens_out = total_sections * 900

    total_tokens = est_tokens_in + est_tokens_out
    cost_minimax = total_tokens / 1_000_000 * 0.30
    cost_deepseek = total_tokens / 1_000_000 * 0.14

    console.print()
    summary = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    summary.add_column("Label", style="dim", min_width=28)
    summary.add_column("Value", style="bold white")
    summary.add_row("Characters to process:", f"{total_chars:,}")
    summary.add_row("Input tokens (est.):", f"{est_tokens_in:,}")
    summary.add_row(f"Output tokens ({modules_count} mod × {total_sections//max(modules_count,1)} sec):", f"{est_tokens_out:,}")
    summary.add_row("TOTAL TOKENS (est.):", f"[bold cyan]{total_tokens:,}[/bold cyan]")
    summary.add_row("", "")
    summary.add_row("Cost (MiniMax M2.7):", f"[yellow]${cost_minimax:.4f} USD[/yellow]")
    summary.add_row("Cost (DeepSeek):", f"[yellow]${cost_deepseek:.4f} USD[/yellow]")
    console.print(summary)


# ── run ────────────────────────────────────────────────────────────────────────

def cmd_run(args):
    from core.template_loader import load_template
    import main as pipeline_main

    try:
        template = load_template(args.template)
    except FileNotFoundError as e:
        console.print(f"[red]✗ {e}[/red]")
        sys.exit(1)

    pipeline_main.run_for_entity(
        entity_name=args.entity,
        template=template,
        output_dir=Path(args.output) if args.output else None,
        force_refresh=args.force_refresh,
    )


# ── batch ──────────────────────────────────────────────────────────────────────

def cmd_batch(args):
    from core.template_loader import load_template
    import main as pipeline_main

    entities_file = Path(args.entities)
    if not entities_file.exists():
        console.print(f"[red]✗ File not found: {entities_file}[/red]")
        sys.exit(1)

    entities = [
        line.strip()
        for line in entities_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]

    if not entities:
        console.print(f"[red]✗ No entities found in {entities_file}[/red]")
        sys.exit(1)

    try:
        template = load_template(args.template)
    except FileNotFoundError as e:
        console.print(f"[red]✗ {e}[/red]")
        sys.exit(1)

    _print_logo()

    # Summary panel
    entity_list = "\n".join(f"  [dim]{i:2d}.[/dim] {e}" for i, e in enumerate(entities, 1))
    console.print(Panel(
        f"[dim]Template:[/dim]  [cyan]{template.name}[/cyan]\n"
        f"[dim]Entities:[/dim]  {len(entities)}\n\n"
        f"{entity_list}",
        title="[bold cyan]🔄  Batch Processing[/bold cyan]",
        border_style="cyan",
        padding=(0, 2),
    ))
    console.print()

    success, failed = 0, 0
    for i, entity in enumerate(entities, 1):
        console.print(Rule(
            f"[bold blue] [{i}/{len(entities)}] {entity} [/bold blue]",
            style="blue dim",
        ))
        try:
            pipeline_main.run_for_entity(
                entity_name=entity,
                template=template,
                output_dir=Path(args.output) if args.output else None,
            )
            success += 1
        except Exception as e:
            console.print(f"[red]✗ Failed: {e}[/red]")
            failed += 1
            if not args.continue_on_error:
                console.print("[yellow]Stopping batch. Use --continue-on-error to skip failures.[/yellow]")
                break

    console.print()
    console.print(Panel(
        f"[green]✓ Completed:[/green] {success}\n"
        f"{'[red]' if failed else '[dim]'}✗ Failed:    {failed}{'[/red]' if failed else '[/dim]'}",
        title="[bold]Batch Summary[/bold]",
        border_style="green" if not failed else "yellow",
        padding=(0, 2),
    ))


# ── Parser ─────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kaosextract",
        description="KaosExtract — AI-powered knowledge extraction from books",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python kaosextract.py ingest my_textbook.pdf
  python kaosextract.py ingest ./library/ --pattern "*.pdf" --category books
  python kaosextract.py sources list
  python kaosextract.py templates list
  python kaosextract.py estimate --entity "Streptococcus pyogenes"
  python kaosextract.py run --entity "Streptococcus pyogenes"
  python kaosextract.py run --entity "HIV" --template medical_microbiology
  python kaosextract.py batch --entities my_list.txt
        """,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ingest
    p = sub.add_parser("ingest", help="Add books/sources to the system")
    p.add_argument("source", help="Path to a PDF/TXT file or directory")
    p.add_argument("--category", "-c",
                   choices=["books", "notes", "lectures", "articles", "exams", "other"],
                   default="books", help="Source category (default: books)")
    p.add_argument("--pattern", "-p", default="*.pdf",
                   help="Glob pattern for directory ingestion (default: *.pdf)")
    p.add_argument("--force", "-f", action="store_true", help="Overwrite existing files")
    p.set_defaults(func=cmd_ingest)

    # sources
    p = sub.add_parser("sources", help="List available sources")
    p.add_argument("action", choices=["list"], default="list", nargs="?")
    p.set_defaults(func=cmd_sources)

    # templates
    p = sub.add_parser("templates", help="List available templates")
    p.add_argument("action", choices=["list"], default="list", nargs="?")
    p.set_defaults(func=cmd_templates)

    # estimate
    p = sub.add_parser("estimate", help="Estimate token cost without API calls")
    p.add_argument("--entity", "-e", required=True, help="Entity to extract")
    p.add_argument("--template", "-t", default=None, help="Template name")
    p.set_defaults(func=cmd_estimate)

    # run
    p = sub.add_parser("run", help="Run the full extraction pipeline")
    p.add_argument("--entity", "-e", required=True, help="Entity to extract")
    p.add_argument("--template", "-t", default=None, help="Template name")
    p.add_argument("--output", "-o", default=None, help="Output directory")
    p.add_argument("--force-refresh", action="store_true", help="Ignore cache and re-process")
    p.set_defaults(func=cmd_run)

    # batch
    p = sub.add_parser("batch", help="Process multiple entities from a text file")
    p.add_argument("--entities", required=True, help="File with one entity per line")
    p.add_argument("--template", "-t", default=None, help="Template name")
    p.add_argument("--output", "-o", default=None, help="Output directory")
    p.add_argument("--continue-on-error", action="store_true",
                   help="Continue batch even if an entity fails")
    p.set_defaults(func=cmd_batch)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
