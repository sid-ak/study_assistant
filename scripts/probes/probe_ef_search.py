"""Probe how ``hnsw.ef_search`` changes the HNSW index's recall and speed on the ingested corpus.

For every section heading path in the corpus, the probe embeds it as a query and takes the top 5
chunks twice:

- Exact: a sequential scan that compares the query with every chunk.
- Index: the HNSW index, forced with ``enable_seqscan = off`` and run once per ``ef_search`` value.

It prints recall@5 of each index run against the exact run (the share of the exact top 5 the index
also returned) and the median time of the SQL query alone.

Run from the repository root after ``uv run study ingest corpus/release_engineering``:

    uv run python scripts/probes/probe_ef_search.py

Results from 2026-11-25, on 83 chunks, are recorded in the pull request for issue #46.
"""

import time

from pgvector import Vector

from rag_core.config import Settings
from rag_core.embed import FastembedEmbedder
from rag_core.store import Store
from rag_core.store.schema import embedding_column

EF_SEARCH_VALUES = [5, 10, 20, 40, 100]
TOP_K = 5


def median(values: list[float]) -> float:
    """The middle value of ``values`` after sorting (the upper middle for an even count)."""
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def main() -> None:
    """Embed the corpus's heading paths as queries and compare index results with exact ones."""
    settings = Settings()
    embedder = FastembedEmbedder.from_settings(settings)
    store = Store(settings.database_url, embedder=embedder.info)
    column = embedding_column(embedder.info.model_id)
    search_sql = (
        f"SELECT id FROM chunks WHERE {column} IS NOT NULL ORDER BY {column} <=> %s LIMIT {TOP_K}"
    )

    with store.get_connection() as conn:
        rows = conn.execute("SELECT DISTINCT metadata->'headings' AS headings FROM chunks")
        queries: list[str] = []
        for row in rows.fetchall():
            if row["headings"]:
                queries.append(" ".join(row["headings"]))
        vectors: list[Vector] = []
        for query in queries:
            vectors.append(Vector(embedder.embed_query(query)))

        def run_all() -> tuple[list[set[str]], float]:
            """Top-k ids for every query under the session's settings, and the median ms."""
            results: list[set[str]] = []
            timings: list[float] = []
            for vector in vectors:
                started = time.perf_counter()
                found = conn.execute(search_sql, (vector,)).fetchall()
                timings.append((time.perf_counter() - started) * 1000)
                ids: set[str] = set()
                for found_row in found:
                    ids.add(str(found_row["id"]))
                results.append(ids)
            return results, median(timings)

        conn.execute("SET enable_indexscan = off")
        exact, exact_ms = run_all()
        print(f"{len(queries)} queries; exact search median {exact_ms:.2f} ms")

        conn.execute("SET enable_indexscan = on")
        conn.execute("SET enable_seqscan = off")
        for ef_search in EF_SEARCH_VALUES:
            conn.execute(f"SET hnsw.ef_search = {ef_search}")
            found_by_index, index_ms = run_all()
            hits = 0
            for wanted, got in zip(exact, found_by_index, strict=True):
                hits += len(wanted & got)
            recall = hits / (TOP_K * len(queries))
            label = f"ef_search {ef_search:>3}"
            print(f"{label}: recall@{TOP_K} {recall:.3f}, median {index_ms:.2f} ms")


if __name__ == "__main__":
    main()
