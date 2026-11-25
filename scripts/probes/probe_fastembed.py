"""Probe fastembed's embedder and reranker on this machine.

Measures, for one model chosen on the command line:
- load time and the on-disk size of the downloaded model,
- embedding (or reranking) speed,
- peak memory of this Python process,
- a sanity check that the right document ranks first.

Run from the repository root in a throwaway environment, so the project gains no dependency:

    uv run --no-project --with fastembed python scripts/probes/probe_fastembed.py \
        embed BAAI/bge-small-en-v1.5
    uv run --no-project --with fastembed python scripts/probes/probe_fastembed.py \
        rerank jinaai/jina-reranker-v1-tiny-en

Downloaded models go to scripts/probes/model_cache/, which git ignores; delete it afterwards.
Results from 2026-11-25 are recorded in
docs/decisions/0010-lightweight-embedding-and-reranking-models.md.
"""

import resource
import sys
import time
from pathlib import Path

import numpy as np

CACHE_ROOT = Path(__file__).parent / "model_cache"
CACHE_DIR = CACHE_ROOT  # replaced per model in __main__

DOCUMENTS = [
    "CMake: set CMAKE_BUILD_TYPE=Release to build with optimizations enabled.",
    "Bazel: pass --config=asan to build and test with AddressSanitizer.",
    "Release 4.2 notes: the ingest command now skips unchanged files by hash.",
    "CI failure: linker error 'undefined reference to pthread_create'. Fix: link with -pthread.",
    "Bazel remote cache: set --remote_cache to a gRPC endpoint to share build outputs.",
]
QUERY = "Which flag enables AddressSanitizer in Bazel?"
EXPECTED_BEST = 1  # index of the AddressSanitizer document


def peak_memory_mb() -> float:
    """Return this process's peak resident memory in MB on macOS or Linux."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # ru_maxrss is in bytes on macOS but in kibibytes on Linux.
    if sys.platform == "darwin":
        return peak / (1024 * 1024)
    return peak / 1024


def folder_size_mb(folder: Path) -> float:
    """Return the total size of all files under a folder in MB."""
    total = 0
    for path in folder.rglob("*"):
        # The Hugging Face cache links snapshots/ to blobs/; count real files only once.
        if path.is_file() and not path.is_symlink():
            total += path.stat().st_size
    return total / (1024 * 1024)


def make_chunks(count: int) -> list[str]:
    """Build synthetic chunks of roughly 250 tokens each for the speed test."""
    chunks = []
    for number in range(count):
        base = DOCUMENTS[number % len(DOCUMENTS)]
        chunks.append((base + " ") * 12)
    return chunks


def probe_embedder(model_name: str) -> None:
    """Load an embedding model, time it, and check the ranking of the sample query."""
    from fastembed import TextEmbedding

    start = time.perf_counter()
    model = TextEmbedding(model_name=model_name, cache_dir=str(CACHE_DIR))
    print("load seconds:", round(time.perf_counter() - start, 2))
    print("model files MB:", round(folder_size_mb(CACHE_DIR), 1))

    document_vectors = np.array(list(model.embed(DOCUMENTS)))
    print("dimension:", document_vectors.shape[1])

    timings = []
    for _ in range(20):
        start = time.perf_counter()
        query_vector = np.array(list(model.query_embed(QUERY)))[0]
        timings.append((time.perf_counter() - start) * 1000)
    timings.sort()
    print("query embed ms p50:", round(timings[10], 1), "p95:", round(timings[18], 1))

    # Vectors are normalized, so the dot product is the cosine similarity.
    scores = document_vectors @ query_vector
    best = int(np.argmax(scores))
    print("cosine scores:", [round(float(score), 3) for score in scores])
    print("best document:", best, "expected:", EXPECTED_BEST, "ok:", best == EXPECTED_BEST)

    chunks = make_chunks(500)
    start = time.perf_counter()
    list(model.embed(chunks, batch_size=32))
    seconds = time.perf_counter() - start
    print(
        "embed 500 chunks (~250 tokens) seconds:",
        round(seconds, 1),
        "chunks/s:",
        round(500 / seconds, 1),
    )
    print("peak memory MB:", round(peak_memory_mb()))


def probe_reranker(model_name: str) -> None:
    """Load a cross-encoder, time reranking 20 candidates, and check the top result."""
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    start = time.perf_counter()
    model = TextCrossEncoder(model_name=model_name, cache_dir=str(CACHE_DIR))
    print("load seconds:", round(time.perf_counter() - start, 2))
    print("model files MB:", round(folder_size_mb(CACHE_DIR), 1))

    scores = list(model.rerank(QUERY, DOCUMENTS))
    best = int(np.argmax(scores))
    print("rerank scores:", [round(float(score), 3) for score in scores])
    print("best document:", best, "expected:", EXPECTED_BEST, "ok:", best == EXPECTED_BEST)

    candidates = make_chunks(20)
    timings = []
    for _ in range(10):
        start = time.perf_counter()
        list(model.rerank(QUERY, candidates))
        timings.append((time.perf_counter() - start) * 1000)
    timings.sort()
    print(
        "rerank 20 candidates (~250 tokens) ms p50:",
        round(timings[5], 1),
        "max:",
        round(timings[9], 1),
    )
    print("peak memory MB:", round(peak_memory_mb()))


if __name__ == "__main__":
    kind = sys.argv[1]
    name = sys.argv[2]
    # One cache folder per model, so the measured size is that model alone.
    CACHE_DIR = CACHE_ROOT / name.replace("/", "__")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print("==", kind, name)
    if kind == "embed":
        probe_embedder(name)
    else:
        probe_reranker(name)
