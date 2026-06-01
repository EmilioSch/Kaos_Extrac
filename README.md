# KaosExtract 🧠📚

> **AI-powered knowledge extraction engine from technical books.**
> Upload your own books. Define what you want to extract. Let the AI figure out the rest.

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![API](https://img.shields.io/badge/API-MiniMax%20%7C%20DeepSeek-purple.svg)](https://api.minimaxi.chat)

---

## The Problem

Large technical books contain everything you need — but making an LLM process a 900-page medical textbook (5.9MB of text) is not trivial:

- Sending the full book exceeds every model's context window
- Naive chunking loses inter-section coherence
- Simple keyword search misses chapters due to OCR artifacts or terminology variants
- Bibliographies pollute relevance scores with hundreds of false positive mentions

## The Solution: Dense Window Algorithm

KaosExtract uses a **two-strategy extraction system** that adapts automatically to each source:

```
For large books (>2MB):
  ┌─────────────────────────────────────────────────────────┐
  │  DENSE WINDOW ALGORITHM                                 │
  │                                                         │
  │  1. Split book into overlapping 100k-char blocks       │
  │  2. Score each block:                                   │
  │     score = (mentions × 10) + density_bonus            │
  │             - bibliography_penalty                      │
  │  3. Search for chapter heading with entity name         │
  │  4. Extract up to 360k chars from chapter start        │
  │                                                         │
  │  Result: the actual chapter, not random fragments      │
  └─────────────────────────────────────────────────────────┘

For small files (<2MB):
  ┌─────────────────────────────────────────────────────────┐
  │  CONTEXT WINDOW EXTRACTION                              │
  │                                                         │
  │  1. Find all positions where entity appears            │
  │  2. Extract ±15k chars around each mention             │
  │  3. Merge overlapping windows                          │
  │  4. Cap at 120k chars total per source                 │
  └─────────────────────────────────────────────────────────┘
```

**Bibliography penalization** is a key innovation: bibliography sections have 50–100 citations of an entity's name but contain no clinical content. The algorithm detects patterns like `2008;6:32`, `et al.`, journal abbreviations, and penalizes those blocks so the real chapter wins.

---

## Features

| Feature | Description |
|---|---|
| 📖 **PDF Ingestion** | Upload PDFs directly — KaosExtract converts to clean text |
| 🔍 **Dense Window Algorithm** | Identifies the right chapter in 900-page books |
| 🔧 **OCR Repair** | Fixes scanned books with spaced letters (`S tr e p` → `Strep`) |
| ⚡ **Parallel Module Generation** | Multiple sections generated simultaneously, then synthesized |
| 🤖 **Hybrid Model Routing** | Simple tasks → MiniMax, complex reasoning → DeepSeek |
| ✅ **Offline QC** | Detects encoding corruption, broken tables, wrong language — no API cost |
| 📋 **YAML Templates** | Define what to extract without touching any Python code |
| 💰 **Cost Estimator** | Preview token usage and API cost before running |
| 🌐 **Multi-source** | Process multiple books simultaneously, each as a parallel source group |

---

## Quickstart

### 1. Clone and setup

```bash
git clone https://github.com/yourusername/kaosextract.git
cd kaosextract
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then add your API keys
```

### 2. Add your API keys

```bash
# .env
MINIMAX_API_KEY=your_key_here
DEEPSEEK_API_KEY=your_key_here  # optional
```

### 3. Upload your books

```bash
# PDF files are automatically converted to text
python kaosextract.py ingest my_textbook.pdf
python kaosextract.py ingest ./my_library/ --pattern "*.pdf"

# See what's available
python kaosextract.py sources list
```

### 4. Estimate cost (no API calls)

```bash
python kaosextract.py estimate --entity "Streptococcus pyogenes"

# Output:
# 📊 Estimation for: Streptococcus pyogenes
#
#   Source                               Size    Mentions  Strategy
#   Murray_Microbiology.txt              5.9 MB      847   Dense Window
#   my_notes.txt                         340 KB       23   Window ×23
#
#   Estimated tokens: 124,500
#   Estimated cost:   $0.0374 USD
```

### 5. Run the extraction

```bash
python kaosextract.py run --entity "Streptococcus pyogenes"
# → Generates a structured report in output/reports/
```

---

## How Templates Work

Templates define **what dimensions** of a topic to extract. You write them in YAML — no Python required.

```yaml
# templates/my_template.yaml
name: "Pharmacology"
language: "en"
entity_label: "drug"

modules:
  - id: 1
    name: "Mechanism of Action"
    sections:
      - id: "MOA"
        directive: >
          Molecular mechanism of action of {ENTITY}: receptor targets,
          binding sites, downstream signaling cascade.
      - id: "PKD"
        directive: >
          Pharmacodynamics: dose-response relationship, efficacy vs. potency,
          therapeutic window.

  - id: 2
    name: "Clinical Use"
    sections:
      - id: "IND"
        directive: >
          Approved indications with clinical evidence levels.
      - id: "ADR"
        directive: >
          Adverse effects: mechanism, frequency, management.

search_aliases:
  "ibuprofen":
    - "ibuprofeno"
    - "NSAIDs"
    - "anti-inflammatory"
```

Then run:
```bash
python kaosextract.py run --entity "Ibuprofen" --template pharmacology
```

**Pre-built templates:**
- `medical_microbiology` — bacteria & viruses (etiology, epidemiology, virulence, pathogenesis, diagnosis, treatment)
- `custom_template` — blank template with documentation

---

## Batch Processing

Process multiple entities from a text file:

```bash
# entities.txt
Streptococcus pyogenes
Staphylococcus aureus
# This is a comment
Mycobacterium tuberculosis
Escherichia coli

python kaosextract.py batch --entities entities.txt --continue-on-error
```

---

## Architecture

```
kaosextract/
├── kaosextract.py          # Unified CLI entry point
│
├── core/
│   ├── file_loader.py      # Dense Window Algorithm + context window extraction
│   ├── template_loader.py  # YAML template loading and validation
│   ├── api_client.py       # Async API client (MiniMax + DeepSeek)
│   ├── parallel_modules.py # Parallel section generation + synthesis + offline QC
│   └── generation_log.py   # Token tracking and cost logging
│
├── pipeline/
│   ├── ingest.py           # PDF → TXT conversion, OCR repair
│   ├── phase1_extraction.py    # Source extraction per group
│   ├── phase2_consolidation.py # Merge all source extractions
│   ├── phase3_analysis.py      # Module generation (parallel)
│   └── phase4_report.py        # PDF/MD report generation
│
└── templates/
    ├── medical_microbiology.yaml   # Pre-built medical template
    └── custom_template.yaml        # Blank template to copy
```

**Pipeline flow:**

```
User books (PDF)
      ↓
  [ingest.py] PDF → TXT + OCR repair
      ↓
  [phase1] Dense Window / Context Window extraction per source
      ↓
  [phase2] Concatenate all source extractions → master document
      ↓
  [phase3] For each module:
            ├── N sections generated in parallel
            ├── Synthesis call (merge sections)
            └── Offline QC (encoding, tables, language)
      ↓
  [phase4] Structured report (Markdown + PDF)
```

---

## Supported APIs

| Model | Use case | Pricing (approx.) |
|---|---|---|
| MiniMax M2.7 | Standard modules | ~$0.30/MTok |
| DeepSeek V4-Pro | Complex reasoning modules | ~$0.14/MTok |

The hybrid router automatically assigns complex modules (pathophysiology, molecular mechanisms) to the more capable model.

---

## Requirements

- Python 3.11+
- MiniMax API key ([minimaxi.chat](https://minimaxi.chat)) — required
- DeepSeek API key ([platform.deepseek.com](https://platform.deepseek.com)) — optional, for hybrid mode
- `pdfminer.six` or `pymupdf` — for PDF ingestion

---

## Configuration

All settings in `config.py` can be overridden via environment variables:

| Variable | Default | Description |
|---|---|---|
| `MINIMAX_API_KEY` | — | MiniMax API key (required) |
| `DEEPSEEK_API_KEY` | — | DeepSeek API key (optional) |
| `SOURCES_DIR` | `./upload` | Directory where books are stored |
| `OUTPUT_DIR` | `./output` | Directory for generated reports |
| `KAOS_TEMPLATE` | `medical_microbiology` | Default template name |
| `USE_HYBRID_MODEL` | `true` | Enable DeepSeek for complex modules |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

---

## License

MIT — use it, fork it, build on it.

---

*Built from a real medical education pipeline that processed 28 bacteria and 30+ viruses from textbooks like Murray, Sherris, and Mandell.*
