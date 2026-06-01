#!/usr/bin/env python3
"""
kaosextract.py — CLI Principal de KaosExtract
==============================================
Motor de extracción de conocimiento desde libros con IA.

COMANDOS:
  ingest    — Agrega libros/fuentes al sistema (PDF → TXT)
  sources   — Lista las fuentes disponibles
  templates — Lista los templates disponibles
  estimate  — Estima el costo en tokens sin hacer llamadas a la API
  run       — Ejecuta el pipeline de extracción completo
  batch     — Procesa múltiples entidades desde un archivo

USO:
  python kaosextract.py ingest mi_libro.pdf [--category books]
  python kaosextract.py sources list
  python kaosextract.py templates list
  python kaosextract.py estimate --entity "Streptococcus pyogenes" [--template medical_microbiology]
  python kaosextract.py run --entity "Streptococcus pyogenes" [--template medical_microbiology]
  python kaosextract.py batch --entities entities.txt [--template medical_microbiology]
"""

import argparse
import sys
import json
from pathlib import Path

# ── Bootstrap ────────────────────────────────────────────────────────────────
# Asegurar que el directorio raíz esté en el path
sys.path.insert(0, str(Path(__file__).parent))


def cmd_ingest(args):
    """Subcomando: ingest — convierte y registra libros en el sistema."""
    from pipeline.ingest import ingest_file, ingest_directory

    source = Path(args.source)
    category = args.category or "books"
    force = args.force

    print(f"\n📥 KaosExtract — Ingestión de fuentes")
    print(f"   Fuente  : {source}")
    print(f"   Categoría: {category}")
    print()

    if source.is_dir():
        pattern = args.pattern or "*.pdf"
        results = ingest_directory(source, category=category, force=force, pattern=pattern)
        print(f"\n✅ {len(results)} archivo(s) ingestado(s).")
    else:
        try:
            meta = ingest_file(source, category=category, force=force)
            print(f"✅ Archivo ingestado exitosamente:")
            print(f"   Guardado en : {meta['saved_as']}")
            print(f"   Tamaño      : {meta['size_bytes']:,} bytes")
            print(f"   Caracteres  : {meta['char_count']:,}")
            print(f"   Conversión  : {meta['conversion']}")
            print(f"   OCR reparado: {meta['ocr_repaired']}")
        except FileExistsError as e:
            print(f"⚠️  {e}")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Error: {e}")
            sys.exit(1)


def cmd_sources(args):
    """Subcomando: sources list — muestra las fuentes disponibles."""
    from pipeline.ingest import list_sources

    print(f"\n📚 KaosExtract — Fuentes disponibles\n")
    sources = list_sources()

    if not sources:
        print("  No hay fuentes disponibles.")
        print("  Agrega libros con: python kaosextract.py ingest mi_libro.pdf")
        return

    total_files = 0
    total_chars = 0
    for category, files in sources.items():
        print(f"  📁 {category.upper()} ({len(files)} archivo(s)):")
        for f in files:
            bar = "█" * min(int(f["size_mb"] * 2), 20)
            print(f"     {f['name']:<45} {f['size_mb']:>5.1f} MB  {bar}")
        total_files += len(files)
        total_chars += sum(f["chars"] for f in files)
        print()

    print(f"  TOTAL: {total_files} archivo(s), {total_chars:,} caracteres")


def cmd_templates(args):
    """Subcomando: templates list — muestra los templates disponibles."""
    from core.template_loader import list_templates, load_template

    print(f"\n🗂️  KaosExtract — Templates disponibles\n")
    templates = list_templates()

    if not templates:
        print("  No hay templates disponibles.")
        return

    for name in templates:
        try:
            t = load_template(name)
            print(f"  ✓ {name}")
            print(f"    Nombre    : {t.name} v{t.version}")
            print(f"    Idioma    : {t.language} → {t.output_language}")
            print(f"    Entidad   : {t.entity_label}")
            print(f"    Módulos   : {len(t.modules)}")
            total_sections = sum(len(m.get("sections", [])) for m in t.modules)
            print(f"    Secciones : {total_sections} total")
            print()
        except Exception as e:
            print(f"  ✗ {name}: Error al cargar — {e}\n")

    print(f"  Agregar template: crear templates/mi_template.yaml")
    print(f"  Plantilla base  : templates/custom_template.yaml")


def cmd_estimate(args):
    """Subcomando: estimate — estima tokens y costo sin llamar a la API."""
    from core.template_loader import load_template
    from core.file_loader import SourceLoader

    entity = args.entity
    template_name = args.template
    template = load_template(template_name)
    loader = SourceLoader(template=template)
    groups = loader.get_source_groups()

    print(f"\n📊 KaosExtract — Estimación de extracción")
    print(f"   Entidad  : {entity}")
    print(f"   Template : {template.name}")
    print()

    total_chars = 0
    print(f"  {'Fuente':<45} {'Tamaño':>8}  {'Menciones':>10}  {'Estrategia'}")
    print(f"  {'-'*80}")

    for group_name, files in groups.items():
        for f in files:
            if not f.exists():
                continue
            size_mb = f.stat().st_size / 1_000_000
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                entity_lower = entity.lower()
                aliases = [entity_lower] + template.get_aliases_for_entity(entity)
                mentions = sum(text.lower().count(a) for a in aliases)
                strategy = "Dense Window" if f.stat().st_size > 2_000_000 else f"Window ×{mentions}"
                chars_to_extract = min(len(text), 360_000 if f.stat().st_size > 2_000_000 else 120_000)
                total_chars += chars_to_extract if mentions > 0 else 0
                mention_str = f"{mentions:,}" if mentions > 0 else "—"
                print(f"  {f.name:<45} {size_mb:>6.1f} MB  {mention_str:>10}  {strategy}")
            except Exception:
                print(f"  {f.name:<45} {size_mb:>6.1f} MB  {'ERROR':>10}")

    print(f"  {'-'*80}")

    # Estimación de tokens (1 char ≈ 0.25 tokens para español)
    est_tokens_in = int(total_chars * 0.25)
    modules_count = len(template.modules)
    total_sections = sum(len(m.get("sections", [])) for m in template.modules)
    est_tokens_out = total_sections * 800  # ~800 tokens output/sección

    print(f"\n  Caracteres a procesar  : {total_chars:>12,}")
    print(f"  Tokens de entrada est. : {est_tokens_in:>12,}")
    print(f"  Módulos × Secciones    : {modules_count} × {total_sections // modules_count} = {total_sections}")
    print(f"  Tokens de salida est.  : {est_tokens_out:>12,}")
    print(f"  TOKENS TOTALES EST.    : {est_tokens_in + est_tokens_out:>12,}")

    # Estimación de costo (precios aproximados MiniMax-M2.7 y DeepSeek)
    cost_minimax = (est_tokens_in + est_tokens_out) / 1_000_000 * 0.30  # $0.30/MTok
    cost_deepseek = (est_tokens_in + est_tokens_out) / 1_000_000 * 0.14  # $0.14/MTok
    print(f"\n  Costo estimado (MiniMax M2.7)  : ${cost_minimax:.4f} USD")
    print(f"  Costo estimado (DeepSeek)       : ${cost_deepseek:.4f} USD")
    print()


def cmd_run(args):
    """Subcomando: run — ejecuta el pipeline completo para una entidad."""
    print(f"\n🚀 KaosExtract — Extracción de conocimiento")
    print(f"   Entidad  : {args.entity}")
    print(f"   Template : {args.template or 'medical_microbiology (default)'}")
    print()

    # Importar el pipeline principal
    try:
        from core.template_loader import load_template
        template = load_template(args.template)
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)

    # Delegar al main.py existente con los parámetros correctos
    print(f"  Iniciando pipeline para '{args.entity}'...")
    print(f"  Template cargado: {template.name} ({len(template.modules)} módulos)\n")

    # El pipeline completo se llama desde main.py
    # En la versión actual, main.py es el entry point del pipeline completo
    # Esta integración se completará en la Fase de refactoring de main.py
    import main as pipeline_main
    # Pasar parámetros via atributos para compatibilidad con el pipeline existente
    pipeline_main.run_for_entity(
        entity_name=args.entity,
        template=template,
        output_dir=Path(args.output) if args.output else None,
    )


def cmd_batch(args):
    """Subcomando: batch — procesa múltiples entidades desde un archivo de texto."""
    entities_file = Path(args.entities)
    if not entities_file.exists():
        print(f"❌ Entities file not found: {entities_file}")
        sys.exit(1)

    entities = [
        line.strip()
        for line in entities_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]

    if not entities:
        print(f"❌ No entities found in {entities_file}")
        sys.exit(1)

    print(f"\n🔄 KaosExtract — Batch processing")
    print(f"   Template : {args.template or 'medical_microbiology (default)'}")
    print(f"   Entidades: {len(entities)}")
    for i, e in enumerate(entities, 1):
        print(f"   {i:2d}. {e}")
    print()

    for i, entity in enumerate(entities, 1):
        print(f"\n{'='*60}")
        print(f"[{i}/{len(entities)}] Procesando: {entity}")
        print(f"{'='*60}")
        args.entity = entity
        try:
            cmd_run(args)
        except Exception as e:
            print(f"❌ Error procesando '{entity}': {e}")
            if not args.continue_on_error:
                sys.exit(1)


# ── Parser principal ─────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kaosextract",
        description="KaosExtract — AI-powered knowledge extraction from books",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python kaosextract.py ingest my_textbook.pdf
  python kaosextract.py ingest ./library/ --category books --pattern "*.pdf"
  python kaosextract.py sources list
  python kaosextract.py templates list
  python kaosextract.py estimate --entity "Streptococcus pyogenes"
  python kaosextract.py run --entity "Streptococcus pyogenes"
  python kaosextract.py run --entity "HIV" --template medical_microbiology
  python kaosextract.py batch --entities my_entities.txt
        """,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── ingest ────────────────────────────────────────────────────────────────
    p_ingest = subparsers.add_parser("ingest", help="Add books/sources to the system")
    p_ingest.add_argument("source", help="Path to a PDF/TXT file or directory")
    p_ingest.add_argument(
        "--category", "-c",
        choices=["books", "notes", "lectures", "articles", "exams", "other"],
        default="books",
        help="Source category (default: books)"
    )
    p_ingest.add_argument(
        "--pattern", "-p",
        default="*.pdf",
        help="Glob pattern for directory ingestion (default: *.pdf)"
    )
    p_ingest.add_argument(
        "--force", "-f",
        action="store_true",
        help="Overwrite existing files"
    )
    p_ingest.set_defaults(func=cmd_ingest)

    # ── sources ───────────────────────────────────────────────────────────────
    p_sources = subparsers.add_parser("sources", help="List available sources")
    p_sources.add_argument("action", choices=["list"], default="list", nargs="?")
    p_sources.set_defaults(func=cmd_sources)

    # ── templates ─────────────────────────────────────────────────────────────
    p_templates = subparsers.add_parser("templates", help="List available templates")
    p_templates.add_argument("action", choices=["list"], default="list", nargs="?")
    p_templates.set_defaults(func=cmd_templates)

    # ── estimate ──────────────────────────────────────────────────────────────
    p_estimate = subparsers.add_parser(
        "estimate", help="Estimate token cost without making API calls"
    )
    p_estimate.add_argument("--entity", "-e", required=True, help="Entity to extract")
    p_estimate.add_argument(
        "--template", "-t",
        default=None,
        help="Template name (default: from config.py)"
    )
    p_estimate.set_defaults(func=cmd_estimate)

    # ── run ───────────────────────────────────────────────────────────────────
    p_run = subparsers.add_parser("run", help="Run the full extraction pipeline")
    p_run.add_argument("--entity", "-e", required=True, help="Entity to extract")
    p_run.add_argument(
        "--template", "-t",
        default=None,
        help="Template name (default: from config.py)"
    )
    p_run.add_argument(
        "--output", "-o",
        default=None,
        help="Output directory (default: output/reports/)"
    )
    p_run.set_defaults(func=cmd_run)

    # ── batch ─────────────────────────────────────────────────────────────────
    p_batch = subparsers.add_parser(
        "batch", help="Process multiple entities from a text file"
    )
    p_batch.add_argument(
        "--entities", required=True,
        help="Path to text file with one entity per line (# = comment)"
    )
    p_batch.add_argument(
        "--template", "-t",
        default=None,
        help="Template name (default: from config.py)"
    )
    p_batch.add_argument(
        "--output", "-o",
        default=None,
        help="Output directory"
    )
    p_batch.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue batch even if an entity fails"
    )
    p_batch.set_defaults(func=cmd_batch)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
