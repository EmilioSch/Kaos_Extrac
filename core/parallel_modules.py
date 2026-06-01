"""
core/parallel_modules.py — Arquitectura de Secciones Paralelas para Módulos Virológicos
==========================================================================================
Cada módulo genera N secciones en paralelo → síntesis → QC offline.

Llamadas por módulo:
  6 secciones paralelas + 1 síntesis + 1 QC (solo si hay problemas) = 7-8 calls/módulo
  6 módulos × 8 = ~48 calls de módulos (vs 6 actuales)

PubMed:
  Búsqueda siempre en inglés + 1 call individual por artículo + 1 síntesis global
"""

import asyncio
import re
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.api_client import APIClient

# ══════════════════════════════════════════════════════════════════════════════
# DEFINICIÓN DE SECCIONES POR MÓDULO
# Cada sección es (id, directiva_focalizada)
# ══════════════════════════════════════════════════════════════════════════════
MODULE_SECTIONS: dict[int, list[tuple[str, str]]] = {

    1: [  # ARQUITECTURA VIRAL
        ("TAX", "Clasificación taxonómica completa (ICTV): Familia, Género, Especie, subtipos/genotipos. Posición exacta en Baltimore (I-VII). Nombre científico vs. nombres comunes regionales."),
        ("GEN", "Genoma: tipo (DNA/RNA), polaridad (+/-/dsRNA/dsDNA), segmentación (número de segmentos y sus nombres), tamaño en kb. Regiones no codificantes (5'UTR, 3'UTR, IRES si aplica). Capacidad de codificación."),
        ("PRO", "Proteínas estructurales: nombre exacto, gen codificante, peso molecular, función molecular precisa. Incluye cápside, nucleocápside, proteína de matriz, tegumento si aplica."),
        ("NSP", "Proteínas NO estructurales: nombre, gen, función en el ciclo replicativo y evasión inmune. Por qué son dianas terapéuticas. Incluir tabla con todas las NSP y sus funciones."),
        ("ENV", "Envoltura viral (si existe): composición lipídica, origen (membrana plasmática / RE / Golgi / nuclear), glicoproteínas con función de unión-fusión y determinantes de tropismo."),
        ("UNI", "Particularidades únicas de {ENTITY} dentro de su familia. Comparación con miembros relacionados. Características que lo hacen clínicamente especial."),
    ],

    2: [  # CICLO DE REPLICACIÓN
        ("ADS", "Adsorción: receptor(es) primario(s) con nombre molecular exacto (CD4, ACE2, ácido siálico, etc.). Correceptores. Cómo el virus reconoce específicamente su receptor y qué determina el tropismo."),
        ("PEN", "Penetración y desnudamiento: mecanismo exacto (fusión directa pH-neutro vs. endocitosis + fusión pH-ácido). Cambio conformacional de glicoproteína de fusión. Tráfico intracelular al sitio replicativo."),
        ("TRX", "Transcripción y traducción: estrategia (cap-snatching, IRES, splicing, poliproteína). Polimerasa usada (viral o celular). Orden de expresión genes IE/E/L. Cómo el virus secuestra la maquinaria celular."),
        ("REP", "Replicación del genoma: mecanismo enzimático paso a paso. Intermediario replicativo (RF, dsRNA, etc.). Error rate, cuasiespecies. Compartimento celular (cuerpos de replicación, inclusions)."),
        ("ENS", "Ensamblaje y maduración: sitio de nucleocapsidación. Incorporación selectiva del genoma. Adquisición de envoltura. Proteasa viral/celular en maduración. Brotación."),
        ("EGR", "Egreso y destino celular: mecanismo (lisis / brotación continua / exocitosis). CLASIFICACIÓN OBLIGATORIA: CICLO LÍTICO vs. LISOGÉNICO/LATENCIA con justificación. Gatillo molecular de reactivación si aplica."),
    ],

    3: [  # PATOGENIA
        ("FIS", "FISIOLOGÍA BASAL DEL TEJIDO DIANA: identificar órgano/célula diana de {ENTITY}. Describir en 3 párrafos sus funciones homeostáticas normales. Qué procesos moleculares específicos serán interrumpidos y cómo eso produce la clínica."),
        ("DIS", "Diseminación: desde puerta de entrada hasta órgano diana. Viremia primaria, barreras, viremia secundaria. Diseminación neural retrógrada/anterógrada. Mecanismo 'caballo de Troya' si aplica."),
        ("CPE", "Efectos citopáticos directos: inhibición síntesis proteica celular, lisis, formación de sincitios, cuerpos de inclusión patognomónicos, apoptosis inducida (vía intrínseca vs. extrínseca)."),
        ("IND", "Daño indirecto: infiltrado inflamatorio (tipos celulares, quimiocinas), citocinas proinflamatorias (TNF-α, IL-6, IFN), daño por hipoxia, daño colateral. Diferencia daño viral vs. daño inmunológico."),
        ("CLI", "Correlación fisiopatológica-clínica: cada síntoma/signo explicado por el mecanismo patogénico correspondiente. La clínica como consecuencia lógica de la fisiología alterada."),
        ("LAT", "Latencia o persistencia (si aplica): tipo (episomal/proviral), células reservorio, genes LAT, mecanismo reactivación. Si no aplica, describir persistencia crónica o clearance completo."),
        ("ONC", "Oncogénesis (si aplica): mecanismo (inserción proviral, transactivación, E6/E7, LMP1, etc.), oncoproteínas clave, tumores asociados, epidemiología del cáncer viral. Si no aplica, indicarlo."),
    ],

    4: [  # INMUNOLOGÍA
        ("INN", "Respuesta innata: PRRs activados (TLRs específicos, RIG-I, MDA5, cGAS-STING según el virus). Cascada IFN tipo I/III. Células NK (reconocimiento, mecanismo kill). Inflamasoma. Cinética temporal."),
        ("HUM", "Respuesta humoral: anticuerpos neutralizantes (diana, mecanismo, isotipos, cinética IgM→IgG). Anticuerpos no neutralizantes. Seroconversión. Memoria B de larga duración. Uso diagnóstico."),
        ("CEL", "Respuesta celular: CD8+ (péptidos MHC-I presentados, mecanismo citotóxico, expansión clonal). CD4+ (Th1/Th2/Th17, citocinas). Memoria T. Papel en control de infección aguda y latente."),
        ("EVA", "Evasión inmune: mecanismos moleculares con el gen viral responsable. Inhibición IFN, bloqueo presentación MHC-I/II, protección de NK, mimetismo molecular. Tabla: mecanismo → proteína viral."),
        ("PAT", "Inmunopatología: cómo la respuesta inmune causa daño (tormenta de citocinas, autoinmunidad, formación de inmunocomplejos, IRIS). Ejemplos clínicos concretos con correlato molecular."),
        ("VAC", "Base inmunológica de vacunación: qué inmunidad genera la vacuna (humoral/celular). Antígenos diana. Correlatos de protección. Duración. Por qué funciona o por qué es difícil (p.e. VIH, VHC)."),
    ],

    5: [  # DIAGNÓSTICO Y TRATAMIENTO
        ("PRE", "Pre-analítica: muestra de elección según fase (aguda/convaleciente/latente). Condiciones de toma, transporte, conservación. Ventana diagnóstica por método. Errores frecuentes pre-analíticos."),
        ("DIR", "Métodos directos: PCR/RT-PCR (gen diana, sensibilidad, especificidad, tiempo). Antígeno (ELISA, IF, inmunocromatografía). Cultivo celular (líneas, CPE). Microscopía electrónica. Tabla comparativa."),
        ("SER", "Serología: IgM (días de aparición, significado, limitaciones). IgG (seroconversión, correlato de protección). Western Blot (cuándo confirmar). PRNT. Interpretación de patrones serológicos."),
        ("SOP", "Tratamiento de soporte — JUSTIFICACIÓN FISIOLÓGICA OBLIGATORIA: qué función del tejido diana perdida se compensa y por qué tiene coherencia molecular. Vincular con la fisiología basal del Módulo III."),
        ("ANT", "Farmacología antiviral: tabla (fármaco / clase / diana molecular exacta = paso replicativo inhibido / uso clínico / resistencia documentada). Si no existe antiviral, qué se investiga y por qué es difícil."),
        ("PRV", "Prevención: vacuna (tipo, antígeno, esquema). IMPACTO EPIDEMIOLÓGICO con cifras reales (mortalidad reducida, erradicación, hospitalización evitada). Quimioprofilaxis pre/post-exposición. Control no farmacológico."),
    ],

    6: [  # CRONOLOGÍA PATOGÉNICA
        ("INC", "Período de incubación: duración (mínimo-máximo-promedio), factores modificadores (dosis inoculada, vía entrada, estado inmune, edad). Eventos moleculares durante la incubación silenciosa."),
        ("PRO", "Período prodrómico: síntomas inespecíficos iniciales y su base fisiopatológica. Carga viral, respuesta innata activa. Por qué el diagnóstico es difícil en esta fase."),
        ("AGU", "Fase aguda establecida: secuencia temporal de síntomas con correlato patogénico. Signos patognomónicos y su base molecular. Hallazgos de laboratorio esperados (viremia, marcadores inflamatorios)."),
        ("CRI", "Punto de bifurcación: cuándo y por qué algunos pacientes mejoran vs. empeoran. Factores del huésped (inmunogenética, comorbilidades) y del virus (carga, cuasiespecies) que determinan el desenlace."),
        ("RES", "Resolución: cómo el sistema inmune elimina el virus. Marcadores de clearance. Inmunidad post-infección (duración, protección cruzada). Secuelas tardías. Riesgo de reinfección y mecanismo."),
    ],
}

# ══════════════════════════════════════════════════════════════════════════════
# PROMPTS BASE
# ══════════════════════════════════════════════════════════════════════════════
_SECTION_SYSTEM = (
    "Eres Kaos, experto en virología molecular y clínica de nivel universitario avanzado. "
    "Generas UNA SECCIÓN ESPECÍFICA de un análisis virológico con máxima profundidad técnica. "
    "Narrativa médica técnica continua, sin introducción ni cierre. "
    "Cada párrafo denso en información molecular y clínica. "
    "PROHIBIDO listas genéricas. PROHIBIDO resumir. SOLO información técnica profunda."
)

_SYNTHESIS_SYSTEM = (
    "Eres Kaos-Synth, sintetizador maestro de virología clínica. "
    "Recibes secciones especializadas generadas en paralelo y las unificás en UN documento "
    "coherente de tratado médico universitario. "
    "OBLIGATORIO: conservar TODA la información técnica. Eliminar solo duplicaciones exactas. "
    "Mantener headers Markdown del template. Tablas perfectamente formateadas. "
    "Narrativa en Español Médico Técnico, sin bullets genéricos."
)

_QC_SYSTEM = (
    "Eres Kaos-QC, agente de control de calidad virológica. "
    "Corrige el módulo recibido: errores de codificación, tablas rotas, texto en inglés, "
    "información faltante. Devuelve el módulo COMPLETO corregido en Español Médico."
)


# ══════════════════════════════════════════════════════════════════════════════
# FUNCIONES PRINCIPALES
# ══════════════════════════════════════════════════════════════════════════════

async def generate_section(
    client: "APIClient",
    virus_name: str,
    master: str,
    mod_id: int,
    mod_name: str,
    section_id: str,
    directive: str,
) -> tuple[str, str]:
    """Genera una sección focalizada de un módulo."""
    directive = directive.replace("{ENTITY}", virus_name)

    user_msg = (
        f"VIRUS: {virus_name}\n"
        f"MÓDULO: {mod_id} — {mod_name}\n"
        f"SECCIÓN: {section_id}\n\n"
        f"DIRECTIVA DE ESTA SECCIÓN:\n{directive}\n\n"
        f"FUENTES DISPONIBLES:\n<master_context>\n{master[:100_000]}\n</master_context>\n\n"
        f"Genera esta sección con máxima profundidad técnica. "
        f"Mínimo 600 palabras de contenido clínico-molecular real."
    )

    resp, tokens = await client.chat(
        system_prompt=_SECTION_SYSTEM,
        user_message=user_msg,
        label=f"M{mod_id}-{section_id}/{virus_name}",
        use_deepseek=False,
        return_tokens=True,
    )
    if resp:
        clean = re.sub(r"<think>.*?</think>", "", resp, flags=re.DOTALL).strip()
        return section_id, clean, tokens
    return section_id, "", tokens


async def synthesize_module(
    client: "APIClient",
    virus_name: str,
    mod_id: int,
    mod_name: str,
    sections: list[tuple[str, str]],
    module_template: str,
) -> str:
    """Sintetiza todas las secciones paralelas en un módulo coherente."""
    sections_text = ""
    for sec_id, content in sections:
        if content:
            sections_text += f"\n\n═══ SECCIÓN {sec_id} ═══\n{content[:7_000]}\n"

    user_msg = (
        f"VIRUS: {virus_name}\n"
        f"MÓDULO: {mod_id} — {mod_name}\n\n"
        f"Has recibido {len([s for s in sections if s[1]])} secciones especializadas:\n"
        f"{sections_text}\n\n"
        f"ESTRUCTURA REQUERIDA DEL MÓDULO (respeta estos headers):\n"
        f"{module_template[:4_000]}\n\n"
        f"REGLAS:\n"
        f"1. Conservar TODA información técnica de TODAS las secciones\n"
        f"2. Eliminar solo duplicaciones exactas\n"
        f"3. Narrativa continua en Español Médico Técnico\n"
        f"4. Mantener headers del template\n"
        f"5. Tablas Markdown perfectas\n"
        f"6. Sin texto introductorio ni de cierre"
    )

    resp, tokens = await client.chat(
        system_prompt=_SYNTHESIS_SYSTEM,
        user_message=user_msg,
        label=f"M{mod_id}-SYNTH/{virus_name}",
        use_deepseek=False,
        return_tokens=True,
    )
    if resp:
        return re.sub(r"<think>.*?</think>", "", resp, flags=re.DOTALL).strip(), tokens
    return "", tokens


def qc_offline(content: str) -> dict:
    """
    Control de calidad sin API — detecta problemas comunes.
    Retorna dict con issues encontrados.
    """
    issues = {}

    # Codificación corrupta
    encoding_artifacts = [
        (r"â€[™\"'`]", "UTF-8 decoded as Latin-1"),
        (r"Ã[¡éíóúñ¿]", "Spanish chars corrupted"),
        (r"\uFFFD", "Replacement character"),
        (r"&#\d+;", "HTML entities not decoded"),
    ]
    enc_found = [desc for pat, desc in encoding_artifacts if re.search(pat, content)]
    if enc_found:
        issues["encoding"] = enc_found

    # Tablas rotas: filas con distinto número de columnas
    table_rows = re.findall(r"^\|.+\|$", content, re.MULTILINE)
    if table_rows:
        col_counts = [row.count("|") for row in table_rows]
        if len(set(col_counts)) > 2:  # > 2 porque header + separator tienen el mismo count
            issues["tables"] = f"Columnas inconsistentes: {set(col_counts)}"

    # Idioma: texto en inglés dominante
    english_words = ["the ", "this ", "with ", "from ", "have ", "their ", "that "]
    spanish_words = ["que ", "con ", "por ", "para ", "una ", "los ", "del ", "las "]
    en = sum(content.lower().count(w) for w in english_words)
    es = sum(content.lower().count(w) for w in spanish_words)
    if en > es * 1.5:
        issues["language"] = f"Inglés dominante (en={en}, es={es})"

    # Secciones vacías (headers sin contenido)
    empty_sections = re.findall(r"#{2,4} .+\n{1,2}(?=#{2,4}|\Z)", content)
    if empty_sections:
        issues["empty_sections"] = len(empty_sections)

    return issues


async def qc_api_fix(
    client: "APIClient",
    virus_name: str,
    mod_id: int,
    mod_name: str,
    content: str,
    issues: dict,
) -> str:
    """Si hay problemas graves, llama a la API para corrección."""
    issues_str = "\n".join(f"- {k}: {v}" for k, v in issues.items())
    user_msg = (
        f"VIRUS: {virus_name} — Módulo {mod_id} {mod_name}\n\n"
        f"PROBLEMAS DETECTADOS QUE DEBES CORREGIR:\n{issues_str}\n\n"
        f"MÓDULO A CORREGIR:\n{content[:60_000]}\n\n"
        f"Devuelve el módulo COMPLETO y CORREGIDO. Sin texto adicional."
    )
    resp, tokens = await client.chat(
        system_prompt=_QC_SYSTEM,
        user_message=user_msg,
        label=f"M{mod_id}-QC/{virus_name}",
        use_deepseek=False,
        return_tokens=True,
    )
    if resp:
        return re.sub(r"<think>.*?</think>", "", resp, flags=re.DOTALL).strip(), tokens
    return content, tokens  # Devolver original si falla la corrección


async def run_module_parallel(
    client: "APIClient",
    virus_name: str,
    master: str,
    module_entry: tuple,
) -> tuple[int, str, str, bool, int]:
    """
    Reemplaza run_module() con arquitectura de secciones paralelas:
      1. N secciones en paralelo (según MODULE_SECTIONS)
      2. Síntesis unificada
      3. QC offline + corrección API si hay problemas

    Returns: (mod_id, mod_name, content, use_deepseek, tokens_approx)
    """
    mod_id, mod_name, mod_prompt, use_deepseek = module_entry
    sections_def = MODULE_SECTIONS.get(mod_id, [])

    print(f"  [M{mod_id}] {mod_name}: lanzando {len(sections_def)} secciones paralelas...")

    # ── Paso 1: Generar secciones en paralelo ────────────────────────────────
    section_tasks = [
        generate_section(client, virus_name, master, mod_id, mod_name, sid, directive)
        for sid, directive in sections_def
    ]
    section_results: list[tuple[str, str, int]] = await asyncio.gather(*section_tasks)
    
    sections_for_synth = [(sid, c) for sid, c, _ in section_results]
    total_tokens = sum(t for _, _, t in section_results)
    
    filled = sum(1 for _, c in sections_for_synth if c)
    print(f"  [M{mod_id}] {filled}/{len(sections_def)} secciones completadas → sintetizando...")

    # ── Paso 2: Síntesis ─────────────────────────────────────────────────────
    synthesis, synth_tokens = await synthesize_module(
        client, virus_name, mod_id, mod_name, sections_for_synth, mod_prompt
    )
    total_tokens += synth_tokens

    if not synthesis:
        # Fallback: concatenar secciones directamente
        synthesis = "\n\n---\n\n".join(c for _, c in sections_for_synth if c)

    # ── Paso 3: QC offline ───────────────────────────────────────────────────
    issues = qc_offline(synthesis)
    if issues:
        critical = [k for k in issues if k in ("encoding", "language")]
        if critical:
            print(f"  [M{mod_id}] ⚠ QC issues: {list(issues.keys())} — corrigiendo con API...")
            synthesis, qc_tokens = await qc_api_fix(client, virus_name, mod_id, mod_name, synthesis, issues)
            total_tokens += qc_tokens
        else:
            print(f"  [M{mod_id}] ⚠ QC minor issues: {list(issues.keys())} — aceptado")
    else:
        print(f"  [M{mod_id}] ✓ QC OK")

    return mod_id, mod_name, synthesis, use_deepseek, total_tokens


# ══════════════════════════════════════════════════════════════════════════════
# PUBMED: búsqueda en inglés + análisis individual por artículo
# ══════════════════════════════════════════════════════════════════════════════

# Mapa de nombres en español → inglés para la búsqueda PubMed
PUBMED_ENGLISH_MAP = {
    "rabia":           "Rabies virus",
    "gripe":           "Influenza virus",
    "influenza":       "Influenza virus",
    "varicela":        "Varicella zoster virus",
    "sarampión":       "Measles virus",
    "paperas":         "Mumps virus",
    "parotiditis":     "Mumps virus",
    "rubeola":         "Rubella virus",
    "rubéola":         "Rubella virus",
    "hepatitis a":     "Hepatitis A virus",
    "hepatitis b":     "Hepatitis B virus",
    "hepatitis c":     "Hepatitis C virus",
    "hepatitis e":     "Hepatitis E virus",
    "vih":             "HIV Human immunodeficiency virus",
    "vhs":             "Herpes simplex virus",
    "herpes simple":   "Herpes simplex virus",
    "herpes zóster":   "Varicella zoster virus reactivation",
    "citomegalovirus": "Cytomegalovirus CMV",
    "epstein-barr":    "Epstein-Barr virus EBV",
    "dengue":          "Dengue virus",
    "zika":            "Zika virus",
    "ebola":           "Ebola virus",
    "sars-cov-2":      "SARS-CoV-2 COVID-19",
    "coronavirus":     "Coronavirus",
    "rotavirus":       "Rotavirus",
    "poliovirus":      "Poliovirus",
    "parvovirus":      "Parvovirus B19",
    "adenovirus":      "Adenovirus",
    "norovirus":       "Norovirus",
    "enterovirus":     "Enterovirus",
    "arenavirus":      "Arenavirus",
    "hantavirus":      "Hantavirus",
    "chikungunya":     "Chikungunya virus",
    "rhinovirus":      "Rhinovirus",
    "sincicial":       "Respiratory syncytial virus",
    "sincitial":       "Respiratory syncytial virus",
    "hvh-6":           "Human herpesvirus 6",
    "hvh-7":           "Human herpesvirus 7",
}


def get_pubmed_english_name(virus_name: str) -> str:
    """Devuelve el nombre en inglés para búsqueda en PubMed."""
    name_lower = virus_name.lower().strip()
    for key, english in PUBMED_ENGLISH_MAP.items():
        if key in name_lower:
            return english
    # Si no hay mapa, usar el nombre original (ya puede estar en inglés)
    return virus_name


_ARTICLE_SYSTEM = (
    "Eres Kaos, experto en virología clínica. "
    "Analizas un artículo científico de PubMed y extraes los hallazgos más relevantes "
    "en términos clínicos, moleculares y epidemiológicos. "
    "Escribe en Español Médico Técnico, narrativa continua, máximo 400 palabras. "
    "Cita el artículo como [PMID: XXXX] al final de cada hallazgo relevante."
)

_PUBMED_SYNTHESIS_SYSTEM = (
    "Eres Kaos-Synth, sintetizador de literatura científica virológica. "
    "Recibes análisis individuales de artículos PubMed y los integras en UNA sección "
    "de 'Literatura Científica Reciente' de tratado médico. "
    "Narrativa continua en Español Médico Técnico, sin listas. "
    "Cita artículos como [N] en el texto. Mínimo 4 párrafos."
)


async def analyze_single_article(
    client: "APIClient",
    virus_name: str,
    article: dict,
    article_num: int,
) -> str:
    """Analiza un artículo de PubMed individualmente con MiniMax."""
    abstract = article.get("abstract", "")[:2_000]
    title    = article.get("title", "")
    year     = article.get("year", "")
    journal  = article.get("journal", "")
    pmid     = article.get("pmid", "")

    user_msg = (
        f"Artículo [{article_num}] sobre {virus_name}:\n"
        f"Título: {title}\n"
        f"Revista: {journal} ({year}) | PMID: {pmid}\n\n"
        f"Abstract:\n{abstract}\n\n"
        f"Extrae y analiza los hallazgos más importantes de este artículo:\n"
        f"- Hallazgos moleculares o mecanísticos nuevos\n"
        f"- Datos epidemiológicos relevantes\n"
        f"- Avances terapéuticos o preventivos\n"
        f"- Implicaciones clínicas\n"
        f"Cita como [PMID: {pmid}] en el texto."
    )

    resp = await client.chat(
        system_prompt=_ARTICLE_SYSTEM,
        user_message=user_msg,
        label=f"PubMed-Art{article_num}/{virus_name}",
        use_deepseek=False,
    )
    if resp:
        return re.sub(r"<think>.*?</think>", "", resp, flags=re.DOTALL).strip()
    return ""


async def synthesize_pubmed_articles(
    client: "APIClient",
    virus_name: str,
    articles: list[dict],
    analyses: list[str],
) -> str:
    """Sintetiza los análisis individuales en una sección cohesiva."""
    analyses_text = ""
    for i, (art, analysis) in enumerate(zip(articles, analyses), 1):
        if analysis:
            analyses_text += f"\n[{i}] {art.get('title','')} ({art.get('year','')})\n{analysis}\n"

    user_msg = (
        f"Virus: {virus_name}\n\n"
        f"Análisis individuales de {len([a for a in analyses if a])} artículos PubMed:\n"
        f"{analyses_text}\n\n"
        f"## ACTUALIZACIÓN CIENTÍFICA — {virus_name.upper()} (Literatura 2017–2025)\n\n"
        f"### 1. AVANCES EN COMPRENSIÓN MOLECULAR Y PATOGÉNICA\n"
        f"### 2. ACTUALIZACIONES EPIDEMIOLÓGICAS Y CLÍNICAS\n"
        f"### 3. AVANCES TERAPÉUTICOS Y PREVENTIVOS\n"
        f"### 4. BRECHAS DE CONOCIMIENTO Y LÍNEAS DE INVESTIGACIÓN ACTIVA\n\n"
        f"Narrativa continua, sin listas. Cita artículos como [N]. Mínimo 2 párrafos por sección."
    )

    resp = await client.chat(
        system_prompt=_PUBMED_SYNTHESIS_SYSTEM,
        user_message=user_msg,
        label=f"PubMed-SYNTH/{virus_name}",
        use_deepseek=False,
    )
    if resp:
        return re.sub(r"<think>.*?</think>", "", resp, flags=re.DOTALL).strip()
    return ""
