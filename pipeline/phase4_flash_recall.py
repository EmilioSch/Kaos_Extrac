"""
pipeline/phase4_flash_recall.py — Fase 4: Flash Recall Matrix
==============================================================
PROPÓSITO: Genera la Matriz de Recuperación Rápida a partir del reporte
           Markdown completo (resultado de las Fases 1-3) ya existente en disco.

FLUJO:
  1. Localiza el archivo .md del reporte final en resultados/reportes/
  2. Lee su contenido completo (es el documento más rico: 7 módulos integrados)
  3. Llama a la API con el prompt Flash Recall (Fase 4) y el reporte como contexto
  4. Guarda el resultado en resultados/flash_recall/{bacteria}_flash.md

DIFERENCIAS CON LAS FASES ANTERIORES:
  - No requiere acceder a fuentes primarias — opera sobre el reporte ya generado
  - Una sola llamada a la API (muy eficiente en tokens y en quota)
  - Puede ejecutarse de forma INDEPENDIENTE sobre cualquier bacteria ya procesada
  - También puede ejecutarse en BATCH sobre todas las bacterias procesadas

USO (desde main.py):
    from pipeline.phase4_flash_recall import run_phase4, run_phase4_batch
    await run_phase4("Staphylococcus aureus", api_client)
    await run_phase4_batch(api_client)   # Procesa todas las bacterias en reportes/
"""

import asyncio
import re
from pathlib import Path

from core.api_client import APIClient
from core.logger import get_logger
from prompts.flash_recall import build_flash_recall_message
from prompts.system import PROTOCOLO_ARQUITECTO_V3
from output.image_generator import generate_flash_image
import config

log = get_logger(__name__)

# ── Directorio de salida exclusivo para flash recalls ─────────────────────────
FLASH_RECALL_DIR: Path = config.OUTPUT_BASE_DIR / "flash_recall"


async def run_phase4(
    entity_name: str,
    api_client: APIClient,
    force_refresh: bool = False,
    generate_image: bool = True,
) -> Path | None:
    """
    Genera la Flash Recall Matrix para una bacteria específica.

    Busca el reporte .md de la bacteria en resultados/reportes/.
    Si no existe, avisa y retorna None sin lanzar excepción.

    Args:
        entity_name:     Nombre de la bacteria (ej: "Staphylococcus aureus")
        api_client:      Instancia compartida del cliente de API
        force_refresh:   Si True, regenera aunque ya exista el flash .md en disco
        generate_image:  Si True, genera también una imagen PNG de la matriz

    Returns:
        Path al archivo flash_recall .md generado, o None si no pudo generarse.
    """
    FLASH_RECALL_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = _sanitize_filename(entity_name)

    # ── Verificar si ya existe el flash recall ────────────────────────────────
    output_file = FLASH_RECALL_DIR / f"{safe_name}_flash.md"
    if output_file.exists() and not force_refresh:
        log.info(f"[FASE 4] Flash recall ya existe (usando caché): {output_file.name}")
        return output_file

    # ── Localizar el reporte fuente (.md completo de 7 módulos) ──────────────
    report_file = _find_report_file(entity_name, safe_name)
    if report_file is None:
        log.error(
            f"[FASE 4] No se encontró el reporte para '{entity_name}'. "
            f"Ejecuta primero el pipeline completo (python main.py \"{entity_name}\")."
        )
        return None

    log.info(f"[FASE 4] Fuente: {report_file.name} ({report_file.stat().st_size:,} bytes)")

    # ── Leer el reporte completo ──────────────────────────────────────────────
    report_text = report_file.read_text(encoding="utf-8")

    # ── Construir el mensaje ──────────────────────────────────────────────────
    user_message = build_flash_recall_message(
        entity_name=entity_name,
        report_text=report_text,
    )

    # ── Llamada a la API ──────────────────────────────────────────────────────
    log.info(f"[FASE 4] Enviando solicitud de Flash Recall para: {entity_name}")
    result = await api_client.chat(
        system_prompt=PROTOCOLO_ARQUITECTO_V3,
        user_message=user_message,
        label=f"Fase4/FlashRecall-{entity_name}",
    )

    if result is None:
        log.error(f"[FASE 4] La API no respondió para: {entity_name}")
        return None

    # ── Limpiar bloques <think> del resultado ─────────────────────────────────
    clean_result = re.sub(r'<think>.*?</think>', '', result, flags=re.DOTALL).strip()

    # ── Guardar en disco ──────────────────────────────────────────────────────
    output_file.write_text(clean_result, encoding="utf-8")
    log.info(f"[FASE 4] ✓ Flash Recall guardado: {output_file}")

    # ── Generar imagen PNG ────────────────────────────────────────────────────
    if generate_image:
        try:
            img_file = generate_flash_image(output_file)
            log.info(f"[FASE 4] ✓ Imagen generada: {img_file}")
        except Exception as e:
            log.warning(f"[FASE 4] ⚠ Imagen no generada: {e}")

    return output_file


async def run_phase4_batch(
    api_client: APIClient,
    force_refresh: bool = False,
    concurrency: int = 2,
) -> dict[str, Path | None]:
    """
    Genera Flash Recall Matrices para TODAS las bacterias con reportes existentes.

    Descubre automáticamente los archivos .md en resultados/reportes/,
    ignora archivos _thoughts.md y los que ya tienen flash generado.

    Args:
        api_client:    Instancia compartida del cliente de API
        force_refresh: Si True, regenera todos aunque ya existan
        concurrency:   Máximo de llamadas paralelas a la API (respetar rate limit)

    Returns:
        Diccionario {nombre_bacteria: path_flash_md | None}
    """
    # Descubrir todos los reportes disponibles
    all_bacteria = _discover_processed_bacteria()
    if not all_bacteria:
        log.warning("[FASE 4 BATCH] No se encontraron reportes en resultados/reportes/")
        return {}

    log.info(f"[FASE 4 BATCH] Bacterias descubiertas: {len(all_bacteria)}")
    for name in all_bacteria:
        log.info(f"  · {name}")

    # Filtrar las que ya tienen flash (si no se fuerza regeneración)
    if not force_refresh:
        pending = []
        skipped = []
        for name in all_bacteria:
            safe = _sanitize_filename(name)
            flash_path = FLASH_RECALL_DIR / f"{safe}_flash.md"
            if flash_path.exists():
                skipped.append(name)
            else:
                pending.append(name)

        if skipped:
            log.info(f"[FASE 4 BATCH] Ya procesadas (usando caché): {len(skipped)}")
        log.info(f"[FASE 4 BATCH] Pendientes de procesar: {len(pending)}")
    else:
        pending = all_bacteria

    if not pending:
        log.info("[FASE 4 BATCH] Todas las bacterias ya tienen flash recall generado.")
        # Retornar los paths existentes
        return {
            name: FLASH_RECALL_DIR / f"{_sanitize_filename(name)}_flash.md"
            for name in all_bacteria
        }

    # Procesar en grupos con límite de concurrencia
    results: dict[str, Path | None] = {}
    semaphore = asyncio.Semaphore(concurrency)

    async def _process_with_semaphore(name: str) -> tuple[str, Path | None]:
        async with semaphore:
            path = await run_phase4(name, api_client, force_refresh=force_refresh)
            return name, path

    tasks = [_process_with_semaphore(name) for name in pending]
    batch_results = await asyncio.gather(*tasks, return_exceptions=True)

    for item in batch_results:
        if isinstance(item, Exception):
            log.error(f"[FASE 4 BATCH] Error en tarea: {item}")
        else:
            name, path = item
            results[name] = path

    # Agregar los que ya tenían flash (no fueron re-procesados)
    if not force_refresh:
        for name in skipped:
            safe = _sanitize_filename(name)
            results[name] = FLASH_RECALL_DIR / f"{safe}_flash.md"

    success = sum(1 for p in results.values() if p is not None)
    log.info(f"[FASE 4 BATCH] ✓ Completado: {success}/{len(all_bacteria)} flash recalls generados.")

    return results


async def run_phase4_consolidated() -> Path | None:
    """
    Genera un documento CONSOLIDADO con todos los Flash Recalls en un solo archivo.

    Lee todos los archivos _flash.md existentes en resultados/flash_recall/
    y los concatena en orden alfabético en un único índice maestro.

    IMPORTANTE: Esta función NO llama a la API. Solo concatena archivos locales.
    Úsala DESPUÉS de correr run_phase4_batch() para crear el documento de repaso final.

    Returns:
        Path al archivo flash_recall_MASTER.md, o None si no hay ningún flash.
    """
    FLASH_RECALL_DIR.mkdir(parents=True, exist_ok=True)
    flash_files = sorted(FLASH_RECALL_DIR.glob("*_flash.md"))

    if not flash_files:
        log.warning("[FASE 4 CONSOLIDADO] No hay archivos flash_recall generados todavía.")
        return None

    log.info(f"[FASE 4 CONSOLIDADO] Consolidando {len(flash_files)} flash recalls...")

    sections = [
        "# 🧬 MASTER FLASH — Bacteriología\n",
        "> Documento de recuperación rápida generado por Kaos.\n",
        "> Contiene la Matriz Flash de cada bacteria procesada en orden alfabético.\n\n",
        "---\n\n",
    ]

    # Tabla de contenidos automática
    sections.append("## Índice\n\n")
    for flash_file in flash_files:
        # Extraer nombre de bacteria desde el nombre de archivo
        bact_name = flash_file.stem.replace("_flash", "").replace("_", " ")
        anchor = flash_file.stem.replace("_flash", "").lower()
        sections.append(f"- [{bact_name}](#{anchor})\n")

    sections.append("\n---\n\n")

    # Contenido de cada flash
    for flash_file in flash_files:
        content = flash_file.read_text(encoding="utf-8").strip()
        # Añadir un anchor HTML para navegación en Obsidian
        bact_id = flash_file.stem.replace("_flash", "").lower()
        sections.append(f'<a id="{bact_id}"></a>\n\n')
        sections.append(content)
        sections.append("\n\n---\n\n")

    master_content = "".join(sections)
    master_file = FLASH_RECALL_DIR / "flash_recall_MASTER.md"
    master_file.write_text(master_content, encoding="utf-8")

    log.info(f"[FASE 4 CONSOLIDADO] ✓ Master guardado: {master_file} ({len(master_content):,} chars)")
    return master_file


# ── Helpers privados ──────────────────────────────────────────────────────────

def _find_report_file(entity_name: str, safe_name: str) -> Path | None:
    """
    Localiza el archivo de reporte .md para la entidad dada.
    Primero busca por nombre exacto sanitizado, luego hace búsqueda fuzzy.
    """
    # Intento 1: nombre exacto sanitizado
    exact = config.REPORTS_MD_DIR / f"{safe_name}.md"
    if exact.exists():
        return exact

    # Intento 2: búsqueda fuzzy — buscar archivos que empiecen con el género+especie
    parts = entity_name.split()
    if len(parts) >= 2:
        prefix = f"{parts[0]}_{parts[1]}"
        candidates = list(config.REPORTS_MD_DIR.glob(f"{prefix}*.md"))
        # Excluir archivos _thoughts.md
        candidates = [c for c in candidates if "_thoughts" not in c.name]
        if candidates:
            log.debug(f"[FASE 4] Reporte encontrado por búsqueda fuzzy: {candidates[0].name}")
            return candidates[0]

    # Intento 3: género solo
    if parts:
        genus_prefix = parts[0]
        candidates = list(config.REPORTS_MD_DIR.glob(f"{genus_prefix}*.md"))
        candidates = [c for c in candidates if "_thoughts" not in c.name]
        if candidates:
            log.debug(f"[FASE 4] Reporte encontrado por género: {candidates[0].name}")
            return candidates[0]

    return None


def _discover_processed_bacteria() -> list[str]:
    """
    Descubre todas las bacterias con reportes completos en resultados/reportes/MD/.
    Excluye archivos _thoughts.md y el propio flash_recall si hubiera.
    Retorna los nombres reconstruidos desde el nombre de archivo.
    """
    if not config.REPORTS_MD_DIR.exists():
        return []

    bacteria_names = []
    for md_file in sorted(config.REPORTS_MD_DIR.glob("*.md")):
        # Excluir thoughts y archivos auxiliares
        if "_thoughts" in md_file.name:
            continue
        # Reconstruir nombre aproximado (reemplazar _ por espacio)
        name = md_file.stem.replace("_", " ").strip()
        bacteria_names.append(name)

    return bacteria_names


def _sanitize_filename(name: str) -> str:
    return re.sub(r'[^\w\-.]', '_', name).strip('_')
