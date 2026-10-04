# ORVIA — Project Summary

> **ORVIA — Personal Research Intelligence Workspace**
> "Explore Information. Discover What Connects."
> Version 1.0.0

---

## What Was Built

ORVIA is a complete, production-ready personal research intelligence workspace. It was designed and built across 12 phases, each adding a distinct layer of capability on top of a stable, local-first architecture.

The complete system allows a researcher to:

1. **Import** sources (text, CSV, JSON files) into a structured research library
2. **Search** their library using a deterministic BM25 full-text search engine
3. **Explore** extracted concepts and their frequency patterns
4. **Navigate** a knowledge graph of concept relationships
5. **Investigate** a research question by linking sources, recording evidence, noting findings, and tracking open questions
6. **Analyze** patterns across the research collection (trend detection, concept frequency, co-occurrence, source density)
7. **Synthesize** structured research reports with traceable citations and evidence provenance
8. **Export** reports as clean Markdown
9. **Back up** the full workspace with a single click

---

## Architecture Summary

| Dimension | Choice |
|---|---|
| Language | Python 3.10+ |
| Web framework | Flask 3.x |
| Persistence | SQLite 3 (WAL mode) |
| Search | Deterministic BM25 + inverted positional index |
| Intelligence | Deterministic: co-occurrence, frequency, graph algorithms |
| UI | Jinja2 templates, vanilla JavaScript |
| AI/LLM | None |
| Cloud | None |
| External APIs | None |
| Telemetry | None |

---

## Phase History

| Phase | Capability Added |
|---|---|
| **Phase 1** | Python package structure, SQLite schema, DatabaseManager, Config, exceptions, logging |
| **Phase 2** | Visual design system (dark graphite + acid-lime), base templates, layout, navigation |
| **Phase 3** | Overview / Command Center: live stats, recent activity, quick access |
| **Phase 4** | Source ingestion (TXT/CSV/JSON), source repository, source detail views, statistics |
| **Phase 5** | BM25 search engine, inverted positional index, ranking, search history, results UI |
| **Phase 6** | Concept extraction, concept repository, concept relationships, concept intelligence views |
| **Phase 7** | Knowledge graph: builder, graph algorithms (PageRank, centrality), D3.js visualization |
| **Phase 8** | Investigation workspace: create/manage investigations, attach sources/concepts, record evidence/findings/questions/notes |
| **Phase 9** | Research analytics: concept frequency trends, source density, pattern detection, emerging concepts, cross-source analysis |
| **Phase 10** | Research reports: synthesis engine, structured sections, citations, evidence provenance, quality analysis, Markdown export, versioning |
| **Phase 11** | Advanced research workflow: command palette, universal search, research context, source comparison, research tensions, timeline, data health |
| **Phase 12** | Final integration: database backup, api_demo_clear, version 1.0.0, documentation, test verification |

---

## Test Coverage

- **314 unit tests** across all phases
- All tests are isolated using in-memory SQLite databases
- Run with: `python -m unittest discover -s tests -v`
- All 314 tests pass at 1.0.0 release

---

## Key Design Decisions

1. **No ORM.** Raw SQL through DatabaseManager keeps the dependency surface minimal.
2. **No LLMs.** Deterministic algorithms only. Every result is explainable.
3. **Application factory pattern.** `create_app(config)` enables isolated test instances.
4. **Service layer.** Business logic is isolated from routing and persistence.
5. **Traceable reports.** Every report section links back to real user evidence.
6. **WAL mode.** SQLite WAL enables concurrent reads during backup.

---

## Files Delivered

```
orvia/                     # Application package
tests/                     # 314 unit tests
data/                      # Runtime database (git-ignored)
run.py                     # Web server entry point
main.py                    # CLI foundation check
requirements.txt           # flask>=3.0.0,<4.0.0
.gitignore                 # Python, venv, data, logs
.env.example               # Environment configuration template
README.md                  # User quickstart and overview
ARCHITECTURE.md            # System architecture reference
RESEARCH_INTEGRITY.md      # Research integrity principles
LIMITATIONS.md             # Honest capability boundaries
PROJECT_SUMMARY.md         # This file
RELEASE_CHECKLIST.md       # Pre-release verification checklist
```

---

## Non-Goals (Intentional)

- No semantic search (no embeddings, no vector DB)
- No AI-generated content (no LLMs, no GPT, no Gemini, no Claude)
- No cloud sync (fully local)
- No multi-user support (personal workspace)
- No mobile app (web UI only)
- No plugin system (for this release)
