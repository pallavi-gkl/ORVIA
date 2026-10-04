# ORVIA — Personal Research Intelligence Workspace

> **"Explore Information. Discover What Connects."**

ORVIA is a local-first, deterministic personal research intelligence workspace. It helps researchers collect sources, extract concepts, discover relationships, investigate questions, analyze patterns, and synthesize structured research reports — entirely on their own machine, without cloud services or AI APIs.

---

## Quick Start

```bash
# 1. Clone the repository
git clone <repo-url>
cd orvia

# 2. Create a virtual environment
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run ORVIA
python run.py

# Open http://127.0.0.1:5000 in your browser
```

### Optional configuration

```bash
cp .env.example .env
# Edit .env to change the port, database path, or log level
```

---

## What ORVIA Does

| Capability | Description |
|---|---|
| **Source Ingestion** | Import plain text, CSV, or JSON files into your research library |
| **Search** | Deterministic full-text BM25 search with positional indexing and ranking |
| **Concept Extraction** | Automatic multi-word concept detection across your library |
| **Knowledge Graph** | Visual concept relationship map with co-occurrence analysis |
| **Investigation Workspace** | Structured research investigations with evidence, findings, and open questions |
| **Research Analytics** | Pattern detection across sources, concepts, and time |
| **Research Reports** | Structured reports with traceable citations and evidence provenance |
| **Database Backup** | One-click local SQLite snapshots |

---

## Architecture

- **Language:** Python 3.10+
- **Web framework:** Flask 3.x
- **Persistence:** SQLite 3 (WAL mode, foreign key enforcement)
- **Search:** Deterministic BM25 + inverted positional index (no external service)
- **Intelligence:** OOP service layer, co-occurrence analysis, TF-IDF variant scoring
- **UI:** Jinja2 templates, vanilla JavaScript, custom ORVIA design system
- **AI/LLM:** **None.** All intelligence is deterministic and explainable.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full system map.

---

## Project Structure

```
orvia/
├── app/
│   ├── core/           # Config, DatabaseManager, exceptions, logging
│   ├── models/         # Domain models (Source, Concept, Investigation, Report…)
│   ├── repositories/   # SQLite persistence layer
│   ├── ingestion/      # File importers (TXT, CSV, JSON) + demo data
│   ├── search/         # BM25 engine, inverted index, ranking, history
│   ├── knowledge/      # Knowledge graph builder and algorithms
│   ├── investigations/ # Investigation service and repository
│   ├── analysis/       # Research analytics and pattern intelligence
│   ├── reports/        # Report synthesis, citations, export, quality
│   ├── workspace/      # Research workflow and activity tracking
│   └── ui/             # Flask routes, templates, static assets
├── tests/              # 314 unit tests covering all phases
├── data/               # Runtime: orvia.db + backups/ (git-ignored)
├── run.py              # Web server entry point
├── main.py             # CLI foundation check
└── requirements.txt
```

---

## Running Tests

```bash
python -m unittest discover -s tests -v
```

All 314 tests must pass. Tests are isolated and use in-memory SQLite databases.

---

## Design Principles

1. **Local-first.** Your research data never leaves your machine.
2. **Deterministic.** Every analysis result can be explained and reproduced.
3. **Traceable.** Every claim in a research report links back to a specific source and evidence record.
4. **No LLMs.** ORVIA uses statistical text analysis, co-occurrence, and graph algorithms — never generative AI.
5. **No telemetry.** Zero external tracking.

---

## Phases Completed

| Phase | Feature |
|---|---|
| 1 | Foundation & architecture |
| 2 | Visual design system |
| 3 | Overview / Command Center |
| 4 | Source Intelligence |
| 5 | Search Intelligence (BM25) |
| 6 | Concept Intelligence |
| 7 | Knowledge Graph |
| 8 | Investigation Workspace |
| 9 | Research Analytics & Pattern Intelligence |
| 10 | Research Reports & Evidence Synthesis |
| 11 | Advanced Research Workflow & Product Polish |
| 12 | Final Integration, Testing & Deployment Readiness |

---

## Limitations

See [`LIMITATIONS.md`](LIMITATIONS.md) for a full description of what ORVIA intentionally does not do.

---

## Version

ORVIA 1.0.0 — Final release.
