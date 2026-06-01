"""
main.py — KaosExtract Pipeline Orchestrator
============================================
Orchestrates the full extraction pipeline for a given entity and template.
Called by kaosextract.py CLI via run_for_entity().

FLOW:
  Phase 1 → Extract relevant text from each source group (parallel)
  Phase 2 → Consolidate all extractions into a master document
  Phase 3 → Generate analysis modules in parallel (parallel sections → synthesis → QC)
  Output  → Save structured report as Markdown (+ PDF if weasyprint available)
"""

import asyncio
import time
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    Progress, SpinnerColumn, TextColumn,
    BarColumn, TimeElapsedColumn, TaskProgressColumn,
)
from rich.table import Table
from rich.text import Text
from rich import box
from rich.columns import Columns
from rich.rule import Rule

import config
from core.api_client import APIClient
from core.file_loader import SourceLoader
from core.logger import get_logger
from core.template_loader import Template
from pipeline.phase1_extraction import run_phase1
from pipeline.phase2_consolidation import run_phase2
from pipeline.phase3_analysis import run_phase3

log = get_logger(__name__)
console = Console()

# ── Terminal UI helpers ───────────────────────────────────────────────────────

def print_banner():
    """Print the KaosExtract ASCII banner."""
    console.print()
    console.print(
        "[bold cyan]"
        "  ██╗  ██╗ █████╗  ██████╗ ███████╗\n"
        "  ██║ ██╔╝██╔══██╗██╔═══██╗██╔════╝\n"
        "  █████╔╝ ███████║██║   ██║███████╗\n"
        "  ██╔═██╗ ██╔══██║██║   ██║╚════██║\n"
        "  ██║  ██╗██║  ██║╚██████╔╝███████║\n"
        "  ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝[/bold cyan]"
        "  [dim cyan]EXTRACT[/dim cyan]"
    )
    console.print(
        "  [dim]AI-powered knowledge extraction from books[/dim]",
        justify="left"
    )
    console.print()


def print_phase_header(phase_num: int, title: str, subtitle: str = ""):
    """Print a phase header with decorative rule."""
    console.print()
    console.print(Rule(
        f"[bold blue] Phase {phase_num} — {title} [/bold blue]",
        style="blue dim",
        align="left",
    ))
    if subtitle:
        console.print(f"  [dim]{subtitle}[/dim]")
    console.print()


def print_source_table(groups: dict, entity_name: str) -> int:
    """Print a table of source groups and their file counts."""
    table = Table(
        box=box.ROUNDED,
        border_style="dim blue",
        show_header=True,
        header_style="bold cyan",
        padding=(0, 1),
    )
    table.add_column("Source Group", style="white", min_width=20)
    table.add_column("Files", justify="right", style="yellow")
    table.add_column("Status", justify="center")

    total_files = 0
    for group, files in groups.items():
        if files:
            table.add_row(group, str(len(files)), "[green]●[/green] Ready")
            total_files += len(files)

    if total_files == 0:
        console.print(
            Panel(
                "[yellow]No source files found in upload/\n\n"
                "Add your books first:\n"
                "[bold]  python kaosextract.py ingest my_book.pdf[/bold][/yellow]",
                border_style="yellow",
                title="[yellow]⚠ No sources[/yellow]",
            )
        )
        return 0

    console.print(f"  [dim]Entity:[/dim] [bold white]{entity_name}[/bold white]")
    console.print(f"  [dim]Sources:[/dim]")
    console.print(table)
    return total_files


def print_extraction_results(extractions: dict):
    """Print extraction results per source group."""
    table = Table(
        box=box.SIMPLE,
        show_header=False,
        padding=(0, 2),
    )
    table.add_column("Icon", width=2)
    table.add_column("Source", style="white")
    table.add_column("Result", style="dim")

    for group, text in extractions.items():
        if "FUENTE_SIN_INFORMACIÓN_RELEVANTE" in text or not text.strip():
            table.add_row("○", group, "[dim]No relevant data[/dim]")
        else:
            char_count = len(text)
            table.add_row(
                "[green]●[/green]",
                group,
                f"[green]{char_count:,} chars[/green]"
            )

    console.print(table)


def print_module_status(module_results: dict, modules: list[dict]):
    """Print a summary table of generated modules."""
    console.print()
    table = Table(
        box=box.ROUNDED,
        border_style="dim cyan",
        header_style="bold cyan",
        padding=(0, 1),
    )
    table.add_column("Module", style="white", min_width=24)
    table.add_column("Sections", justify="center", style="yellow")
    table.add_column("Characters", justify="right", style="green")
    table.add_column("Status", justify="center")

    for mod in modules:
        mod_id = mod["id"]
        content = module_results.get(mod_id, "")
        sections = len(mod.get("sections", []))
        chars = len(content) if content else 0
        status = "[green]✓ Done[/green]" if content else "[red]✗ Failed[/red]"
        table.add_row(mod["name"], str(sections), f"{chars:,}", status)

    console.print(table)


def print_final_summary(
    entity_name: str,
    elapsed: float,
    total_requests: int,
    extractions: dict,
    module_results: dict,
    md_file: Optional[Path],
    pdf_file: Optional[Path],
):
    """Print the final results panel."""
    valid_sources = sum(
        1 for v in extractions.values()
        if "FUENTE_SIN_INFORMACIÓN_RELEVANTE" not in v and v.strip()
    )
    total_sources = len(extractions)
    valid_modules = sum(1 for v in module_results.values() if v)

    content = Text()
    content.append("Entity:   ", style="dim")
    content.append(f"{entity_name}\n", style="bold yellow")
    content.append("Sources:  ", style="dim")
    content.append(f"{valid_sources}/{total_sources} with relevant data\n", style="white")
    content.append("Modules:  ", style="dim")
    content.append(f"{valid_modules} generated\n", style="white")
    content.append("Time:     ", style="dim")
    content.append(f"{elapsed:.1f}s\n", style="white")
    content.append("API calls:", style="dim")
    content.append(f" {total_requests}\n", style="white")

    if md_file:
        content.append("\n")
        content.append("Markdown: ", style="dim")
        content.append(str(md_file), style="bold green")
        content.append("\n")
    if pdf_file:
        content.append("PDF:      ", style="dim")
        content.append(str(pdf_file), style="bold green")

    console.print()
    console.print(Panel(
        content,
        title="[bold green]✓ Extraction Complete[/bold green]",
        border_style="green",
        padding=(1, 2),
    ))


# ── Pipeline orchestrator ────────────────────────────────────────────────────

async def _run_pipeline(
    entity_name: str,
    template: Template,
    output_dir: Optional[Path] = None,
    force_refresh: bool = False,
):
    """Internal async pipeline runner."""
    start_time = time.monotonic()
    api_client = APIClient()

    # ── Phase 0: Validate sources ────────────────────────────────────────────
    loader = SourceLoader(template=template)
    source_groups = loader.get_source_groups()

    total_files = print_source_table(source_groups, entity_name)
    if total_files == 0:
        return

    # ── Phase 1: Parallel extraction ─────────────────────────────────────────
    print_phase_header(1, "Source Extraction", "Scanning all source groups in parallel...")

    with Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[bold white]{task.description}"),
        BarColumn(bar_width=30, style="cyan", complete_style="green"),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("Extracting from sources...", total=None)
        extractions = await run_phase1(entity_name, api_client)
        progress.update(task, completed=1, total=1, description="Extraction complete")

    print_extraction_results(extractions)

    valid_count = sum(
        1 for v in extractions.values()
        if "FUENTE_SIN_INFORMACIÓN_RELEVANTE" not in v and v.strip()
    )
    console.print(
        f"\n  [green]●[/green] {valid_count}/{len(extractions)} sources with relevant data"
    )

    # ── Phase 2: Consolidation ───────────────────────────────────────────────
    print_phase_header(2, "Consolidation", "Merging all source extractions into master document...")

    with Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[bold white]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("Building master document...", total=None)
        master_text = await run_phase2(entity_name, extractions, api_client)
        progress.update(task, completed=1, total=1, description="Master document ready")

    console.print(f"  [green]●[/green] Master document: [bold]{len(master_text):,} characters[/bold]")

    # ── Phase 3: Module generation ───────────────────────────────────────────
    module_entries = template.get_module_entries()
    total_sections = sum(len(m.get("sections", [])) for m in template.modules)

    print_phase_header(
        3,
        "Analysis Modules",
        f"Generating {len(module_entries)} modules × parallel sections → synthesis → offline QC"
    )

    with Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[bold white]{task.description}"),
        BarColumn(bar_width=30, style="cyan", complete_style="green"),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task(
            f"Generating modules (0/{len(module_entries)})...",
            total=len(module_entries),
        )
        module_results = await run_phase3(
            entity_name,
            master_text,
            api_client,
            progress_callback=lambda n: progress.update(
                task,
                advance=1,
                description=f"Generating modules ({n}/{len(module_entries)})...",
            ),
        )
        progress.update(task, description="All modules complete")

    print_module_status(module_results, template.modules)

    # ── Output ───────────────────────────────────────────────────────────────
    print_phase_header(4, "Output", "Saving report files...")

    out_dir = output_dir or config.REPORTS_MD_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _sanitize_filename(entity_name)
    md_file = out_dir / f"{safe_name}_report.md"

    # Build markdown report
    report_lines = [
        f"# {entity_name} — Analysis Report",
        f"\n*Generated by KaosExtract | Template: {template.name}*\n",
        "---\n",
    ]
    for mod in template.modules:
        mod_id = mod["id"]
        content = module_results.get(mod_id, "")
        if content:
            report_lines.append(f"\n## Module {mod_id}: {mod['name']}\n")
            report_lines.append(content)
            report_lines.append("\n")

    md_file.write_text("\n".join(report_lines), encoding="utf-8")
    console.print(f"  [green]●[/green] Markdown: [bold]{md_file}[/bold]")

    # Try PDF generation
    pdf_file = None
    try:
        import weasyprint
        pdf_out = config.REPORTS_PDF_DIR
        pdf_out.mkdir(parents=True, exist_ok=True)
        pdf_file = pdf_out / f"{safe_name}_report.pdf"
        # Basic HTML wrapping
        import markdown as md_lib
        html = f"<html><body>{md_lib.markdown(md_file.read_text())}</body></html>"
        weasyprint.HTML(string=html).write_pdf(str(pdf_file))
        console.print(f"  [green]●[/green] PDF:      [bold]{pdf_file}[/bold]")
    except ImportError:
        console.print("  [dim]○ PDF generation skipped (install weasyprint + markdown)[/dim]")
    except Exception as e:
        console.print(f"  [yellow]⚠ PDF error: {e}[/yellow]")

    # ── Final summary ────────────────────────────────────────────────────────
    elapsed = time.monotonic() - start_time
    print_final_summary(
        entity_name=entity_name,
        elapsed=elapsed,
        total_requests=getattr(api_client, 'total_requests', 0),
        extractions=extractions,
        module_results=module_results,
        md_file=md_file,
        pdf_file=pdf_file,
    )


def run_for_entity(
    entity_name: str,
    template: Template,
    output_dir: Optional[Path] = None,
    force_refresh: bool = False,
):
    """
    Public entry point called by the CLI.
    Runs the full extraction pipeline for a single entity.
    """
    print_banner()

    console.print(Panel(
        f"[bold white]Entity  :[/bold white]  [yellow]{entity_name}[/yellow]\n"
        f"[bold white]Template:[/bold white]  [cyan]{template.name} v{template.version}[/cyan]\n"
        f"[bold white]Modules :[/bold white]  {len(template.modules)} modules, "
        f"{sum(len(m.get('sections',[])) for m in template.modules)} sections",
        title="[bold cyan]KaosExtract — Extraction Pipeline[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    ))

    try:
        asyncio.run(_run_pipeline(entity_name, template, output_dir, force_refresh))
    except KeyboardInterrupt:
        console.print("\n[yellow]Pipeline interrupted by user.[/yellow]")
    except Exception as e:
        log.exception(f"Pipeline error: {e}")
        console.print(f"\n[red]✗ Pipeline error: {e}[/red]")
        raise


def _sanitize_filename(name: str) -> str:
    import re
    return re.sub(r'[^\w\-.]', '_', name).strip('_')
