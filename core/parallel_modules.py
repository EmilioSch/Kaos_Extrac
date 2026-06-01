"""
core/parallel_modules.py — Parallel Section Architecture
=========================================================
Each module generates N sections in parallel → synthesis → offline QC.

API calls per module:
  N sections (parallel) + 1 synthesis + 1 QC correction (only if issues found)

The module definitions (sections, directives) are loaded from the active
YAML template — NOT hardcoded here. This file is domain-agnostic.
"""

import asyncio
import re
from typing import TYPE_CHECKING, Optional, Callable

if TYPE_CHECKING:
    from core.api_client import APIClient
    from core.template_loader import Template

# ── Generic system prompts ────────────────────────────────────────────────────
# These are intentionally broad. Domain-specific instructions go in the YAML template.

def _build_section_system(template: "Template") -> str:
    lang = getattr(template, "output_language", "en")
    domain = getattr(template, "name", "knowledge extraction")
    lang_label = "the language of the source material" if lang == "auto" else lang
    return (
        f"You are KaosExtract, an expert in {domain}. "
        f"You generate ONE SPECIFIC SECTION of an analysis with maximum technical depth. "
        f"Continuous technical narrative, no introductions or closings. "
        f"Every paragraph must be dense with factual, specific information. "
        f"NO generic lists. NO summaries. ONLY deep technical content. "
        f"Write in {lang_label}."
    )


def _build_synthesis_system(template: "Template") -> str:
    lang = getattr(template, "output_language", "en")
    domain = getattr(template, "name", "the domain")
    lang_label = "the language of the source material" if lang == "auto" else lang
    return (
        f"You are KaosExtract-Synth, master synthesizer for {domain}. "
        f"You receive parallel specialized sections and unify them into ONE coherent "
        f"technical document. "
        f"MANDATORY: preserve ALL technical information. Remove only exact duplications. "
        f"Maintain Markdown headers from the template. Tables must be perfectly formatted. "
        f"Write in {lang_label}, without generic bullet points."
    )


def _build_qc_system(template: "Template") -> str:
    lang = getattr(template, "output_language", "en")
    lang_label = "the language of the source material" if lang == "auto" else lang
    return (
        f"You are KaosExtract-QC, quality control agent. "
        f"Fix the received module: encoding errors, broken tables, wrong language, "
        f"missing information. Return the COMPLETE corrected module in {lang_label}."
    )


# ── Main parallel generation function ─────────────────────────────────────────

async def generate_section(
    client: "APIClient",
    entity_name: str,
    master: str,
    mod_id: int,
    mod_name: str,
    section_id: str,
    directive: str,
    template: "Template",
) -> tuple[str, str, int]:
    """
    Generates one focused section of a module.

    Returns:
        (section_id, content, tokens_used)
    """
    directive = directive.replace("{ENTITY}", entity_name)
    entity_label = getattr(template, "entity_label", "entity")

    user_msg = (
        f"{entity_label.upper()}: {entity_name}\n"
        f"MODULE: {mod_id} — {mod_name}\n"
        f"SECTION: {section_id}\n\n"
        f"SECTION DIRECTIVE:\n{directive}\n\n"
        f"AVAILABLE SOURCE MATERIAL:\n"
        f"<source_context>\n{master[:100_000]}\n</source_context>\n\n"
        f"Generate this section with maximum technical depth. "
        f"Minimum 500 words of real, specific content."
    )

    resp, tokens = await client.chat(
        system_prompt=_build_section_system(template),
        user_message=user_msg,
        label=f"M{mod_id}-{section_id}/{entity_name}",
        use_deepseek=False,
        return_tokens=True,
    )
    if resp:
        clean = re.sub(r"<think>.*?</think>", "", resp, flags=re.DOTALL).strip()
        return section_id, clean, tokens
    return section_id, "", tokens


async def synthesize_module(
    client: "APIClient",
    entity_name: str,
    mod_id: int,
    mod_name: str,
    sections: list[tuple[str, str]],
    module_template_text: str,
    template: "Template",
) -> tuple[str, int]:
    """
    Synthesizes all parallel sections into one coherent module.

    Returns:
        (synthesized_content, tokens_used)
    """
    sections_text = ""
    for sec_id, content in sections:
        if content:
            sections_text += f"\n\n═══ SECTION {sec_id} ═══\n{content[:7_000]}\n"

    user_msg = (
        f"ENTITY: {entity_name}\n"
        f"MODULE: {mod_id} — {mod_name}\n\n"
        f"You received {len([s for s in sections if s[1]])} specialized sections:\n"
        f"{sections_text}\n\n"
        f"REQUIRED MODULE STRUCTURE (respect these headers):\n"
        f"{module_template_text[:4_000]}\n\n"
        f"RULES:\n"
        f"1. Preserve ALL technical information from ALL sections\n"
        f"2. Remove only exact duplications\n"
        f"3. Continuous technical narrative in the required language\n"
        f"4. Maintain all template headers\n"
        f"5. Perfect Markdown tables\n"
        f"6. No introductory or closing text"
    )

    resp, tokens = await client.chat(
        system_prompt=_build_synthesis_system(template),
        user_message=user_msg,
        label=f"M{mod_id}-SYNTH/{entity_name}",
        use_deepseek=False,
        return_tokens=True,
    )
    if resp:
        clean = re.sub(r"<think>.*?</think>", "", resp, flags=re.DOTALL).strip()
        return clean, tokens
    return "", tokens


# ── Offline QC (no API call) ───────────────────────────────────────────────────

def qc_offline(content: str) -> dict:
    """
    Quality control without an API call — detects common issues.
    Returns a dict with found issues. Empty dict = no issues.
    """
    issues = {}

    # Encoding corruption
    encoding_artifacts = [
        (r"â€[™\"'`]", "UTF-8 decoded as Latin-1"),
        (r"Ã[¡éíóúñ¿]", "Spanish chars corrupted"),
        (r"\uFFFD", "Replacement character found"),
        (r"&#\d+;", "HTML entities not decoded"),
    ]
    enc_found = [desc for pat, desc in encoding_artifacts if re.search(pat, content)]
    if enc_found:
        issues["encoding"] = enc_found

    # Broken tables: rows with inconsistent column counts
    table_rows = re.findall(r"^\|.+\|$", content, re.MULTILINE)
    if table_rows:
        col_counts = [row.count("|") for row in table_rows]
        if len(set(col_counts)) > 2:
            issues["tables"] = f"Inconsistent columns: {set(col_counts)}"

    # Empty sections (headers with no content)
    empty_sections = re.findall(r"#{2,4} .+\n{1,2}(?=#{2,4}|\Z)", content)
    if empty_sections:
        issues["empty_sections"] = len(empty_sections)

    return issues


async def qc_api_fix(
    client: "APIClient",
    entity_name: str,
    mod_id: int,
    mod_name: str,
    content: str,
    issues: dict,
    template: "Template",
) -> tuple[str, int]:
    """
    If critical QC issues found, calls API to fix them.

    Returns:
        (corrected_content, tokens_used)
    """
    issues_str = "\n".join(f"- {k}: {v}" for k, v in issues.items())
    user_msg = (
        f"ENTITY: {entity_name} — Module {mod_id} {mod_name}\n\n"
        f"DETECTED ISSUES TO FIX:\n{issues_str}\n\n"
        f"MODULE TO CORRECT:\n{content[:60_000]}\n\n"
        f"Return the COMPLETE and CORRECTED module. No additional text."
    )
    resp, tokens = await client.chat(
        system_prompt=_build_qc_system(template),
        user_message=user_msg,
        label=f"M{mod_id}-QC/{entity_name}",
        use_deepseek=False,
        return_tokens=True,
    )
    if resp:
        clean = re.sub(r"<think>.*?</think>", "", resp, flags=re.DOTALL).strip()
        return clean, tokens
    return content, tokens  # Return original if fix fails


# ── Orchestrator ───────────────────────────────────────────────────────────────

async def run_module_parallel(
    client: "APIClient",
    entity_name: str,
    master: str,
    module_def: dict,
    template: "Template",
    progress_log: Optional[Callable[[str], None]] = None,
) -> tuple[int, str, str, int]:
    """
    Runs the full parallel architecture for one module:
      1. N sections in parallel (loaded from template YAML)
      2. Synthesis into one coherent document
      3. Offline QC + API fix if critical issues found

    Args:
        client:       API client instance
        entity_name:  Name of the entity being analyzed
        master:       Master document text (consolidated from all sources)
        module_def:   Module definition dict from template (id, name, sections, ...)
        template:     Active Template object (for prompts and language settings)
        progress_log: Optional callback for progress updates

    Returns:
        (module_id, module_name, content, tokens_total)
    """
    mod_id = module_def["id"]
    mod_name = module_def["name"]
    sections_def = module_def.get("sections", [])
    mod_template_text = module_def.get("template_text", "")

    def _log(msg: str):
        if progress_log:
            progress_log(msg)

    _log(f"[M{mod_id}] {mod_name}: launching {len(sections_def)} parallel sections...")

    # ── Step 1: Generate sections in parallel ─────────────────────────────────
    section_tasks = [
        generate_section(
            client, entity_name, master,
            mod_id, mod_name,
            sec["id"], sec["directive"],
            template,
        )
        for sec in sections_def
    ]
    section_results: list[tuple[str, str, int]] = await asyncio.gather(*section_tasks)

    sections_for_synth = [(sid, content) for sid, content, _ in section_results]
    total_tokens = sum(tok for _, _, tok in section_results)

    filled = sum(1 for _, c in sections_for_synth if c)
    _log(f"[M{mod_id}] {filled}/{len(sections_def)} sections done → synthesizing...")

    # ── Step 2: Synthesis ──────────────────────────────────────────────────────
    synthesis, synth_tokens = await synthesize_module(
        client, entity_name, mod_id, mod_name,
        sections_for_synth, mod_template_text,
        template,
    )
    total_tokens += synth_tokens

    if not synthesis:
        # Fallback: concatenate sections directly
        synthesis = "\n\n---\n\n".join(c for _, c in sections_for_synth if c)

    # ── Step 3: Offline QC ─────────────────────────────────────────────────────
    issues = qc_offline(synthesis)
    if issues:
        critical = [k for k in issues if k in ("encoding", "language")]
        if critical:
            _log(f"[M{mod_id}] ⚠ QC issues: {list(issues.keys())} — fixing with API...")
            synthesis, qc_tokens = await qc_api_fix(
                client, entity_name, mod_id, mod_name, synthesis, issues, template
            )
            total_tokens += qc_tokens
        else:
            _log(f"[M{mod_id}] ⚠ QC minor: {list(issues.keys())} — accepted")
    else:
        _log(f"[M{mod_id}] ✓ QC passed")

    return mod_id, mod_name, synthesis, total_tokens
