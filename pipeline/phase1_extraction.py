"""
pipeline/phase1_extraction.py — Fase 1: Extracción Paralela por Fuente
=======================================================================
PROPÓSITO: Para cada grupo de fuentes, extrae localmente el texto relevante
           para la bacteria indicada y lo envía a la API para generar un
           resumen estructurado de esa fuente.

GRUPOS DE EXTRACCIÓN:
  ┌─────────────────────┬──────────────────────────────────────────┐
  │ Agente              │ Archivos                                 │
  ├─────────────────────┼──────────────────────────────────────────┤
  │ Sherris             │ Sherris - Microbiologia medica 6ta.txt   │
  │ Murray              │ Microbiología Médica 8a Edición.txt      │
  │ Mandell             │ Enfermedades Infecciosas.txt             │
  │ Libros              │ Jawetz, Romero, Tortora, Nerea, etc.     │
  │ Clases              │ CLASE BACTERIAS *.txt                    │
  │ Complementario      │ Otros/*.txt + Articulos/*.txt            │
  └─────────────────────┴──────────────────────────────────────────┘

EJECUCIÓN: Todos los grupos corren en PARALELO (asyncio.gather) para maximizar
           el uso del plan de API dentro de los límites de rate limiting.

SALIDA: Diccionario {nombre_fuente: texto_extraído} + archivos en cache/bacteria/
"""

import asyncio
import re
from pathlib import Path
from core.file_loader import SourceLoader
from core.api_client import APIClient
from core.logger import get_logger
from prompts.extraction import (
    EXTRACTION_SYSTEM_PROMPT,
    EXAM_EXTRACTION_SYSTEM_PROMPT,
    build_extraction_user_message,
    build_exam_extraction_user_message,
)
import config

log = get_logger(__name__)


async def run_phase1(
    entity_name: str,
    api_client: APIClient,
) -> dict[str, str]:
    """
    Ejecuta la Fase 1 completa: extrae información de todas las fuentes en paralelo.

    Args:
        entity_name: Nombre de la entidad a analizar
        api_client:    Instancia compartida del cliente de API

    Returns:
        Diccionario con los resultados de extracción por grupo de fuente.
        Ejemplo: {"Sherris": "texto...", "Murray": "texto...", ...}
        Los grupos sin información retornan "FUENTE_SIN_INFORMACIÓN_RELEVANTE".
    """
    log.info(f"[FASE 1] Iniciando extracción paralela para: {entity_name}")

    loader = SourceLoader()
    source_groups = loader.get_source_groups()

    # Crear el directorio de caché para esta entidad
    # El nombre de carpeta sanitiza caracteres especiales del nombre
    safe_name = _sanitize_filename(entity_name)
    cache_dir = config.CACHE_DIR / safe_name
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Crear tareas asíncronas: una por cada grupo de fuentes
    tasks = []
    group_names = []

    for group_name, files in source_groups.items():
        if not files:
            log.debug(f"[FASE 1] Grupo '{group_name}' vacío, omitiendo")
            continue

        tasks.append(
            _extract_group(
                entity_name=entity_name,
                group_name=group_name,
                files=files,
                loader=loader,
                api_client=api_client,
                cache_dir=cache_dir,
            )
        )
        group_names.append(group_name)

    # Ejecutar todas las extracciones EN PARALELO
    # asyncio.gather espera a que TODAS terminen antes de continuar
    log.info(f"[FASE 1] Lanzando {len(tasks)} agentes de extracción en paralelo...")
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Construir diccionario de resultados
    extractions: dict[str, str] = {}
    for group_name, result in zip(group_names, results):
        if isinstance(result, Exception):
            log.error(f"[FASE 1] Error en grupo '{group_name}': {result}")
            extractions[group_name] = "FUENTE_SIN_INFORMACIÓN_RELEVANTE"
        else:
            extractions[group_name] = result
            status = "✓ Con datos" if "FUENTE_SIN_INFORMACIÓN_RELEVANTE" not in result else "— Sin datos"
            log.info(f"[FASE 1] {group_name}: {status}")

    log.info(f"[FASE 1] Extracción completa. {sum(1 for v in extractions.values() if 'SIN_INFORMACIÓN' not in v)} fuentes con datos.")
    return extractions


async def _extract_group(
    entity_name: str,
    group_name: str,
    files: list[Path],
    loader: SourceLoader,
    api_client: APIClient,
    cache_dir: Path,
) -> str:
    """
    Extrae información de un grupo de fuentes y llama a la API.

    Primero verifica si ya existe una versión en caché para no repetir la llamada.
    """
    # ── Verificar caché ──────────────────────────────────────────────────────
    cache_file = cache_dir / f"{_sanitize_filename(group_name)}_extract.md"
    if cache_file.exists() and config.KEEP_INTERMEDIATE_FILES:
        log.info(f"[FASE 1] '{group_name}' → Usando caché: {cache_file.name}")
        return cache_file.read_text(encoding="utf-8")

    # ── Extracción local (sin API) ───────────────────────────────────────────
    # Buscar el texto relevante en los archivos .txt localmente
    # Grupos de transcripciones (clases, asesorías, exámenes) necesitan búsqueda
    # más flexible porque usan lenguaje coloquial, nombres abreviados y errores fonéticos
    is_transcript = any(kw in group_name for kw in [
        "Clases", "Asesorias", "asesorias", "Examenes", "Otros"
    ])
    
    if len(files) == 1:
        local_text = loader.extract_relevant_text(entity_name, files[0], is_transcript=is_transcript)
        source_label = files[0].stem  # Nombre del archivo sin extensión
    else:
        local_text = loader.extract_from_group(entity_name, files, is_transcript=is_transcript)
        source_label = group_name

    # Si no hay texto relevante local, no tiene sentido llamar a la API
    if not local_text or "FUENTE_SIN_INFORMACIÓN_RELEVANTE" in str(local_text):
        result = "FUENTE_SIN_INFORMACIÓN_RELEVANTE"
        if config.KEEP_INTERMEDIATE_FILES:
            cache_file.write_text(result, encoding="utf-8")
        return result

    # ── Llamada a la API (con soporte para fragmentación) ────────────────────
    chunk_size = config.MAX_CHARS_PER_SOURCE
    text_chunks = [local_text[i:i + chunk_size] for i in range(0, len(local_text), chunk_size)]
    
    if len(text_chunks) > 1:
        log.info(f"[FASE 1] '{group_name}' excede el límite de API. Dividiendo en {len(text_chunks)} llamadas paralelas.")
        
    # Seleccionar prompt según tipo de fuente
    # Los exámenes usan un prompt especializado que captura referencias contextuales
    is_exam_group = "Examenes" in group_name
    system_prompt = EXAM_EXTRACTION_SYSTEM_PROMPT if is_exam_group else EXTRACTION_SYSTEM_PROMPT
    build_message_fn = build_exam_extraction_user_message if is_exam_group else build_extraction_user_message

    api_tasks = []
    for idx, chunk in enumerate(text_chunks):
        user_message = build_message_fn(
            entity_name=entity_name,
            source_name=source_label + (f" (Parte {idx+1})" if len(text_chunks) > 1 else ""),
            source_text=chunk,
        )
        api_tasks.append(
            api_client.chat(
                system_prompt=system_prompt,
                user_message=user_message,
                label=f"Fase1/{group_name}" + (f" p{idx+1}" if len(text_chunks) > 1 else ""),
            )
        )
        
    # Ejecutar llamadas en paralelo para este grupo
    chunk_results = await asyncio.gather(*api_tasks)
    
    valid_results = []
    for res in chunk_results:
        if res:
            res_clean = re.sub(r'<think>.*?</think>', '', res, flags=re.DOTALL).strip()
            
            # Condición de rechazo: si el texto es muy corto y contiene la frase clave
            is_rejected = False
            if "FUENTE_SIN_INFORMACIÓN_RELEVANTE" in res_clean:
                if len(res_clean) < 150: # Si solo respondió la frase clave o un par de palabras extra
                    is_rejected = True
                    
            if not is_rejected and len(res_clean) > 20:
                valid_results.append(res_clean)
            else:
                log.debug(f"[FASE 1] Fragmento descartado. Longitud {len(res_clean)} chars. Contenido: {res_clean[:100]}...")
                
    if not valid_results:
        result = "FUENTE_SIN_INFORMACIÓN_RELEVANTE"
    else:
        result = "\n\n---\n\n".join(valid_results)
    
    # ── Guardar en caché ─────────────────────────────────────────────────────
    if config.KEEP_INTERMEDIATE_FILES:
        cache_file.write_text(result, encoding="utf-8")
        log.debug(f"[FASE 1] Caché guardado: {cache_file}")

    return result


def _sanitize_filename(name: str) -> str:
    """
    Convierte un nombre de bacteria o grupo en un nombre de archivo válido.
    Ejemplo: "Staphylococcus aureus" → "Staphylococcus_aureus"
    """
    import re
    return re.sub(r'[^\w\-.]', '_', name).strip('_')
