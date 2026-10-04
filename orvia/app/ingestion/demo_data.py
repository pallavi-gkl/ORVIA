"""
Realistic Research Demonstration Datasets for ORVIA Source Intelligence.
Contains technical research notes across Transformers, Python Internals, AI Agents, and RAG.
Can be seeded on demand via the UI or CLI.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orvia.app.ingestion.service import SourceImportService
    from orvia.app.ingestion.importers.base_importer import ImportResult

logger = logging.getLogger(__name__)

DEMO_DATASETS = [
    {
        "filename": "transformer_attention_mechanisms.txt",
        "title": "Transformer Attention Mechanisms & Scaling",
        "content": """# Transformer Attention Mechanisms & Computational Scaling

## Abstract
The scaled dot-product attention formulation serves as the mathematical foundation for modern sequence modeling.
This research synthesis inspects the computational complexity, query-key interaction dynamics, and recent memory-efficient optimizations including FlashAttention.

## Mathematical Formulation
Given an input sequence representations matrix X in R^{N x d}, linear projections yield:
- Queries: Q = X * W_Q
- Keys:    K = X * W_K
- Values:  V = X * W_V

The core attention equation is computed as:
Attention(Q, K, V) = softmax((Q * K^T) / sqrt(d_k)) * V

Where:
1. d_k represents the head dimension, acting as a variance scaling factor.
2. The term (Q * K^T) computes pairwise dot products reflecting affinity or relevance between all token pairs.
3. Softmax normalizes row sums to unity, creating a probability distribution over input context positions.

## Quadratic Bottleneck
The self-attention matrix S = Q * K^T requires O(N^2) memory allocations and O(N^2 * d) floating point operations.
When processing long contexts (e.g. 32k to 1M tokens), memory bandwidth constraints between HBM (High Bandwidth Memory) and SRAM on GPU architectures dominate runtime latency.

## FlashAttention Paradigm
FlashAttention reorganizes the attention computation using GPU SRAM tiling:
- Splits Q, K, and V into blocks that fit within on-chip SRAM.
- Computes partial softmax denominators using the online softmax trick.
- Eliminates the need to materialize the full N x N attention matrix to HBM.
- Reduces memory accesses by an order of magnitude while maintaining mathematical exactness.

## Comparative Summary
- Standard Attention: O(N^2) memory, bounded by memory bandwidth.
- FlashAttention-2: Exact computation, 2x speedup over FA-1, optimized warp specialization.
- Multi-Query Attention (MQA): Shares single K and V head across all Q heads, reducing KV cache footprint.
- Grouped-Query Attention (GQA): Compromise between MHA and MQA with G key-value groups.
""",
    },
    {
        "filename": "python_async_internals.txt",
        "title": "Python Asyncio Internals & Task Scheduling",
        "content": """# Python Asyncio Internals: Event Loops and Coroutines

## Overview
Python's asynchronous programming model (`asyncio`) provides cooperative multitasking via a single-threaded event loop.
Understanding its underlying generators, futures, and task lifecycle is critical for architecting high-throughput I/O pipelines.

## Coroutine Architecture
A Python coroutine is declared using `async def` and is compiled into a code object with the `CO_COROUTINE` flag.
Under the hood:
1. Invoking a coroutine function returns a coroutine object; it does not begin execution immediately.
2. The `await` keyword yields execution back to the event loop until the underlying `Future` or `Task` is marked complete.
3. Python implements coroutines as stateful generators yielding control via the C-level `tp_iternext` slot.

## The Event Loop Lifecycle
The event loop maintains two primary queues:
- Ready Queue: Callbacks and coroutines ready to run in the current iteration tick.
- Scheduled Queue: Timed handles (call_later, call_at) stored in a binary min-heap sorted by target timestamp.

In each iteration cycle, the loop:
1. Evaluates expired timers from the min-heap.
2. Polls OS I/O multiplexers (epoll on Linux, kqueue on macOS, I/O Completion Ports on Windows) with a calculated timeout.
3. Dispatches ready I/O callbacks.
4. Executes tasks on the ready queue until exhausted.

## Performance Considerations
- CPU-bound operations in the event loop block all cooperative tasks.
- Cooperative yield points (`await asyncio.sleep(0)`) allow other pending coroutines to execute during tight loops.
- Use `asyncio.to_thread()` or `ProcessPoolExecutor` to offload blocking filesystem or computational workloads.
""",
    },
    {
        "filename": "ai_agent_architectures.json",
        "title": "AI Agent Cognitive Architectures & Benchmarks",
        "content": """{
  "system": "ORVIA Research Dataset",
  "category": "Cognitive Agent Architectures",
  "version": "2026.1",
  "paradigms": [
    {
      "name": "ReAct",
      "description": "Interleaved Reasoning and Acting loops",
      "cycles": ["Thought", "Action", "Observation"],
      "strengths": ["Interpretability", "Error recovery", "Human trace inspection"],
      "benchmark_scores": {
        "hotpot_qa_f1": 68.4,
        "fever_accuracy": 72.1,
        "alfworld_success_rate": 84.0
      }
    },
    {
      "name": "Reflexion",
      "description": "Verbal reinforcement learning with self-reflection memory",
      "cycles": ["Trial", "Evaluate", "Self-Reflect", "Retry"],
      "strengths": ["Self-correction without fine-tuning", "Long-term heuristics storage"],
      "benchmark_scores": {
        "hotpot_qa_f1": 74.9,
        "fever_accuracy": 78.5,
        "alfworld_success_rate": 97.0
      }
    },
    {
      "name": "Plan-and-Solve",
      "description": "Explicit macro-planning followed by sub-task execution",
      "cycles": ["Devise Plan", "Execute Step", "Synthesize Final Answer"],
      "strengths": ["Reduced hallucination on multi-step reasoning", "Lower token consumption"],
      "benchmark_scores": {
        "hotpot_qa_f1": 71.2,
        "fever_accuracy": 75.3,
        "alfworld_success_rate": 88.5
      }
    }
  ],
  "common_failure_modes": [
    "Context drift during prolonged execution chains",
    "Repeated action loops on ambiguous tool outputs",
    "Overconfidence in unverified intermediate evidence"
  ]
}""",
    },
    {
        "filename": "rag_retrieval_benchmarks.csv",
        "title": "RAG Retrieval Benchmarks & Latency Evaluation",
        "content": """retriever_type,top_k,recall_at_5,mrr_at_10,p99_latency_ms,index_size_mb
BM25_Lexical,5,0.712,0.645,4.2,42.0
Dense_BGE_Large,5,0.841,0.782,38.5,1240.0
Dense_E5_Small,5,0.795,0.729,14.1,380.0
Hybrid_RRF_BM25_BGE,5,0.892,0.834,44.8,1282.0
ColBERT_Late_Interaction,5,0.915,0.867,62.3,3400.0
Parent_Document_Retrieval,5,0.864,0.801,29.4,850.0
Contextual_Compression,5,0.881,0.819,78.2,1240.0
""",
    },
]


def seed_demo_sources(service: SourceImportService, force: bool = False) -> list[ImportResult]:
    """Import the pre-configured research demo datasets into the workspace."""
    results = []
    for item in DEMO_DATASETS:
        res = service.import_source(
            file_bytes=item["content"].encode("utf-8"),
            filename=item["filename"],
            force_duplicate=force,
            custom_title=item["title"],
        )
        results.append(res)
        logger.info("Demo source %s: success=%s", item["filename"], res.success)
    return results


if __name__ == "__main__":
    from pathlib import Path
    from orvia.app.core.config import Config
    from orvia.app.core.database import DatabaseManager
    from orvia.app.repositories.source_repository import SourceRepository
    from orvia.app.ingestion.service import SourceImportService

    config = Config.from_env()
    db = DatabaseManager(config.DATABASE_PATH)
    db.connect()
    db.initialize_schema()
    repo = SourceRepository(db)
    srv = SourceImportService(repo)
    results = seed_demo_sources(srv, force=False)
    print(f"Imported {sum(1 for r in results if r.success)} demo sources.")
    db.disconnect()
