"""
pipeline/phase2_consolidation.py — Fase 2: Consolidación en Master Document
=============================================================================
PROPÓSITO: Toma las extracciones de la Fase 1 (una por fuente) y las funde
           en un único documento master que sirve de base para el análisis.

PROCESO:
  1. Recibe el dict {fuente: extracción} de la Fase 1
  2. Descarta fuentes sin información
  3. Valida citación obligatoria [Fuente:] en cada fuente
  4. Si falta citación, intenta reparar con llamada API
  5. Construye master por concatenación directa (orden jerárquico)
  6. Guarda el resultado como bacteria_master.md

IMPORTANCIA DEL MASTER:
  El bacteria_master.md es el documento más valioso del pipeline.
  Contiene TODA la información disponible sobre la bacteria, sin redundancias,
  organizada por jerarquía de fuentes. Los 7 módulos de la Fase 3 trabajan
  exclusivamente con este documento.
"""

import re
from pathlib import Path
from core.api_client import APIClient
from core.logger import get_logger
import config

log = get_logger(__name__)


async def run_phase2(
    entity_name: str,
    extractions: dict[str, str],
    api_client: APIClient,
) -> str:
    """
    Ejecuta la Fase 2: consolida todas las extracciones en el master document.

    Args:
        entity_name: Nombre de la entidad
        extractions:   Resultado de la Fase 1 {nombre_fuente: texto}
        api_client:    Instancia compartida del cliente de API

    Returns:
        Texto completo del master document en Markdown.
        En caso de error, retorna un master mínimo con las extracciones brutas.
    """
    log.info(f"[FASE 2] Iniciando consolidación para: {entity_name}")

    safe_name = _sanitize_filename(entity_name)
    master_file = config.MASTERS_DIR / f"{safe_name}_master.md"
    config.MASTERS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Verificar caché del master ───────────────────────────────────────────
    if master_file.exists() and config.KEEP_INTERMEDIATE_FILES:
        log.info(f"[FASE 2] Usando master en caché: {master_file.name}")
        return master_file.read_text(encoding="utf-8")

    # ── Filtrar fuentes sin datos ────────────────────────────────────────────
    valid_sources = {
        k: v for k, v in extractions.items()
        if v and "FUENTE_SIN_INFORMACIÓN_RELEVANTE" not in v
    }

    if not valid_sources:
        log.error(f"[FASE 2] No hay información de ninguna fuente para '{entity_name}'")
        error_master = f"# {entity_name}\n\n> ⚠️ No se encontró información en ninguna fuente disponible."
        master_file.write_text(error_master, encoding="utf-8")
        return error_master

    # ── VALIDACIÓN DE CITACIÓN (MEJORA CRÍTICA) ──────────────────────────────
    # Verificar que cada fuente tenga tags [Fuente:] antes de consolidar
    log.info(f"[FASE 2] Validando citación en {len(valid_sources)} fuentes...")
    
    validated_sources = {}
    repair_tasks = []  # Fuentes que necesitan reparación

    # Primera pasada: verificar qué fuentes necesitan reparación
    for source_name, text in valid_sources.items():
        citation_count = len(re.findall(r'\[Fuente:', text))

        if citation_count == 0:
            log.warning(f"[FASE 2] ⚠️ '{source_name}' NO tiene citaciones [Fuente:]")
            repair_tasks.append((source_name, text))
        else:
            validated_sources[source_name] = text
            log.info(f"[FASE 2] ✓ '{source_name}': {citation_count} citaciones verificadas")

    # Si hay fuentes que necesitan reparación, hacerlas EN PARALELO (optimización)
    if repair_tasks:
        log.info(f"[FASE 2] Reparando {len(repair_tasks)} fuentes en PARALELO...")
        
        repair_coroutines = [
            _repair_citations(entity_name, source_name, text, api_client)
            for source_name, text in repair_tasks
        ]
        
        import asyncio
        repair_results = await asyncio.gather(*repair_coroutines)

        # Procesar resultados de reparaciones
        for (source_name, _), repaired in zip(repair_tasks, repair_results):
            if repaired and len(re.findall(r'\[Fuente:', repaired)) > 0:
                validated_sources[source_name] = repaired
                log.info(f"[FASE 2] ✓ '{source_name}' reparada: {len(re.findall(r'\[Fuente:', repaired))} citaciones")
            else:
                log.error(f"[FASE 2] ✗ '{source_name}' NO PUDO ser reparada. Se descarta.")

    if not validated_sources:
        log.error(f"[FASE 2] Ninguna fuente pasó la validación de citación")
        return f"# {entity_name}\n\n> ⚠️ Error: Las fuentes no tienen citación obligatoria."

    fuente_count = len(validated_sources)
    log.info(f"[FASE 2] Consolidando {fuente_count} fuente(s) con citación válida")

    # ── Construcción directa del master (sin API) ────────────────────────────
    log.info(f"[FASE 2] Construyendo master por concatenación directa ({fuente_count} fuentes)...")

    # Orden de prioridad para concatenar (las fuentes más importantes primero)
    SOURCE_PRIORITY_ORDER = [
        "Mandell", "Sherris", "Murray",
        "Libros en espanol", "Libros en ingles",
        "Examenes Reales", "Clases, asesorias y otros",
    ]
    ordered_sources = sorted(
        validated_sources.items(),
        key=lambda x: next((i for i, s in enumerate(SOURCE_PRIORITY_ORDER) if s.lower() in x[0].lower()), 99)
    )

    master_text = _build_direct_master(entity_name, ordered_sources)

    # ── Encabezado del master ────────────────────────────────────────────────
    total_chars = sum(len(v) for v in validated_sources.values())
    header = (
        f"# MASTER DOCUMENT: {entity_name}\n"
        f"*Generado por Kaos — {fuente_count} fuentes — {total_chars:,} chars brutos*\n\n"
        "---\n\n"
    )
    final_master = header + master_text

    # ── Verificación final ───────────────────────────────────────────────────
    final_citations = len(re.findall(r'\[Fuente:', final_master))
    log.info(f"[FASE 2] Master final: {final_citations} citaciones totales")

    # ── Guardar master ───────────────────────────────────────────────────────
    master_file.write_text(final_master, encoding="utf-8")
    log.info(f"[FASE 2] ✓ Master guardado: {master_file}")

    return final_master


async def _repair_citations(
    entity_name: str,
    source_name: str,
    text: str,
    api_client: APIClient,
) -> str:
    """
    Intenta reparar citaciones faltantes en una extracción usando la API.
    Toma el texto y le pide al modelo que re-escriba con citaciones obligatorias.
    """
    log.info(f"[FASE 2] Reparando citaciones para '{source_name}'...")

    # Limitar texto para no exceder tokens (8k chars)
    truncated_text = text[:8000]

    repair_prompt = f"""You are a medical text repair system.
The following extraction about "{entity_name}" from source "{source_name}" is missing proper citations.

ORIGINAL TEXT:
{truncated_text}

TASK:
1. Read the text above
2. Add "[Fuente: {source_name}]" prefix to EVERY piece of information
3. Keep all original content, do not summarize or change meaning
4. If information is already cited, keep the existing citation
5. Output ONLY the repaired text - NO explanation, NO thinking, NO analysis

IMPORTANT: Your response must be ONLY the repaired text with [Fuente: {source_name}] prefixes.
Do NOT include any thinking, reasoning, or meta-commentary. Start directly with the first piece of information."""

    result = await api_client.chat(
        system_prompt="You are a precise medical text editor. Add citations where missing. Output ONLY the repaired text, no explanations.",
        user_message=repair_prompt,
        label=f"Phase2-Repair/{source_name}",
    )

    if result:
        # Limpieza robusta de bloques think y contenido no deseado
        result = _clean_think_blocks(result)
        return result

    return text  # Devolver original si falla la reparación


def _clean_think_blocks(text: str) -> str:
    """
    Limpia bloques de pensamiento, razonamiento interno y contenido no deseado.
    """
    # Patrón para bloques típícos de think
    text = re.sub(r'<think>.*?', '', text, flags=re.DOTALL)

    # Limpiar bloques con etiquetas alternatives
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<reasoning>.*?</reasoning>', '', text, flags=re.DOTALL | re.IGNORECASE)

    # Limpiar líneas que empiezan con indicadores de reasoning
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        # Saltar líneas que son claramente reasoning interno
        stripped = line.strip()
        if stripped.startswith('Let me') or stripped.startswith('Looking at the text'):
            continue
        if stripped.startswith('I need to') or stripped.startswith('The user wants'):
            continue
        if stripped.startswith('Actually,') and 'Looking more carefully' in stripped:
            continue
        if stripped.startswith('However,') and len(stripped) < 100:
            continue
        cleaned_lines.append(line)

    text = '\n'.join(cleaned_lines)

    # Limpiar espacios múltiples
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def _build_direct_master(entity_name: str, ordered_sources: list[tuple[str, str]]) -> str:
    """
    Construye el master document concatenando directamente todas las extracciones
    en orden de jerarquía de fuentes. Sin pasar por la API, sin pérdida de información.
    Cada sección está claramente delimitada con el nombre de la fuente.
    """
    parts = []
    for source_name, text in ordered_sources:
        separator = "=" * 70
        parts.append(
            f"\n{separator}\n"
            f"## FUENTE: {source_name}\n"
            f"{separator}\n\n"
            f"{text.strip()}\n"
        )
    return "\n".join(parts)


def _sanitize_filename(name: str) -> str:
    return re.sub(r'[^\w\-.]', '_', name).strip('_')
