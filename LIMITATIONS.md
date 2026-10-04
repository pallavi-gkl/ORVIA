# ORVIA — Limitations

This document describes what ORVIA intentionally does not do and why.

---

## By Design

### No Artificial Intelligence

ORVIA does not use:

- Large language models (GPT, Gemini, Claude, Llama, etc.)
- Embeddings or vector databases
- Semantic similarity search
- Retrieval-augmented generation (RAG)
- AI agents or autonomous reasoning

**Why:** ORVIA is intentionally deterministic. Every result it produces is explainable, reproducible, and auditable. The researcher controls the interpretation.

### No Semantic Understanding

ORVIA's concept extraction uses statistical frequency analysis and multi-word phrase detection, not natural language understanding. It will:

- Extract "climate change" as a concept if it appears frequently
- Not understand that "global warming" and "climate change" are related (unless you manually link them)
- Not infer that a source about "inflation" is relevant to a query about "rising prices"

**What to do instead:** Use the knowledge graph to manually create concept relationships. Use the investigation workspace to explicitly link sources and evidence to your research question.

### No Semantic Search

ORVIA's search engine is a deterministic BM25 full-text search. It:

- Finds documents that contain the exact words you type (with basic stemming)
- Does not understand meaning or intent
- Does not find synonyms unless the source text contains those words

**What to do instead:** Try multiple search terms. Explore via the knowledge graph.

### No Automatic Summarization

ORVIA does not summarize sources. It extracts statistics (word count, reading time, concept frequency) but does not generate summaries. All text in reports comes directly from what you wrote.

### No External Data Sources

ORVIA cannot:

- Fetch web pages
- Connect to databases
- Call external APIs
- Import from citation managers (Zotero, Mendeley) directly

**Supported import formats:** `.txt`, `.csv`, `.json`

### No Cloud Sync

ORVIA is local-first. Your data is stored in a single SQLite file at `data/orvia.db`. There is no cloud backup, no account system, and no sharing feature.

---

## Known Constraints

### Scalability

ORVIA is designed for personal research collections (hundreds to low thousands of sources). Very large collections (10,000+ sources) may experience slower search and analytics performance due to the in-memory index construction approach.

### Concept Extraction Accuracy

The concept extractor uses frequency thresholds and phrase detection heuristics. It will:

- Miss rare but important concepts
- Include common phrases that are not meaningful concepts in your domain
- Produce better results with longer, richer source texts

### Knowledge Graph Completeness

The knowledge graph only shows relationships that can be computed from co-occurrence patterns and explicitly created user links. It does not represent all real-world relationships between concepts.

### Report Quality Indicators

Report quality indicators (evidence coverage, source diversity, etc.) measure structural completeness of your research record, not the truth or accuracy of your research conclusions.

---

## What ORVIA Is Not

- Not a fact-checker
- Not an automatic literature reviewer
- Not a citation manager
- Not a note-taking app (though investigations include notes)
- Not a mind mapping tool (though the knowledge graph is similar)
- Not a writing assistant
- Not a search engine for the web
- Not a replacement for domain expertise
