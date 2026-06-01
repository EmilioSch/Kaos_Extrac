"""
config.py — KaosExtract Configuration
=======================================
All settings here can be overridden via environment variables in .env
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── MiniMax API ───────────────────────────────────────────────────────────────
MINIMAX_API_KEY: str = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL: str = "https://api.minimaxi.chat/v1"
MINIMAX_MODEL: str = "MiniMax-M2.7"
MAX_TOKENS: int = 8192
TEMPERATURE: float = 0.2

# ── DeepSeek API (optional, used for complex modules) ─────────────────────────
DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL: str = "deepseek-chat"
DEEPSEEK_MAX_TOKENS: int = 16384
DEEPSEEK_TEMPERATURE: float = 0.1

# ── Hybrid model routing ───────────────────────────────────────────────────────
# If True: complex modules → DeepSeek, simple modules → MiniMax
USE_HYBRID_MODEL: bool = os.getenv("USE_HYBRID_MODEL", "true").lower() == "true"
DEEPSEEK_WEIGHT: float = 0.6

# ── Rate limiting (MiniMax) ───────────────────────────────────────────────────
MAX_CONCURRENT_API_CALLS: int = 10
MIN_REQUEST_INTERVAL: float = 0.5
RETRY_DELAY_ON_RATE_LIMIT: float = 30.0
MAX_RETRIES: int = 3

# ── Rate limiting (DeepSeek) ──────────────────────────────────────────────────
DEEPSEEK_MAX_CONCURRENT: int = 10
DEEPSEEK_MIN_INTERVAL: float = 1.0

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT: Path = Path(__file__).parent.resolve()

# Books and source files uploaded by the user go here.
# Override with SOURCES_DIR environment variable.
SOURCES_BASE_DIR: Path = Path(os.getenv(
    "SOURCES_DIR",
    str(PROJECT_ROOT / "upload")
))

# Sub-directories inside upload/ for organizing sources by type
BOOKS_DIR: Path     = SOURCES_BASE_DIR / "Books"
CLASSES_DIR: Path   = SOURCES_BASE_DIR / "Notes"
ASESORIAS_DIR: Path = SOURCES_BASE_DIR / "Lectures"
OTHERS_DIR: Path    = SOURCES_BASE_DIR / "Other"
ARTICLES_DIR: Path  = SOURCES_BASE_DIR / "Articles"
EXAMENES_DIR: Path  = SOURCES_BASE_DIR / "Exams"

# Output directories (generated reports, cache, logs)
OUTPUT_BASE_DIR: Path = Path(os.getenv("OUTPUT_DIR", str(PROJECT_ROOT / "output")))
MASTERS_DIR: Path     = OUTPUT_BASE_DIR / "masters"
REPORTS_DIR: Path     = OUTPUT_BASE_DIR / "reports"
REPORTS_MD_DIR: Path  = REPORTS_DIR / "md"
REPORTS_PDF_DIR: Path = REPORTS_DIR / "pdf"
LOGS_DIR: Path        = OUTPUT_BASE_DIR / "logs"
CACHE_DIR: Path       = OUTPUT_BASE_DIR / "cache"

# ── Extraction settings ───────────────────────────────────────────────────────
# Characters of context to extract around each mention (small files)
CONTEXT_WINDOW_CHARS: int = 15_000
# Total character limit per source sent to the API (~30k tokens)
MAX_CHARS_PER_SOURCE: int = 120_000
# File size threshold to activate Dense Window Algorithm (2MB)
DENSE_WINDOW_SIZE_THRESHOLD: int = 2_000_000

# ── Pipeline options ──────────────────────────────────────────────────────────
KEEP_INTERMEDIATE_FILES: bool = True
PDF_CSS_FILE: Path = PROJECT_ROOT / "output" / "styles.css"

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_TO_CONSOLE: bool = True

# ── Active template ────────────────────────────────────────────────────────────
# Name of the YAML template to use (must exist in templates/)
# Override with KAOS_TEMPLATE environment variable
ACTIVE_TEMPLATE: str = os.getenv("KAOS_TEMPLATE", "medical_microbiology")

# ── Module complexity routing ──────────────────────────────────────────────────
# Loaded dynamically from the active template. Set here as defaults.
USE_THINKING_LINES: bool = True
MODULE_COMPLEXITY: dict[int, dict] = {
    1: {"model": "minimax", "lines": 2, "name": "MODULE_1"},
    2: {"model": "minimax", "lines": 2, "name": "MODULE_2"},
    3: {"model": "minimax", "lines": 2, "name": "MODULE_3"},
    4: {"model": "hybrid",  "lines": 5, "name": "MODULE_4"},
    5: {"model": "minimax", "lines": 2, "name": "MODULE_5"},
    6: {"model": "minimax", "lines": 2, "name": "MODULE_6"},
}
