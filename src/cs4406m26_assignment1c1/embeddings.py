"""Mean-pooled user representation + batched brute-force cosine-similarity
retrieval over precomputed article embeddings.

No embedding-model dependency lives here -- the vectors themselves are
computed on Kaggle (see SPEC.md Q3 section 1); this module only does vector
math on embeddings that already exist.
"""

from __future__ import annotations

import numpy as np


def mean_pool(article_ids, embedding_lookup: dict[str, np.ndarray]) -> np.ndarray | None:
    vectors = [embedding_lookup[aid] for aid in article_ids if aid in embedding_lookup]
    if not vectors:
        return None
    return np.mean(vectors, axis=0)


def weighted_mean_pool(article_ids, weights, embedding_lookup: dict[str, np.ndarray]) -> np.ndarray | None:
    """Recency-weighted generalization of `mean_pool` (A2 SPEC.md Q1 #5) --
    uniform weights must reduce to `mean_pool`'s exact output, checked by a
    regression test wherever this is used. Falls back to an unweighted mean
    if every matched weight is zero (an all-zero weight vector has no valid
    weighted average, not that the history is uninformative)."""
    pairs = [(embedding_lookup[aid], w) for aid, w in zip(article_ids, weights) if aid in embedding_lookup]
    if not pairs:
        return None
    vectors, matched_weights = zip(*pairs)
    matched_weights = np.asarray(matched_weights, dtype=np.float64)
    if matched_weights.sum() == 0:
        return np.mean(vectors, axis=0)
    return np.average(vectors, axis=0, weights=matched_weights)


def normalize_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def batched_top_k(
    query_matrix: np.ndarray,
    corpus_matrix: np.ndarray,
    doc_ids: np.ndarray,
    k: int,
    batch_size: int = 2000,
) -> list[list[tuple[str, float]]]:
    """Within one call, results are exact (verified against a naive full
    sort). Scores from two *separate* calls with different batch shapes for
    the same logical query can differ at the float32-epsilon level (BLAS
    GEMM isn't bit-exact across different matrix shapes), which can reorder
    near-tied candidates -- not a correctness bug, just don't compare
    top-K across separately-shaped calls. The real pipeline never needs to:
    call once at TOPK_MAX and slice prefixes for smaller K, which is exact
    by construction.
    """
    n_docs = corpus_matrix.shape[0]
    corpus_unit = normalize_rows(corpus_matrix.astype(np.float32))
    query_unit = normalize_rows(query_matrix.astype(np.float32))

    results: list[list[tuple[str, float]]] = []
    for start in range(0, len(query_unit), batch_size):
        batch = query_unit[start : start + batch_size]
        scores = batch @ corpus_unit.T  # (batch, n_docs) cosine similarities

        if k >= n_docs:
            top_idx = np.argsort(-scores, axis=1)
        else:
            part = np.argpartition(-scores, k, axis=1)[:, :k]
            row_idx = np.arange(part.shape[0])[:, None]
            order = np.argsort(-np.take_along_axis(scores, part, axis=1), axis=1)
            top_idx = np.take_along_axis(part, order, axis=1)

        for row_scores, idx_row in zip(scores, top_idx):
            results.append([(doc_ids[i], float(row_scores[i])) for i in idx_row])
    return results


def cosine_similarity_subset(
    query_vector: np.ndarray | None,
    corpus_unit: np.ndarray,
    doc_ids: np.ndarray,
    id_to_idx: dict[str, int],
    subset_ids: list[str],
) -> dict[str, float]:
    """`corpus_unit` must already be row-normalized (via `normalize_rows`) and
    `id_to_idx` must map every `doc_ids[i] -> i` -- both precomputed *once* by
    the caller and reused across calls. An earlier version rebuilt
    `id_to_idx` (a dict over the whole corpus) and re-normalized the
    corpus-subset on every call; at ebnerd_large's Q4/Q5 re-ranking scale
    (12.5M+ calls against a 125,541-doc corpus), rebuilding a 125,541-entry
    dict per call was the dominant cost of the whole scoring pass -- see
    SPEC.md Q4 #9."""
    if query_vector is None:
        return {}
    idxs = [id_to_idx[aid] for aid in subset_ids if aid in id_to_idx]
    if not idxs:
        return {}

    sub_unit = corpus_unit[idxs]
    q_norm = np.linalg.norm(query_vector)
    q_unit = (query_vector / q_norm if q_norm else query_vector).astype(np.float32)
    scores = sub_unit @ q_unit
    return {doc_ids[idxs[i]]: float(scores[i]) for i in range(len(idxs))}
