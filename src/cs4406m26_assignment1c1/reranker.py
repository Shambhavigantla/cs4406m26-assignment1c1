"""Feature assembly and comparison helpers for A2 Q2's Stage-2 re-ranker.

Pure functions only -- same contract as bm25.py/embeddings.py/evaluation.py.
The model itself is trained on Kaggle (see src/reranker_training_kaggle.ipynb)
and scored locally through a `score_inview` adapter, so everything here has to
work identically in both places: the training notebook builds its design
matrix with `feature_matrix`, and the serving adapter builds a single
impression's matrix with the same call, guaranteeing the column order the
booster was trained on. See SPEC.md's "A2 Q2" section.
"""

from __future__ import annotations

import numpy as np
import polars as pl

# Behavioural features, produced once per (impression, candidate) by
# src/feature_engineering.ipynb (SPEC.md A2 Q1 #2).
BEHAVIOURAL_FEATURES = [
    "click_count",
    "weighted_category_affinity",
    "weighted_read_time",
    "weighted_scroll_percentage",
    "weighted_embedding_similarity",
    "position_in_impression",
    "clicks_earlier_in_session",
    "session_impressions_so_far",
    "popularity",
    "freshness_hours",
    "category_match",
]

# Stage-1 retrieval signals. Scores come from the existing bm25/embedding
# `score_inview` adapters; the membership flags from the persisted
# `{method}_topk.parquet` corpus-wide top-200 lists (SPEC.md A2 Q1 #1).
RETRIEVAL_FEATURES = [
    "bm25_score",
    "embedding_score",
    "in_bm25_top200",
    "in_embedding_top200",
]

FEATURE_COLUMNS = BEHAVIOURAL_FEATURES + RETRIEVAL_FEATURES

LABEL_COLUMN = "clicked"
KEY_COLUMNS = ["impression_id", "article_id"]


def feature_matrix(df, columns=FEATURE_COLUMNS) -> np.ndarray:
    """`(n_rows, len(columns))` float32 matrix in `columns` order.

    Order is fixed by `FEATURE_COLUMNS` rather than by whatever order the
    caller's frame happens to have, because LightGBM identifies features
    positionally -- a booster trained on one column order and scored on
    another silently produces garbage rather than raising.

    Nulls become NaN, which LightGBM treats as a first-class "missing" value
    and routes at each split. That is what makes a single feature set work
    for both dataset families: MIND has no dwell-time, session, or
    freshness data at all (SPEC.md A2 Q1 #2), so five of these columns are
    entirely null there and simply yield no split gain, rather than needing
    a separate model architecture or a sentinel value that the tree could
    mistake for a real measurement.
    """
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise KeyError(f"feature columns absent from frame: {missing}")

    out = np.empty((df.height, len(columns)), dtype=np.float32)
    for j, name in enumerate(columns):
        series = df[name]
        if series.dtype == bool:
            # cast(Float32) maps null -> NaN; a plain to_numpy() on a boolean
            # column with nulls would raise or coerce nulls to False, which
            # would be a silent lie for MIND's absent flags.
            series = series.cast(float)
        out[:, j] = series.cast(float).to_numpy(allow_copy=True)
    return out


def topk_membership_pairs(topk, flag_name: str):
    """`(user_id, article_id, <flag_name>=True)` pairs from a persisted
    `{method}_topk.parquet`, as a `LazyFrame` to be left-joined onto candidate
    rows (the absent side then fills to `False`).

    A join rather than the obvious `user_id -> set(article_ids)` dict: at
    `ebnerd_large` the top-200 lists hold 164,222,200 article-id entries *per
    method*, so materializing both as Python strings drove the scoring pass to
    a 12.1GB peak with free RAM at 0.3GB. Exploded in Arrow the same data is
    a columnar pair table polars can stream through a join -- the same
    keep-it-in-Arrow rule as SPEC.md A2 Q1 #8.
    """
    lf = topk.lazy() if isinstance(topk, pl.DataFrame) else topk
    # Frame-level .explode(), not pl.col(...).explode() inside a select: the
    # latter cannot broadcast `user_id` against the exploded column and fails
    # with "zip node received non-equal length inputs". Exploding the frame
    # repeats each user_id once per retrieved article, which is the pairing
    # the join needs.
    return (
        lf.select("user_id", "retrieved_article_ids")
        .explode("retrieved_article_ids")
        .rename({"retrieved_article_ids": "article_id"})
        .drop_nulls()
        .unique()
        .with_columns(pl.lit(True).alias(flag_name))
    )


def before_after_comparison_table(before: dict, after: dict, metrics=("auc", "mrr", "ndcg5", "ndcg10")):
    """Rows of `(metric, before, after, delta, pct_change)` for the Q2
    before/after write-up, where `before`/`after` map metric name -> value.

    "Before" is the Stage-1-only ranking already recorded in
    `eval_metrics.json`; "after" is the same impressions re-scored by the
    Stage-2 re-ranker. Metrics absent from either side are skipped rather
    than reported as a zero delta, so a partially-evaluated run cannot look
    like a no-op improvement.
    """
    rows = []
    for metric in metrics:
        if metric not in before or metric not in after:
            continue
        b, a = float(before[metric]), float(after[metric])
        rows.append({
            "metric": metric,
            "before": b,
            "after": a,
            "delta": a - b,
            "pct_change": ((a - b) / b * 100.0) if b else float("nan"),
        })
    return rows
