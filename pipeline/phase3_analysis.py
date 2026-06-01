"""
pipeline/phase3_analysis.py — Phase 3: Parallel Module Analysis
================================================================
Executes all analysis modules in parallel over the master document.
Module definitions (sections, directives, names) come from the active
YAML template — this file is fully domain-agnostic.

ARCHITECTURE per module:
  N parallel sections → synthesis → offline QC (→ API fix if critical)

All modules run concurrently via asyncio.gather.
"""

import asyncio
import re
from typing import Optional, Callable

from core.api_client import APIClient
from core.parallel_modules import run_module_parallel
from core.logger import get_logger
import config

log = get_logger(__name__)


async def run_phase3(
    entity_name: str,
    master_text: str,
    api_client: APIClient,
    template=None,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> dict[int, str]:
    """
    Runs all analysis modules in parallel over the master document.

    Args:
        entity_name:       Entity being analyzed (e.g. "Streptococcus pyogenes")
        master_text:       Consolidated master document from Phase 2
        api_client:        Shared API client instance
        template:          Active Template object (loads modules from YAML).
                           If None, tries to load from config.ACTIVE_TEMPLATE.
        progress_callback: Optional callback(n_completed) for progress reporting.

    Returns:
        Dict {module_id: module_content_text}
    """
    # Load template if not provided
    if template is None:
        from core.template_loader import load_template
        template = load_template()

    modules = template.modules
    log.info(f"[PHASE 3] Starting parallel analysis — {len(modules)} modules for: {entity_name}")

    # Create cache directory for this entity
    safe_name = _sanitize_filename(entity_name)
    cache_dir = config.CACHE_DIR / safe_name / "modules"
    cache_dir.mkdir(parents=True, exist_ok=True)

    completed_count = 0

    async def _run_one(module_def: dict) -> tuple[int, str]:
        nonlocal completed_count

        mod_id = module_def["id"]
        mod_name = module_def["name"]

        # ── Check cache ───────────────────────────────────────────────────────
        cache_file = cache_dir / f"module_{mod_id:02d}_{_sanitize_filename(mod_name)}.md"
        if cache_file.exists() and config.KEEP_INTERMEDIATE_FILES:
            log.info(f"[PHASE 3] Module {mod_id} ({mod_name}): using cache")
            text = cache_file.read_text(encoding="utf-8")
            completed_count += 1
            if progress_callback:
                progress_callback(completed_count)
            return mod_id, text

        # ── Run parallel sections → synthesis → QC ────────────────────────────
        def _log(msg: str):
            log.info(f"[PHASE 3] {msg}")

        mod_id_out, mod_name_out, content, tokens = await run_module_parallel(
            client=api_client,
            entity_name=entity_name,
            master=master_text,
            module_def=module_def,
            template=template,
            progress_log=_log,
        )

        log.info(
            f"[PHASE 3] Module {mod_id} ({mod_name}): ✓ "
            f"({len(content):,} chars, ~{tokens:,} tokens)"
        )

        # ── Save to cache ─────────────────────────────────────────────────────
        if content and config.KEEP_INTERMEDIATE_FILES:
            cache_file.write_text(content, encoding="utf-8")

        completed_count += 1
        if progress_callback:
            progress_callback(completed_count)

        return mod_id_out, content

    # Launch all modules concurrently
    log.info(f"[PHASE 3] Launching {len(modules)} modules in parallel...")
    raw_results = await asyncio.gather(
        *[_run_one(mod) for mod in modules],
        return_exceptions=True,
    )

    # Build results dict
    results: dict[int, str] = {}
    for module_def, result in zip(modules, raw_results):
        mod_id = module_def["id"]
        mod_name = module_def["name"]

        if isinstance(result, Exception):
            log.error(f"[PHASE 3] Module {mod_id} ({mod_name}) failed: {result}")
            results[mod_id] = (
                f"## Module {mod_id}: {mod_name.upper()}\n\n"
                f"> ⚠️ Analysis failed: {result}"
            )
        else:
            _, content = result
            results[mod_id] = content

    valid = sum(1 for v in results.values() if v and "failed" not in v.lower())
    log.info(f"[PHASE 3] ✓ Complete. {valid}/{len(modules)} modules generated successfully.")
    return results


def _sanitize_filename(name: str) -> str:
    return re.sub(r'[^\w\-.]', '_', name).strip('_')
