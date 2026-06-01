"""
pipeline/ingest.py — Book and Source Ingestion
================================================
PURPOSE: Converts PDFs and other formats to the clean TXT that the pipeline expects.
         Detects encoding automatically, repairs OCR artifacts, and organizes
         files into the upload/ directory structure.

USAGE:
  python kaosextract.py ingest my_textbook.pdf
  python kaosextract.py ingest ./my_library/ --category books --pattern "*.pdf"
"""

import re
from pathlib import Path
from typing import Optional
from datetime import datetime

import config
from core.logger import get_logger

log = get_logger(__name__)

# Category name → upload sub-directory
CATEGORY_MAP: dict[str, Path] = {
    "books":    config.BOOKS_DIR,
    "notes":    config.CLASSES_DIR,
    "lectures": config.ASESORIAS_DIR,
    "articles": config.ARTICLES_DIR,
    "exams":    config.EXAMENES_DIR,
    "other":    config.OTHERS_DIR,
}

DEFAULT_CATEGORY = "books"


def ingest_file(
    source_path: Path,
    category: str = DEFAULT_CATEGORY,
    force: bool = False,
) -> dict:
    """
    Ingests a file (PDF or TXT) into the KaosExtract system.

    Args:
        source_path: Path to the file to ingest.
        category:    Source category ("books", "notes", "lectures", etc.)
        force:       If True, overwrites if the file already exists in upload/.

    Returns:
        Metadata dict:
        {
            "original_name": str,
            "saved_as": str,
            "category": str,
            "size_bytes": int,
            "char_count": int,
            "conversion": str,   # "none" | "pdf_to_txt"
            "ocr_repaired": bool,
            "ingested_at": str,
        }
    """
    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    suffix = source_path.suffix.lower()
    target_dir = CATEGORY_MAP.get(category.lower(), config.BOOKS_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)

    # ── PDF → TXT conversion ─────────────────────────────────────────────────
    conversion = "none"
    if suffix == ".pdf":
        log.info(f"Converting PDF: {source_path.name}")
        text = _pdf_to_text(source_path)
        conversion = "pdf_to_txt"
        target_name = source_path.stem + ".txt"
    elif suffix in (".txt", ".md", ""):
        text = source_path.read_text(encoding="utf-8", errors="replace")
        target_name = source_path.stem + ".txt"
    else:
        raise ValueError(
            f"Unsupported file type: '{suffix}'. Supported: .pdf, .txt, .md"
        )

    # ── OCR repair ───────────────────────────────────────────────────────────
    original_len = len(text)
    text = _fix_ocr_text(text)
    ocr_repaired = len(text) != original_len

    # ── Save to upload/ ──────────────────────────────────────────────────────
    target_path = target_dir / target_name

    if target_path.exists() and not force:
        raise FileExistsError(
            f"'{target_name}' already exists in {target_dir.name}/. "
            f"Use --force to overwrite."
        )

    target_path.write_text(text, encoding="utf-8")
    log.info(f"Saved: {target_path} ({len(text):,} chars)")

    return {
        "original_name": source_path.name,
        "saved_as": str(target_path.relative_to(config.PROJECT_ROOT)),
        "category": category,
        "size_bytes": target_path.stat().st_size,
        "char_count": len(text),
        "conversion": conversion,
        "ocr_repaired": ocr_repaired,
        "ingested_at": datetime.now().isoformat(),
    }


def ingest_directory(
    source_dir: Path,
    category: str = DEFAULT_CATEGORY,
    force: bool = False,
    pattern: str = "*.pdf",
) -> list[dict]:
    """
    Ingests all files in a directory matching the given glob pattern.

    Returns:
        List of metadata dicts for successfully ingested files.
    """
    files = list(source_dir.glob(pattern))
    if not files:
        log.warning(f"No files matching '{pattern}' found in {source_dir}")
        return []

    results = []
    for f in files:
        try:
            meta = ingest_file(f, category=category, force=force)
            results.append(meta)
            print(f"  ✓ {f.name} → {meta['saved_as']} ({meta['char_count']:,} chars)")
        except FileExistsError as e:
            print(f"  ⚠ {f.name}: {e}")
        except Exception as e:
            log.error(f"Failed to ingest {f.name}: {e}")
            print(f"  ✗ {f.name}: {e}")

    return results


def list_sources() -> dict[str, list[dict]]:
    """
    Lists all sources available in upload/, organized by category.

    Returns:
        Dict {category_name: [{"name": str, "size_mb": float, "chars": int}, ...]}
    """
    result = {}
    for cat_name, cat_dir in CATEGORY_MAP.items():
        if not cat_dir.exists():
            continue
        files = []
        for f in sorted(cat_dir.glob("*.txt")):
            try:
                size_mb = f.stat().st_size / 1_000_000
                char_count = len(f.read_text(encoding="utf-8", errors="replace"))
                files.append({
                    "name": f.name,
                    "size_mb": round(size_mb, 2),
                    "chars": char_count,
                    "path": str(f),
                })
            except Exception:
                pass
        if files:
            result[cat_name] = files
    return result


# ── Private helpers ───────────────────────────────────────────────────────────

def _pdf_to_text(pdf_path: Path) -> str:
    """
    Converts a PDF to plain text using pdfminer.six (primary) or PyMuPDF (fallback).
    """
    # Attempt 1: pdfminer.six (better extraction quality)
    try:
        from pdfminer.high_level import extract_text as pdfminer_extract
        text = pdfminer_extract(str(pdf_path))
        if text and len(text.strip()) > 100:
            log.debug(f"PDF converted with pdfminer: {len(text):,} chars")
            return text
    except ImportError:
        log.debug("pdfminer.six not installed. Trying PyMuPDF...")
    except Exception as e:
        log.warning(f"pdfminer failed: {e}. Trying PyMuPDF...")

    # Attempt 2: PyMuPDF (fitz)
    try:
        import fitz  # type: ignore
        doc = fitz.open(str(pdf_path))
        pages_text = [page.get_text() for page in doc]
        doc.close()
        text = "\n\n".join(pages_text)
        if text and len(text.strip()) > 100:
            log.debug(f"PDF converted with PyMuPDF: {len(text):,} chars")
            return text
    except ImportError:
        pass
    except Exception as e:
        log.warning(f"PyMuPDF failed: {e}")

    raise RuntimeError(
        f"Could not convert PDF '{pdf_path.name}'. "
        "Install pdfminer.six or PyMuPDF:\n"
        "  pip install pdfminer.six\n"
        "  pip install pymupdf"
    )


def _fix_ocr_text(text: str) -> str:
    """
    Repairs OCR-spaced text where the scanner separated individual letters.
    Example: 'S tr e p to c o c c u s' → 'Streptococcus'
    Only collapses blocks of 4+ consecutive 1-3 letter groups to avoid
    affecting normal text (prepositions, articles, etc.).
    """
    pattern = re.compile(
        r'(?<![\w])'
        r'((?:[A-Za-záéíóúüñÁÉÍÓÚÜÑ]{1,3} ){3,}[A-Za-záéíóúüñÁÉÍÓÚÜÑ]{1,3})'
        r'(?![\w])'
    )
    return pattern.sub(lambda m: m.group(0).replace(' ', ''), text)
