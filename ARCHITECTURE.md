# ORVIA — System Architecture

> Version 1.0.0 | Local-first | Deterministic | Python + SQLite

---

## Overview

ORVIA is structured as a classic layered application: UI → Services → Repositories → Database. Each layer has a single responsibility. There are no circular dependencies between layers.

```
Browser / Jinja2 Templates
        │
        ▼
    Flask Routes  (orvia/app/ui/routes.py)
        │
        ├── Services (business logic, no direct DB access)
        │     ├── IngestionService
        │     ├── SearchEngine
        │     ├── ConceptAnalysisService
        │     ├── GraphService
        │     ├── InvestigationService
        │     ├── AnalyticsService
        │     ├── ResearchReportService
        │     └── ResearchWorkspaceService
        │
        ├── Repositories (SQL persistence, return domain models)
        │     ├── SourceRepository
        │     ├── ConceptRepository
        │     ├── InvestigationRepository
        │     ├── DocumentRepository
        │     └── TopicRepository
        │
        └── Core
              ├── DatabaseManager  (connection, WAL, backup)
              ├── Config           (from_env, typed fields)
              ├── Exceptions       (OrviaError hierarchy)
              └── logging_config
```

---

## Directory Map

```
orvia/
├── __init__.py                      # __version__ = "1.0.0"
├── app/
│   ├── core/
│   │   ├── config.py                # Config: database_path, log_level, debug
│   │   ├── database.py              # DatabaseManager: execute/fetchall/fetchone/backup
│   │   ├── exceptions.py            # OrviaError, ValidationError, DatabaseError, NotFoundError
│   │   └── logging_config.py        # Structured logging setup
│   │
│   ├── models/                      # Pure domain model classes (no SQL)
│   │   └── source.py, concept.py, investigation.py, evidence.py, report.py…
│   │
│   ├── repositories/                # SQL read/write for each domain
│   │   ├── source_repository.py
│   │   ├── concept_repository.py
│   │   ├── investigation_repository.py
│   │   └── …
│   │
│   ├── ingestion/                   # File importers
│   │   ├── importer.py              # IngestionService (orchestrator)
│   │   ├── txt_importer.py
│   │   ├── csv_importer.py
│   │   ├── json_importer.py
│   │   ├── normalizer.py            # Text cleaning
│   │   └── demo_data.py             # Reproducible demo dataset
│   │
│   ├── search/                      # Deterministic full-text search
│   │   ├── engine.py                # SearchEngine (BM25 + positional)
│   │   ├── index.py                 # InvertedIndex
│   │   ├── tokenizer.py             # Tokenizer (stop words, stemming-lite)
│   │   ├── ranking.py               # BM25 scoring
│   │   └── history.py               # Search history persistence
│   │
│   ├── knowledge/
│   │   └── graph/
│   │       ├── service.py           # GraphService
│   │       ├── builder.py           # Graph construction from concepts
│   │       ├── algorithms.py        # PageRank, centrality, community detection
│   │       ├── filters.py           # Graph filter helpers
│   │       └── serializers.py       # JSON serialization for frontend
│   │
│   ├── investigations/
│   │   ├── service.py               # InvestigationService
│   │   ├── repository.py            # InvestigationRepository
│   │   └── models.py                # Investigation, Evidence, Finding, Question, Note
│   │
│   ├── analysis/
│   │   └── analytics/
│   │       └── service.py           # AnalyticsService (patterns, trends, co-occurrence)
│   │
│   ├── reports/
│   │   ├── service.py               # ResearchReportService
│   │   ├── repository.py            # ReportRepository
│   │   ├── models.py                # Report, ReportSection, ReportSource, …
│   │   ├── synthesis.py             # ReportSynthesisEngine
│   │   ├── citations.py             # CitationManager
│   │   ├── export.py                # Markdown export
│   │   ├── quality.py               # ReportQualityAnalyzer
│   │   └── comparison.py            # ReportVersionComparator
│   │
│   ├── services/
│   │   └── workspace_service.py     # WorkspaceService (Phase 1 stats + health, used by main.py)
│   │
│   ├── workspace/                   # Phase 11: Advanced research workflow
│   │   ├── service.py               # ResearchWorkspaceService
│   │   └── models.py                # ActivityType, ResearchActivity, ResearchContext…
│   │
│   └── ui/
│       ├── __init__.py              # create_app(), get_db() (Flask application factory)
│       ├── routes.py                # All HTTP routes (~1800 lines)
│       ├── static/
│       │   ├── css/
│       │   │   ├── orvia.css        # Design system (variables, components, layout)
│       │   │   ├── analytics.css
│       │   │   ├── investigation.css
│       │   │   ├── knowledge_graph.css
│       │   │   └── reports.css
│       │   └── js/
│       │       ├── orvia.js         # App shell, command palette, keyboard nav
│       │       ├── analytics.js
│       │       ├── investigation.js
│       │       ├── knowledge_graph.js
│       │       └── reports.js
│       └── templates/               # 20+ Jinja2 HTML templates
│
├── tests/                           # 314 unit tests (all phases)
├── data/                            # Runtime: orvia.db + backups/ (git-ignored)
├── run.py                           # Web server entry point
├── main.py                          # CLI startup / foundation check
└── requirements.txt
```

---

## Key Architectural Decisions

### 1. Application Factory Pattern
`create_app(config)` in `orvia/app/ui/__init__.py` wires all routes and extensions. Each test gets a fresh app instance with an in-memory SQLite database.

### 2. DatabaseManager
A single `DatabaseManager` class wraps the SQLite connection. All queries go through `execute()`, `fetchall()`, and `fetchone()`. WAL mode and foreign key enforcement are applied at connection time. Online backup uses `sqlite3.Connection.backup()` — non-blocking, safe during reads.

### 3. No ORM
ORVIA uses raw SQL via the `DatabaseManager`. This keeps the dependency surface minimal and makes every query auditable.

### 4. Service Layer Isolation
Services never access `db._connection` directly. They call `db.execute()`, `db.fetchall()`, and `db.fetchone()`. Repositories are the only layer that writes SQL; services call repositories.

### 5. Deterministic Intelligence
All analytics (concept frequency, co-occurrence, trend detection, research gaps) are computed from observable database records. No probabilistic models, no embeddings, no external APIs.

### 6. Request-scoped Database Connection
`get_db()` returns a `DatabaseManager` stored in Flask's `g` object. It is closed at the end of every request via `teardown_appcontext`.

---

## Database Schema (key tables)

| Table | Purpose |
|---|---|
| `sources` | Ingested research sources |
| `source_statistics` | Word count, reading time, unique words per source |
| `concepts` | Extracted multi-word concepts |
| `concept_source_links` | Many-to-many: concepts ↔ sources |
| `concept_relationships` | Pairwise concept co-occurrence relationships |
| `search_index` | Inverted index terms |
| `search_history` | User query history |
| `investigations` | Research investigations |
| `investigation_sources` | Sources attached to an investigation |
| `investigation_concepts` | Concepts tracked in an investigation |
| `investigation_evidence` | Evidence records |
| `investigation_findings` | Findings with status |
| `investigation_finding_evidence` | Finding ↔ evidence junction |
| `investigation_questions` | Open research questions |
| `investigation_notes` | Free-form investigation notes |
| `investigation_activity` | Audit log of all investigation actions |
| `research_context_state` | Per-investigation research context |
| `reports` | Research reports |
| `report_sections` | Report section content |
| `report_sources` | Sources cited in a report |
| `report_evidence` | Evidence referenced in a report |
| `report_findings` | Findings included in a report |
| `research_activities` | Global activity stream |

---

## Entry Points

| Command | Purpose |
|---|---|
| `python run.py` | Start web server (default: `http://127.0.0.1:5000`) |
| `python run.py --port 8080 --debug` | Custom port + debug mode |
| `python main.py` | CLI startup check (validates DB, prints status) |
| `python -m unittest discover -s tests -v` | Run full test suite |
