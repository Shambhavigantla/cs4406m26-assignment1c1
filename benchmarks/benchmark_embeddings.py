"""Verifies SPEC.md Q3 #2's brute-force cosine-similarity timing claim
(~7-12s matmul + ~19-40s top-K selection, under two minutes total, for the
full MIND val/test population) against the real feature store and
embeddings.py module. Mirrors batched_top_k's two internal stages with
separate timers so each half of the claim can be checked independently.

Usage: uv run python benchmarks/benchmark_embeddings.py
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

from cs4406m26_assignment1c1.embeddings import normalize_rows, mean_pool

ROOT = Path(__file__).resolve().parent.parent
RECENT_N_CLICKS = 20
TOPK_MAX = 200
BATCH_SIZE = 2000


def benchmark(dataset: str) -> None:
    processed = ROOT / "data" / "processed" / dataset
    articles = pd.read_parquet(processed / "articles.parquet")
    behaviors = pd.read_parquet(processed / "behaviors.parquet")
    history = pd.read_parquet(processed / "history.parquet")
    embeddings = pd.read_parquet(processed / "article_embeddings.parquet")

    embedding_lookup = dict(zip(embeddings["article_id"], embeddings["embedding"].apply(np.asarray)))
    corpus_matrix = np.stack(articles["article_id"].map(embedding_lookup).to_numpy())
    doc_ids = articles["article_id"].to_numpy()

    val_test_users = behaviors.loc[behaviors["split"].isin(["val", "test"]), "user_id"].unique()
    history_by_user = history.set_index("user_id")["article_id_sequence"]

    query_vectors = []
    for user_id in val_test_users:
        seq = history_by_user.get(user_id)
        if seq is None or len(seq) == 0:
            continue
        recent = list(seq)[-RECENT_N_CLICKS:]
        vector = mean_pool(recent, embedding_lookup)
        if vector is not None:
            query_vectors.append(vector)
    query_matrix = np.stack(query_vectors)

    corpus_unit = normalize_rows(corpus_matrix.astype(np.float32))
    query_unit = normalize_rows(query_matrix.astype(np.float32))
    n_docs = corpus_unit.shape[0]

    matmul_s = 0.0
    topk_s = 0.0
    for start in range(0, len(query_unit), BATCH_SIZE):
        batch = query_unit[start : start + BATCH_SIZE]

        t0 = time.perf_counter()
        scores = batch @ corpus_unit.T
        matmul_s += time.perf_counter() - t0

        t0 = time.perf_counter()
        part = np.argpartition(-scores, TOPK_MAX, axis=1)[:, :TOPK_MAX]
        row_idx = np.arange(part.shape[0])[:, None]
        order = np.argsort(-np.take_along_axis(scores, part, axis=1), axis=1)
        _ = np.take_along_axis(part, order, axis=1)
        topk_s += time.perf_counter() - t0

    print(
        f"[{dataset}] corpus={n_docs} articles, {len(query_unit)} val/test users with a query"
    )
    print(
        f"[{dataset}] matmul: {matmul_s:.1f}s, top-{TOPK_MAX} selection: {topk_s:.1f}s, "
        f"total: {matmul_s + topk_s:.1f}s"
    )


if __name__ == "__main__":
    for dataset in ("ebnerd", "mind"):
        benchmark(dataset)
