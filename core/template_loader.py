"""
core/template_loader.py — Cargador de Templates de Módulos
===========================================================
PROPÓSITO: Carga el template YAML activo y expone los módulos, secciones
           y aliases de búsqueda como objetos Python listos para usar.

USO:
    from core.template_loader import load_template, get_search_aliases
    template = load_template()  # Carga el template configurado en config.py
    aliases = get_search_aliases(template, "streptococcus pyogenes")
"""

from pathlib import Path
from typing import Optional
import yaml
import config
from core.logger import get_logger

log = get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


class Template:
    """Representación en memoria de un template YAML cargado."""

    def __init__(self, data: dict):
        self._data = data

    @property
    def name(self) -> str:
        return self._data.get("name", "Unknown Template")

    @property
    def version(self) -> str:
        return self._data.get("version", "1.0")

    @property
    def language(self) -> str:
        return self._data.get("language", "en")

    @property
    def entity_label(self) -> str:
        return self._data.get("entity_label", "entity")

    @property
    def output_language(self) -> str:
        return self._data.get("output_language", "English")

    @property
    def system_prompt(self) -> str:
        return self._data.get("system_prompt", "")

    @property
    def synthesis_prompt(self) -> str:
        return self._data.get("synthesis_prompt", "")

    @property
    def modules(self) -> list[dict]:
        return self._data.get("modules", [])

    @property
    def search_aliases(self) -> dict[str, list[str]]:
        return self._data.get("search_aliases", {})

    def get_module_sections(self) -> dict[int, list[tuple[str, str]]]:
        """
        Retorna el dict de secciones por módulo, compatible con parallel_modules.py.
        Returns: {module_id: [(section_id, directive), ...]}
        """
        result: dict[int, list[tuple[str, str]]] = {}
        for module in self.modules:
            mod_id = module.get("id")
            sections = module.get("sections", [])
            result[mod_id] = [(s["id"], s["directive"]) for s in sections]
        return result

    def get_module_entries(self) -> list[tuple]:
        """
        Retorna la lista de entradas de módulo compatible con el pipeline existente.
        Returns: [(mod_id, mod_name, module_prompt_placeholder, use_deepseek), ...]
        """
        entries = []
        for module in self.modules:
            mod_id = module.get("id")
            mod_name = module.get("name", f"Module {mod_id}")
            complexity = module.get("complexity", "standard")
            use_deepseek = complexity == "complex"
            # El prompt real se construye dinámicamente desde las secciones
            entries.append((mod_id, mod_name, self.synthesis_prompt, use_deepseek))
        return entries

    def get_aliases_for_entity(self, entity_name: str) -> list[str]:
        """
        Retorna los aliases de búsqueda para una entidad dada.
        La búsqueda es flexible: si la clave del alias contiene el nombre o viceversa.
        """
        entity_lower = entity_name.lower().split("|")[0].strip()
        for key, aliases in self.search_aliases.items():
            if key in entity_lower or entity_lower in key:
                return [a for a in aliases if isinstance(a, str)]
        return []


def load_template(template_name: Optional[str] = None) -> Template:
    """
    Carga un template YAML desde la carpeta templates/.

    Args:
        template_name: Nombre del template sin extensión (ej: "medical_microbiology").
                       Si es None, usa config.ACTIVE_TEMPLATE.

    Returns:
        Objeto Template cargado y validado.

    Raises:
        FileNotFoundError: Si el template no existe.
        ValueError: Si el template tiene formato inválido.
    """
    name = template_name or config.ACTIVE_TEMPLATE
    template_path = _TEMPLATES_DIR / f"{name}.yaml"

    if not template_path.exists():
        available = [f.stem for f in _TEMPLATES_DIR.glob("*.yaml")]
        raise FileNotFoundError(
            f"Template '{name}' not found. Available templates: {available}\n"
            f"Templates directory: {_TEMPLATES_DIR}"
        )

    log.info(f"Loading template: {template_path.name}")

    try:
        with open(template_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in template '{name}': {e}")

    if not isinstance(data, dict):
        raise ValueError(f"Template '{name}' must be a YAML mapping at the top level.")

    if "modules" not in data or not data["modules"]:
        raise ValueError(f"Template '{name}' has no modules defined.")

    template = Template(data)
    log.info(
        f"Template loaded: '{template.name}' v{template.version} "
        f"— {len(template.modules)} modules, language={template.language}"
    )
    return template


def list_templates() -> list[str]:
    """Retorna los nombres de todos los templates disponibles."""
    if not _TEMPLATES_DIR.exists():
        return []
    return sorted(f.stem for f in _TEMPLATES_DIR.glob("*.yaml")
                  if f.stem != "custom_template")
