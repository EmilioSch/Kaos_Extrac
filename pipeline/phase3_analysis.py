"""
pipeline/phase3_analysis.py — Fase 3: Análisis con 7 Módulos
============================================================
PROPÓSITO: Ejecuta los 7 módulos de análisis usando el sistema de
           LÍNEAS DE PENSAMIENTO para mayor calidad y profundidad.

MÓDULOS:
  ┌────┬──────────────────────┐
  │ I  │ Etiología            │
  │ II │ Epidemiología        │
  │ III│ Factores Virulencia  │
  │ IV │ Cronología Patogénica│
  │ V  │ Fisiopatogenia       │
  │ VI │ Diagnóstico          │
  │ VII│ Tratamiento          │
  └────┴──────────────────────┘

SISTEMA DE LÍNEAS DE PENSAMIENTO:
  Cada módulo se analiza desde 4 perspectivas:
  1. CLÍNICA   - Perspectivo infectólogo (30% peso)
  2. MOLECULAR - Perspectiva microbiólogo molecular (30% peso)
  3. EXAMEN    - Perspectiva professor/exam designer (25% peso)
  4. FUSIÓN    - Síntesis final editorial (15% peso)

EJECUCIÓN: asyncio.gather lanza los 7 módulos simultáneamente.
           Las 4 líneas de cada módulo corren en paralelo interno.
           El rate limiter de APIClient garantiza no exceder límites.
"""

import asyncio
import re
from core.api_client import APIClient
from core.logger import get_logger
from prompts.modules import MODULES, build_module_message
from prompts.system import PROTOCOLO_ARQUITECTO_V3
from prompts.thinking_lines import run_thinking_lines
import config

log = get_logger(__name__)

# Flag para activar/desactivar sistema de líneas de pensamiento
USE_THINKING_LINES = getattr(config, 'USE_THINKING_LINES', True)


async def run_phase3(
    entity_name: str,
    master_text: str,
    api_client: APIClient,
) -> dict[int, str]:
    """
    Ejecuta los 7 módulos de análisis en paralelo sobre el master document.

    Args:
        entity_name: Nombre de la entidad
        master_text:   Contenido del master document (salida de Fase 2)
        api_client:    Instancia compartida del cliente de API

    Returns:
        Diccionario {id_módulo: texto_análisis}
        Ejemplo: {1: "# MÓDULO I...", 2: "# MÓDULO II...", ...}
    """
    log.info(f"[FASE 3] Iniciando análisis paralelo — {len(MODULES)} módulos para: {entity_name}")

    # Crear directorio de caché para módulos
    safe_name = _sanitize_filename(entity_name)
    modules_cache_dir = config.CACHE_DIR / safe_name / "modulos"
    modules_cache_dir.mkdir(parents=True, exist_ok=True)

    # Crear una tarea asíncrona por cada módulo
    tasks = [
        _run_single_module(
            entity_name=entity_name,
            master_text=master_text,
            module_id=mod_id,
            module_name=mod_name,
            module_prompt=mod_prompt,
            api_client=api_client,
            cache_dir=modules_cache_dir,
        )
        for mod_id, mod_name, mod_prompt in MODULES
    ]

    # Ejecutar todos en paralelo y esperar resultados
    log.info(f"[FASE 3] Lanzando {len(tasks)} módulos en paralelo...")
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Construir diccionario de resultados
    results: dict[int, str] = {}
    for (mod_id, mod_name, _), result in zip(MODULES, raw_results):
        if isinstance(result, Exception):
            log.error(f"[FASE 3] Error en Módulo {mod_id} ({mod_name}): {result}")
            results[mod_id] = f"## MÓDULO {mod_id}: {mod_name.upper()}\n\n> ⚠️ Error durante el análisis."
        else:
            results[mod_id] = result
            log.info(f"[FASE 3] Módulo {mod_id} ({mod_name}): ✓")

    log.info(f"[FASE 3] ✓ Análisis completo. {len(results)}/7 módulos generados.")
    if cache_dir is not None and config.KEEP_INTERMEDIATE_FILES:
        cache_file = cache_dir / f"modulo_{module_id:02d}_{_sanitize_filename(module_name)}.md"
        cache_file.write_text(result, encoding="utf-8")
        
    return results


async def run_phase3(
    entity_name: str,
    master_text: str,
    api_client: APIClient,
) -> dict[int, str]:
    """
    Ejecuta los 7 módulos de análisis en paralelo sobre el master document.

    Args:
        entity_name: Nombre de la entidad
        master_text:   Contenido del master document (salida de Fase 2)
        api_client:    Instancia compartida del cliente de API

    Returns:
        Diccionario {id_módulo: texto_análisis}
        Ejemplo: {1: "# MÓDULO I...", 2: "# MÓDULO II...", ...}
    """
    log.info(f"[FASE 3] Iniciando análisis — {len(MODULES)} módulos para: {entity_name}")
    log.info(f"[FASE 3] Sistema de Líneas de Pensamiento: {'ACTIVADO' if USE_THINKING_LINES else 'DESACTIVADO'}")

    # Crear directorio de caché para módulos
    safe_name = _sanitize_filename(entity_name)
    modules_cache_dir = config.CACHE_DIR / safe_name / "modulos"
    modules_cache_dir.mkdir(parents=True, exist_ok=True)

    # Crear una tarea asíncrona por cada módulo
    tasks = [
        _run_single_module(
            entity_name=entity_name,
            master_text=master_text,
            module_id=mod_id,
            module_name=mod_name,
            module_prompt=mod_prompt,
            api_client=api_client,
            cache_dir=modules_cache_dir,
        )
        for mod_id, mod_name, mod_prompt in MODULES
    ]

    # Ejecutar todos en paralelo y esperar resultados
    log.info(f"[FASE 3] Lanzando {len(tasks)} módulos en paralelo...")
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Construir diccionario de resultados
    results: dict[int, str] = {}
    for (mod_id, mod_name, _), result in zip(MODULES, raw_results):
        if isinstance(result, Exception):
            log.error(f"[FASE 3] Error en Módulo {mod_id} ({mod_name}): {result}")
            results[mod_id] = f"## MÓDULO {mod_id}: {mod_name.upper()}\n\n> ⚠️ Error durante el análisis."
        else:
            results[mod_id] = result
            log.info(f"[FASE 3] Módulo {mod_id} ({mod_name}): ✓")

    log.info(f"[FASE 3] ✓ Análisis completo. {len(results)}/7 módulos generados.")
    return results


async def _run_single_module(
    entity_name: str,
    master_text: str,
    module_id: int,
    module_name: str,
    module_prompt: str,
    api_client: APIClient,
    cache_dir,
) -> str:
    """
    Ejecuta un único módulo de análisis con la API.
    Soporta el sistema de LÍNEAS DE PENSAMIENTO para mayor calidad.
    Verifica caché antes de llamar a la API.
    """
    # ── Verificar caché del módulo ───────────────────────────────────────────
    cache_file = cache_dir / f"modulo_{module_id:02d}_{_sanitize_filename(module_name)}.md"
    if cache_file.exists() and config.KEEP_INTERMEDIATE_FILES:
        log.info(f"[FASE 3] Módulo {module_id} — Usando caché")
        return cache_file.read_text(encoding="utf-8")

    # ── Sistema de Líneas de Pensamiento (MEJORA) ────────────────────────────
    if USE_THINKING_LINES:
        log.info(f"[FASE 3] Módulo {module_id} — Ejecutando sistema de 4 líneas de pensamiento...")
        
        result = await _run_with_thinking_lines(
            entity_name=entity_name,
            master_text=master_text,
            module_id=module_id,
            module_name=module_name,
            module_prompt=module_prompt,
            api_client=api_client,
        )
        
        if config.KEEP_INTERMEDIATE_FILES:
            cache_file.write_text(result, encoding="utf-8")
        
        return result

    # ── Método original (sin líneas de pensamiento) ───────────────────────────
    return await _run_single_module_original(
        entity_name=entity_name,
        master_text=master_text,
        module_id=module_id,
        module_name=module_name,
        module_prompt=module_prompt,
        api_client=api_client,
        cache_dir=cache_dir,
    )


async def _run_with_thinking_lines(
    entity_name: str,
    master_text: str,
    module_id: int,
    module_name: str,
    module_prompt: str,
    api_client: APIClient,
) -> str:
    """
    Ejecuta el módulo usando el sistema de líneas de pensamiento.
    Las 4 líneas (clínica, molecular, examen, fusión) corren en paralelo
    y el resultado final es la fusión de las 3 perspectivas.
    """
    # Preparar contexto del módulo para las líneas
    module_context = f'Módulo {module_id}'
    
    # Preparar el prompt base del módulo para dar contexto temático
    # Las líneas usarán master_text directamente
    module_theme = module_prompt[:500]  # Primeros 500 chars del prompt como tema
    
    # Ejecutar las 4 líneas en paralelo
    log.info(f"[FASE 3] M{module_id} ({module_name}): 4 líneas en paralelo...")
    
    line_results = await run_thinking_lines(
        entity_name=entity_name,
        master_text=master_text,
        module_id=module_id,
        module_prompt=module_theme,
        api_client=api_client,
        module_context=module_context,
    )
    
    # Verificar si alguna línea falló
    failed_lines = [lid for lid, content in line_results.items() if content.startswith("[ERROR")]
    
    if failed_lines:
        log.warning(f"[FASE 3] M{module_id}: Líneas fallidas: {failed_lines}. Usando resultados disponibles.")
    
    # El resultado final es el contenido de la línea de FUSIÓN
    # que ya integra las 3 perspectivas
    fusion_result = line_results.get("fusion", "")
    
    if not fusion_result or fusion_result.startswith("[ERROR"):
        # Fallback: intentar usar el método original si la fusión falló
        log.error(f"[FASE 3] M{module_id}: Fusión falló. Ejecutando método original como fallback.")
        return await _run_single_module_original(
            entity_name=entity_name,
            master_text=master_text,
            module_id=module_id,
            module_name=module_name,
            module_prompt=module_prompt,
            api_client=api_client,
            cache_dir=None,
        )
    
    # Limpiar cualquier tag de fuente residual
    fusion_result = re.sub(r'\[Fuente:.*?\]', '', fusion_result)
    
    return fusion_result


async def _run_single_module_original(
    entity_name: str,
    master_text: str,
    module_id: int,
    module_name: str,
    module_prompt: str,
    api_client: APIClient,
    cache_dir,
) -> str:
    """
    Método original de ejecución de módulo (sin sistema de líneas).
    Mantenido como fallback y para cuando USE_THINKING_LINES=False.
    """

    # ── Fragmentación del master si es demasiado grande para la API ──────────
    # El master directo puede pesar 500KB+. Dividimos por fuente y llamamos en paralelo.
    MAX_CHARS_PER_CALL = config.MAX_CHARS_PER_SOURCE  # 120k chars por llamada
    
    if len(master_text) <= MAX_CHARS_PER_CALL:
        # Cabe en una sola llamada
        master_chunks = [master_text]
    else:
        # Dividir respetando los separadores de fuente "## FUENTE:"
        master_chunks = _split_master_by_source(master_text, MAX_CHARS_PER_CALL)
        log.info(f"[FASE 3] Módulo {module_id} ({module_name}): master dividido en {len(master_chunks)} fragmentos")

    # Llamadas paralelas: una por fragmento del master
    api_tasks = []
    for idx, chunk in enumerate(master_chunks):
        label_suffix = f" (fragmento {idx+1}/{len(master_chunks)})" if len(master_chunks) > 1 else ""
        user_message = build_module_message(
            entity_name=entity_name,
            master_text=chunk,
            module_prompt=module_prompt,
        )
        api_tasks.append(
            api_client.chat(
                system_prompt=PROTOCOLO_ARQUITECTO_V3,
                user_message=user_message,
                label=f"Fase3/Módulo{module_id}-{module_name}{label_suffix}",
            )
        )

    raw_results = await asyncio.gather(*api_tasks)

    # Si hay múltiples fragmentos, fusionarlos en una sola llamada final
    valid_parts = []
    for r in raw_results:
        if r:
            cleaned = re.sub(r'<think>.*?</think>', '', r, flags=re.DOTALL).strip()
            if cleaned:
                valid_parts.append(cleaned)

    if not valid_parts:
        result = (
            f"## MÓDULO {module_id}: {module_name.upper()}\n\n"
            f"> ⚠️ No se pudo generar el análisis (API no respondió)."
        )
    elif len(valid_parts) == 1:
        result = valid_parts[0]
    else:
        # Fusionar los resultados de múltiples fragmentos en una llamada extra
        merge_prompt = (
            f"Eres un editor médico. Se te entregan {len(valid_parts)} análisis parciales "
            f"del MÓDULO {module_id} ({module_name}) de {entity_name}, cada uno generado "
            f"desde un fragmento diferente de la bibliografía. "
            f"Tu tarea: fusiónalos en UN SOLO documento cohesivo, eliminando repeticiones "
            f"y manteniendo TODA la información clínica relevante. "
            f"Respeta el formato Markdown y HTML del original. No agregues introducción ni conclusión."
        )
        parts_text = "\n\n---FRAGMENTO SIGUIENTE---\n\n".join(valid_parts)
        merged = await api_client.chat(
            system_prompt=merge_prompt,
            user_message=parts_text,
            label=f"Fase3/Fusión/Módulo{module_id}-{module_name}",
        )
        result = merged if merged else "\n\n".join(valid_parts)

    # ── Corrección Gramatical y Formato ───────────────────────────────────
    grammar_system = (
        "Eres un editor médico experto. Tu única tarea es corregir errores de "
        "ortografía, gramática, caracteres extraños (ej. cirílicos) o errores de "
        "traducción al español en el siguiente texto.\n\n"
        "REGLAS CRÍTICAS:\n"
        "1. NO agregues, elimines ni resumas NINGUNA información médica o contenido.\n"
        "2. MANTÉN INTACTO el formato Markdown (títulos, listas, tablas, resaltados con HTML o Markdown).\n"
        "3. SOLO corrige la redacción y ortografía para que sea Español Médico Técnico perfecto.\n"
        "4. MUY IMPORTANTE: Tu respuesta debe contener ÚNICAMENTE el texto corregido. "
        "NO inicies con 'Aquí está el texto', ni 'Texto corregido', ni ninguna otra frase introductoria. "
        "DEBES devolver exactamente la misma estructura de Markdown que recibiste."
    )
    grammar_user = f"Corrige el siguiente texto generado manteniendo su estructura exacta. NO agregues introducciones:\n\n{result}"
    
    corrected = await api_client.chat(
        system_prompt=grammar_system,
        user_message=grammar_user,
        label=f"Fase3/Gramática/Módulo{module_id}-{module_name}",
    )
    if corrected:
        result = corrected

    # ── Forzar limpieza de referencias ───────────────────────────────────────
    # Por si el LLM ignoró la instrucción de no citar fuentes
    result = re.sub(r'\[Fuente:.*?\]', '', result)

    if cache_dir is not None and config.KEEP_INTERMEDIATE_FILES:
        cache_file = cache_dir / f"modulo_{module_id:02d}_{_sanitize_filename(module_name)}.md"
        cache_file.write_text(result, encoding="utf-8")
        
    return result


def _split_master_by_source(master_text: str, max_chars: int) -> list[str]:
    """
    Divide el master document en fragmentos respetando los separadores de fuente.
    Cada fragmento termina en el último separador '## FUENTE:' que cabe dentro
    del límite de caracteres, garantizando que no se corta en medio de una sección.
    Si una fuente individual supera max_chars, se incluye sola en su propio fragmento.
    """
    separator = "\n" + "=" * 70 + "\n## FUENTE:"
    # Dividir por separadores de fuente
    parts = master_text.split("\n" + "=" * 70)
    
    chunks = []
    current_chunk = ""
    
    for part in parts:
        if not part.strip():
            continue
        candidate = (current_chunk + "\n" + "=" * 70 + part) if current_chunk else part
        if len(candidate) <= max_chars:
            current_chunk = candidate
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            # Si la parte sola excede el límite, la incluimos tal cual (será truncada por la API)
            current_chunk = part
    
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    return chunks if chunks else [master_text]


def _sanitize_filename(name: str) -> str:
    return re.sub(r'[^\w\-.]', '_', name).strip('_')
