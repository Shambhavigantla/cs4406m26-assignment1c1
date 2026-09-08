"""Ranking-quality and beyond-accuracy metrics for the Q4 evaluation harness.

Pure functions only -- reusable and unit-testable like bm25.py/embeddings.py,
but with a correctness (not raw-performance) requirement. See SPEC.md Q4 for
formulas and the candidate-generation-vs-re-ranking framing these operate in.
"""

from __future__ import annotations

from collections import Counter

import numpy as np


def _rank_avg(scores: np.ndarray) -> np.ndarray:
    """1-indexed ranks, ascending by score, with ties given the average rank
    of their tied group (standard tie-handling for the AUC rank-sum form)."""
    order = np.argsort(scores, kind="stable")
    sorted_scores = scores[order]
    ranks = np.empty(len(scores), dtype=np.float64)
    n = len(scores)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sorted_scores[j + 1] == sorted_scores[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + 1 + j + 1) / 2.0
        i = j + 1
    return ranks


def auc_impression(scores, labels) -> float:
    scores = np.asarray(scores, dtype=np.float64)
    labels = np.asarray(labels, dtype=bool)
    n_pos = int(labels.sum())
    n_neg = len(labels) - n_pos
    if n_pos == 0 or n_neg == 0:
        raise ValueError("AUC is undefined without both a click and a non-click in the inview set")
    ranks = _rank_avg(scores)
    rank_sum_pos = ranks[labels].sum()
    return (rank_sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def mrr(scores, labels) -> float:
    scores = np.asarray(scores, dtype=np.float64)
    labels = np.asarray(labels, dtype=bool)
    order = np.argsort(-scores, kind="stable")
    hit_positions = np.flatnonzero(labels[order])
    if len(hit_positions) == 0:
        raise ValueError("MRR is undefined without at least one click in the inview set")
    return 1.0 / (hit_positions[0] + 1)


def ndcg_at_k(scores, labels, k: int) -> float:
    scores = np.asarray(scores, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.float64)
    order = np.argsort(-scores, kind="stable")
    ranked_labels = labels[order][:k]
    dcg = float((ranked_labels / np.log2(np.arange(2, len(ranked_labels) + 2))).sum())

    n_pos = int(labels.sum())
    ideal_len = min(n_pos, k)
    if ideal_len == 0:
        raise ValueError("nDCG is undefined without at least one click in the inview set")
    idcg = float((1.0 / np.log2(np.arange(2, ideal_len + 2))).sum())
    return dcg / idcg


def bootstrap_ci(
    values, n_iterations: int = 1000, seed: int | None = None, max_chunk_cells: int = 200_000_000
) -> tuple[float, float, float]:
    """Resample-with-replacement over `values` (one row per impression already
    computed once); returns (point_estimate, ci_lo, ci_hi) at the 95% level.
    Undefined (raises) for an empty slice -- callers with a legitimately empty
    slice (e.g. EB-NeRD's 0 cold-start users) should check for that themselves
    rather than get a silently degenerate CI back.

    Processes iterations in chunks bounded by `max_chunk_cells` (resample-index
    array cells, int32) rather than allocating one `(n_iterations, len(values))`
    array up front -- at ebnerd_large's test-split scale (~12.5M impressions),
    the naive single-shot array would be ~1000 * 12.5M * 8 bytes =~ 100GB.
    Chunking keeps peak memory bounded regardless of dataset size; for every
    dataset this project used before ebnerd_large, n_iterations * len(values)
    is already under max_chunk_cells, so this is a single chunk exactly like
    the original one-shot implementation (no behavior change)."""
    values = np.asarray(values, dtype=np.float64)
    n = len(values)
    if n == 0:
        raise ValueError("bootstrap_ci is undefined for an empty slice")
    point = float(values.mean())
    if n == 1:
        return point, point, point
    rng = np.random.default_rng(seed)
    iters_per_chunk = max(1, max_chunk_cells // n)
    resample_means = np.empty(n_iterations, dtype=np.float64)
    start = 0
    while start < n_iterations:
        end = min(start + iters_per_chunk, n_iterations)
        resample_idx = rng.integers(0, n, size=(end - start, n), dtype=np.int32)
        resample_means[start:end] = values[resample_idx].mean(axis=1)
        start = end
    lo, hi = np.percentile(resample_means, [2.5, 97.5])
    return point, float(lo), float(hi)


def intra_list_diversity(article_ids, category_lookup: dict) -> float:
    """1 - same_category(i,j) averaged over all pairs in the list. 0.0 for a
    list shorter than 2 items (no pairs) or an all-same-category list."""
    categories = [category_lookup.get(aid) for aid in article_ids]
    n = len(categories)
    if n < 2:
        return 0.0
    total = 0.0
    n_pairs = 0
    for i in range(n):
        for j in range(i + 1, n):
            total += 0.0 if categories[i] == categories[j] else 1.0
            n_pairs += 1
    return total / n_pairs


def novelty(article_ids, novelty_lookup: dict) -> float:
    """Mean of precomputed per-article novelty scores (-log2(train popularity),
    add-one-smoothed for never-clicked items -- see SPEC.md Q4 #3) over the list."""
    values = [novelty_lookup[aid] for aid in article_ids if aid in novelty_lookup]
    if not values:
        return 0.0
    return float(np.mean(values))


def train_click_counts(train_clicked_lists) -> Counter:
    """Per-article train-split click counts from an iterable of per-impression
    clicked-id lists. Callers that can count more cheaply (e.g. a columnar
    `explode().value_counts()`) should do so and pass the result straight to
    `train_popularity_lookup` -- the formula, not the counting, is what has
    to stay shared."""
    counts = Counter()
    for clicked in train_clicked_lists:
        counts.update(clicked)
    return counts


def train_popularity_lookup(article_ids, click_counts) -> dict:
    """Add-one-smoothed train-split click popularity: `clicks_train(item) /
    total_train_clicks` for ever-clicked items, `1 / (total + n_articles)`
    for never-clicked items. Shared basis for Q4's `novelty` metric
    (`-log2(pop)`) and A2 Q1's `popularity` feature (`pop` itself) -- factored
    out so both are computed once, the same way (A2 SPEC.md Q1 #7).

    Takes an already-built `article_id -> count` mapping rather than the raw
    per-impression lists: at ebnerd_large's 10,384,901-row train split,
    materializing those lists as Python objects purely to count them is a
    multi-GB cost the caller can avoid entirely (see A2 SPEC.md Q1 #8)."""
    total = sum(click_counts.values())
    n_articles = len(article_ids)
    smoothed_zero_pop = 1.0 / (total + n_articles)
    return {
        aid: (click_counts[aid] / total if click_counts.get(aid, 0) > 0 else smoothed_zero_pop)
        for aid in article_ids
    }


def coverage(retrieved_id_lists, n_articles: int) -> float:
    covered: set = set()
    for ids in retrieved_id_lists:
        covered.update(ids)
    return len(covered) / n_articles
