"""
core/logger.py — Sistema de Logging Centralizado
=================================================
PROPÓSITO: Proporciona un logger único y consistente para todo el pipeline.
           Guarda logs en archivo y opcionalmente los muestra en consola con colores.
USO: from core.logger import get_logger
     log = get_logger(__name__)
     log.info("Mensaje informativo")
"""

import logging
import sys
from pathlib import Path
from datetime import datetime
from rich.logging import RichHandler  # Logs con colores y formato bonito en consola
import config

# Guardar referencia al logger raíz del pipeline para no crearlo múltiples veces
_loggers: dict[str, logging.Logger] = {}


def get_logger(name: str) -> logging.Logger:
    """
    Retorna un logger configurado para el módulo 'name'.
    Si ya existe uno con ese nombre, lo retorna directamente (no duplica handlers).

    Args:
        name: Normalmente se pasa __name__ del módulo que llama.

    Returns:
        Logger configurado con handler de archivo y consola.
    """
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))

    # Evitar duplicar handlers si el logger ya fue configurado
    if logger.handlers:
        _loggers[name] = logger
        return logger

    # ── Handler de archivo ──────────────────────────────────────────────────
    # Crea el directorio de logs si no existe
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # Nombre del archivo de log incluye la fecha para facilitar revisión
    log_file = config.LOGS_DIR / f"pipeline_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)  # El archivo guarda TODO, incluyendo DEBUG
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(file_handler)

    # ── Handler de consola (con colores via Rich) ────────────────────────────
    if config.LOG_TO_CONSOLE:
        console_handler = RichHandler(
            rich_tracebacks=True,
            show_path=False,       # No mostrar ruta del archivo fuente
            markup=True            # Permite texto con formato [bold], etc.
        )
        console_handler.setLevel(getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))
        logger.addHandler(console_handler)

    logger.propagate = False  # Evitar que el logger raíz duplique mensajes
    _loggers[name] = logger
    return logger
