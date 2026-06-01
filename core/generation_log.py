"""
core/generation_log.py — Generador de Bloque de Metadatos de Generación
========================================================================
PROPÓSITO: Produce un bloque HTML/Markdown estandarizado que documenta 
           los parámetros técnicos usados para generar cada documento.
           Compatible con el pipeline de bacterias y virología (Kaos).
"""

import datetime
from typing import Optional


# ── Catálogo de referencias APA por clave ────────────────────────────────────
APA_REFERENCES = {
    "fields": (
        "Knipe, D. M., & Howley, P. M. (Eds.). (2013). "
        "<em>Fields virology</em> (6th ed.). Lippincott Williams & Wilkins."
    ),
    "principles": (
        "Racaniello, V. R., Skalka, A. M., Flint, S. J., & Enquist, L. W. (2020). "
        "<em>Principles of virology</em> (5th ed.). ASM Press."
    ),
    "jawetz": (
        "Carroll, K. C., Butel, J. S., Morse, S. A., & Mietzner, T. (2019). "
        "<em>Jawetz, Melnick & Adelberg's medical microbiology</em> (28th ed.). McGraw-Hill Education."
    ),
    "sherris": (
        "Ryan, K. J., & Ray, C. G. (Eds.). (2014). "
        "<em>Sherris medical microbiology</em> (6th ed.). McGraw-Hill Education."
    ),
    "murray": (
        "Murray, P. R., Rosenthal, K. S., & Pfaller, M. A. (2021). "
        "<em>Medical microbiology</em> (8th ed.). Elsevier."
    ),
    "mandell": (
        "Bennett, J. E., Dolin, R., & Blaser, M. J. (Eds.). (2019). "
        "<em>Mandell, Douglas, and Bennett's principles and practice of infectious diseases</em> "
        "(9th ed.). Elsevier."
    ),
}

# Conjunto de fuentes usadas por defecto en el Tratado de Virología
VIROLOGY_SOURCES = ["fields", "principles", "jawetz", "sherris", "murray"]

# Conjunto de fuentes usadas en el pipeline de bacteriología
BACTERIOLOGY_SOURCES = ["mandell", "sherris", "murray", "jawetz"]


def build_generation_log(
    entity_name: str,
    entity_type: str = "virus",
    modules_used: Optional[list[dict]] = None,
    protocol: str = "Kaos Virology Pipeline v1.0",
    total_tokens: int = 0,
    thinking_lines: Optional[int] = None,
    tratado_base: Optional[str] = None,
    timestamp: Optional[datetime.datetime] = None,
    references: Optional[list[str]] = None,  # Lista de claves del APA_REFERENCES
) -> str:
    """
    Genera un bloque de metadatos de generación en HTML para incluir al pie
    de cada documento PDF/Markdown.

    Returns:
        String HTML con el bloque de log formateado.
    """
    if timestamp is None:
        timestamp = datetime.datetime.now()

    ts_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")

    # Calcular costo estimado
    cost_usd = _estimate_cost(modules_used or [], total_tokens)

    # Construir filas de módulos si se proporcionan
    module_rows = ""
    if modules_used:
        for m in modules_used:
            model_label = _model_label(m.get("model", "unknown"))
            tokens_str  = f"{m.get('tokens', 0):,}"
            module_rows += f"""
        <tr>
            <td><strong>M{m.get('id', '?')}</strong></td>
            <td>{m.get('name', '—')}</td>
            <td>{model_label}</td>
            <td style="text-align:right;">{tokens_str}</td>
        </tr>"""

    # Thinking lines badge
    if thinking_lines is not None:
        thinking_badge = f"""
        <tr>
            <td colspan="2"><strong>Líneas de Pensamiento</strong></td>
            <td colspan="2">{thinking_lines} líneas paralelas (Chain of Thought)</td>
        </tr>"""
    else:
        thinking_badge = ""

    # Tratado base
    base_row = ""
    if tratado_base:
        base_row = f"""
        <tr>
            <td colspan="2"><strong>Base de Conocimiento</strong></td>
            <td colspan="2">{tratado_base}</td>
        </tr>"""

    # Bloque de referencias APA
    refs_html = ""
    ref_keys = references if references is not None else []
    if ref_keys:
        ref_items = ""
        for i, key in enumerate(ref_keys, 1):
            apa_text = APA_REFERENCES.get(key, f"<em>Referencia '{key}' no encontrada en catálogo.</em>")
            ref_items += f'<li>{apa_text}</li>\n'
        refs_html = f"""
<div class="references-block">
    <h4 class="references-title">Referencias Bibliográficas</h4>
    <ol class="references-list">
        {ref_items}
    </ol>
</div>
"""

    html = f"""
<hr style="border: none; border-top: 2px solid #1a3a5c; margin-top: 40pt;">
<div class="generation-log">
    <table class="log-table">
        <thead>
            <tr>
                <th colspan="4">
                    METADATOS DE GENERACION — KAOS
                </th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td colspan="2"><strong>Autor</strong></td>
                <td colspan="2">Emilio Sanchez</td>
            </tr>
            <tr>
                <td colspan="2"><strong>Entidad</strong></td>
                <td colspan="2"><em>{entity_name}</em> ({entity_type.capitalize()})</td>
            </tr>
            <tr>
                <td colspan="2"><strong>Protocolo</strong></td>
                <td colspan="2">{protocol}</td>
            </tr>
            {base_row}
            <tr>
                <th>Modulo</th>
                <th>Nombre</th>
                <th>Modelo</th>
                <th style="text-align:right;">Tokens</th>
            </tr>
            {module_rows}
            {thinking_badge}
            <tr class="total-row">
                <td colspan="2"><strong>TOTAL TOKENS</strong></td>
                <td colspan="2" style="text-align:right;"><strong>{total_tokens:,}</strong></td>
            </tr>
        </tbody>
    </table>
    <p class="log-disclaimer">
        Documento generado por el sistema <strong>Kaos</strong> a partir de fuentes
        bibliogr&#225;ficas primarias de microbiolog&#237;a y virolog&#237;a.
        Los tokens de entrada incluyen el contexto inyectado del Tratado Maestro.
        DeepSeek-V4-Pro opera en modo <em>thinking=True</em>; MiniMax M2.7 en modo est&#225;ndar.
    </p>
</div>
{refs_html}
"""
    return html


# ── CSS adicional para el bloque de log ──────────────────────────────────────
LOG_CSS = """
.generation-log {
    margin-top: 16pt;
    font-size: 8pt;
    color: #444;
}

table.log-table {
    border-collapse: collapse;
    width: 100%;
    font-size: 8pt;
    margin-bottom: 8pt;
}

table.log-table th {
    background-color: #2c3e50;
    color: white;
    padding: 5pt 8pt;
    text-align: left;
    font-size: 9pt;
    letter-spacing: 0.5pt;
}

table.log-table td {
    padding: 3pt 8pt;
    border: 1px solid #ddd;
    vertical-align: top;
}

table.log-table tr:nth-child(even) {
    background-color: #f9f9f9;
}

table.log-table tr.total-row td {
    background-color: #eaf0fb;
    border-top: 2px solid #2c3e50;
    font-size: 9pt;
}

.log-disclaimer {
    font-size: 7.5pt;
    color: #888;
    font-style: italic;
    text-align: justify;
    margin-top: 4pt;
}

.references-block {
    margin-top: 14pt;
    padding-top: 8pt;
    border-top: 1px dashed #bbb;
}

.references-title {
    font-size: 9pt;
    color: #2c3e50;
    font-weight: bold;
    margin-bottom: 4pt;
    letter-spacing: 0.3pt;
    text-transform: uppercase;
}

.references-list {
    margin: 0;
    padding-left: 18pt;
    font-size: 7.5pt;
    color: #555;
    line-height: 1.5;
}

.references-list li {
    margin-bottom: 4pt;
    text-align: left;
}
"""


# ── Helpers ──────────────────────────────────────────────────────────────────
def _model_label(model: str) -> str:
    mapping = {
        "deepseek": "DeepSeek-V4-Pro (thinking)",
        "minimax":  "MiniMax M2.7",
        "hybrid":   "Hibrido (DeepSeek + MiniMax)",
    }
    return mapping.get(model.lower(), model)


def _estimate_cost(modules: list[dict], total_tokens: int) -> float:
    """
    Estima el costo en USD basado en los tokens y modelos usados.
    Precios (mayo 2026):
      DeepSeek V4-Pro: $0.27/1M input, $1.10/1M output (cache miss)
      MiniMax M2.7:    $0.02/1M input, $0.04/1M output
    Aproximación: 80% tokens = input, 20% = output.
    """
    cost = 0.0
    for m in modules:
        t = m.get("tokens", 0)
        inp = int(t * 0.8)
        out = int(t * 0.2)
        if "deepseek" in m.get("model", "").lower():
            cost += (inp / 1_000_000) * 0.27 + (out / 1_000_000) * 1.10
        else:
            cost += (inp / 1_000_000) * 0.02 + (out / 1_000_000) * 0.04
    
    # Si no hay desglose por módulo, estimar del total
    if not modules and total_tokens:
        inp = int(total_tokens * 0.8)
        out = int(total_tokens * 0.2)
        cost = (inp / 1_000_000) * 0.15 + (out / 1_000_000) * 0.57  # promedio híbrido

    return cost
