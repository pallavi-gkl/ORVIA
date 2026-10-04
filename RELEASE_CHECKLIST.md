# ORVIA 1.0.0 — Release Checklist

Use this checklist before tagging a release. Check each item manually.

---

## Code Quality

- [x] All 314 unit tests pass (`python -m unittest discover -s tests -v`)
- [x] No hardcoded absolute user paths in any source file
- [x] Version string is `1.0.0` in `orvia/__init__.py`
- [x] Version string is `1.0.0` default in `orvia/app/core/config.py`
- [x] `requirements.txt` contains only production dependencies (no LLM deps)

---

## Architecture

- [x] No duplicate service layers (workspace_service.py and workspace/service.py serve distinct purposes)
- [x] All routes registered in `register_routes()` in `routes.py`
- [x] Application factory pattern in `orvia/app/ui/__init__.py`
- [x] DatabaseManager uses WAL mode
- [x] DatabaseManager enforces foreign keys
- [x] Backup API exists: `POST /api/backup/create`, `GET /api/backup/list`
- [x] Demo clear API exists: `POST /api/demo/clear`

---

## Security

- [x] No hardcoded credentials in any file
- [x] No hardcoded absolute paths to user's local filesystem
- [x] `.env` is in `.gitignore`
- [x] `data/orvia.db` is in `.gitignore`
- [x] `data/backups/` is in `.gitignore`
- [x] Debug mode is `False` by default
- [x] ORVIA binds to `127.0.0.1` (localhost) by default — not exposed to network

---

## Features

- [x] Source ingestion: TXT, CSV, JSON
- [x] Full-text BM25 search
- [x] Concept extraction and relationships
- [x] Knowledge graph visualization
- [x] Investigations with evidence, findings, questions, notes
- [x] Research analytics and pattern detection
- [x] Research reports with citations and provenance
- [x] Report Markdown export
- [x] Report versioning
- [x] Command palette (Ctrl+K)
- [x] Universal search
- [x] Source comparison
- [x] Research timeline
- [x] Data integrity diagnostics
- [x] Search index health and rebuild
- [x] Database backup (create + list)
- [x] Demo data load and clear

---

## Documentation

- [x] `README.md` — user-facing quickstart and overview
- [x] `ARCHITECTURE.md` — system architecture reference
- [x] `RESEARCH_INTEGRITY.md` — research integrity principles
- [x] `LIMITATIONS.md` — honest capability boundaries
- [x] `PROJECT_SUMMARY.md` — project overview and phase history
- [x] `.env.example` — environment configuration template
- [x] `.gitignore` — covers Python, venv, data, logs

---

## UI

- [x] Settings page shows database path
- [x] Settings page shows index health with rebuild button
- [x] Settings page shows data integrity diagnostics
- [x] Settings page shows sample data (load/clear)
- [x] Settings page shows database backup (create + list)
- [x] Settings page shows keyboard shortcuts
- [x] Settings page shows ORVIA version
- [x] All pages use ORVIA design system (no blue/purple/neon)

---

## Pre-Release Verification Steps

1. `python -m unittest discover -s tests -v` → All 314 tests must pass
2. `python run.py` → Application starts without errors
3. Open `http://127.0.0.1:5000` → Overview page loads
4. Navigate to Settings → Backup section visible, "Create Backup Now" works
5. Navigate to Settings → "Load Demo Dataset" loads sources
6. Navigate to Sources → Demo sources visible with `[DEMO]` tag
7. Navigate to Settings → "Clear Demo Data" removes demo sources
8. Create an investigation, add evidence, create a finding, generate a report
9. Export the report as Markdown — file downloads
10. `python -c "from orvia.app.ui.routes import register_routes; print('Routes OK')"` → prints `Routes OK`

---

## Git Tag

```bash
git add -A
git commit -m "Release: ORVIA 1.0.0 — Final"
git tag -a v1.0.0 -m "ORVIA 1.0.0 — Personal Research Intelligence Workspace"
```
