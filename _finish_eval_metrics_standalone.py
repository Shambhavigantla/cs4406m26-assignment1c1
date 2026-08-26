"""Finishes Q4's eval_metrics.json for one dataset directly from
evaluate_ranking's already-checkpointed parquet files, with no Jupyter/
nbconvert/ZMQ involved at all.

Exists because evaluation_harness.ipynb's remaining downstream cells
(beyond-accuracy metrics, bootstrap CI, write eval_metrics.json) kept
hitting the same intermittent kernel-death (WinError 10055 / DeadKernelError)
this machine has shown throughout Q4's large-scale runs, even after all four
scoring passes were already safely checkpointed to disk (see SPEC.md Q4 #9).
Since evaluate_ranking's checkpoints already carry every column the
remaining steps need (auc/mrr/ndcg5/ndcg10/is_coldstart/is_head/top10_ids),
none of the Jupyter kernel's fragile machinery is actually necessary for
this part -- a plain script sidesteps the unreliable layer entirely instead
of continuing to chase it.

Mirrors evaluation_harness.ipynb's own logic exactly (same category_lookup/
novelty_lookup construction, same leaner per-column-filtering
compute_bootstrap_metrics, same eval_metrics.json schema) so the output is
identical to what the notebook would have produced.

Usage:
    uv run python _finish_eval_metrics_standalone.py <dataset_name>
"""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import json
import sys

import numpy as np
import polars as pl

from cs4406m26_assignment1c1.evaluation import bootstrap_ci, coverage, intra_list_diversity, novelty


def find_repo_root(marker: str = "pyproject.toml") -> Path:
    for parent in [Path.cwd(), *Path.cwd().parents]:
        if (parent / marker).exists():
            return parent
    raise FileNotFoundError(f"could not locate {marker} above {Path.cwd()}")


ROOT = find_repo_root()
DATA_DIR = ROOT / "data" / "processed"
PROGRESS_LOG = ROOT / "build_progress.log"
CHECKPOINT_DIR = DATA_DIR / "_eval_checkpoints"

METHODS = ["bm25", "embedding"]
SPLITS = ["val", "test"]
RECENT_N_CLICKS = 20
NDCG_K_VALUES = [5, 10]
TOP_LIST_K = 10
HEAD_FRACTION = 0.2
BOOTSTRAP_ITERATIONS = 1000
BOOTSTRAP_SEED = 0
METRIC_COLUMNS = ["auc", "mrr", "ndcg5", "ndcg10", "ild", "novelty"]
SLICE_DEFINITIONS = {
    "overall": lambda df: pl.Series([True] * df.height),
    "cold_start": lambda df: df["is_coldstart"],
    "warm": lambda df: ~df["is_coldstart"],
    "head": lambda df: df["is_head"],
    "tail": lambda df: ~df["is_head"],
}


def log_progress(message: str) -> None:
    with PROGRESS_LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.now(timezone.utc).isoformat()}] {message}\n")
        f.flush()


dataset = sys.argv[1]

ckpt_dir = CHECKPOINT_DIR / dataset
missing = [
    ckpt_dir / f"{split}_{method}.parquet"
    for split in SPLITS for method in METHODS
    if not (ckpt_dir / f"{split}_{method}.parquet").exists()
]
if missing:
    raise FileNotFoundError(f"missing checkpoints, run evaluation_harness.ipynb's scoring cells first: {missing}")

log_progress(f"_finish_eval_metrics_standalone: {dataset} started (no Jupyter/nbconvert)")

ranking_results = pl.concat(
    [pl.read_parquet(ckpt_dir / f"{split}_{method}.parquet") for split in SPLITS for method in METHODS]
)
log_progress(f"  {dataset}: loaded {ranking_results.height} rows from 4 checkpoints")

articles = pl.read_parquet(DATA_DIR / dataset / "articles.parquet", columns=["article_id", "category"])
category_lookup = dict(zip(articles["article_id"].to_list(), articles["category"].to_list()))

# novelty_lookup needs train-split click counts -- read only the columns
# needed for that, not the full behaviors table (SPEC.md Q4 #9's memory
# discipline extends to this standalone script too).
train_clicked = (
    pl.scan_parquet(DATA_DIR / dataset / "behaviors.parquet")
    .filter(pl.col("split") == "train")
    .select("article_ids_clicked")
    .collect()["article_ids_clicked"]
    .to_list()
)
train_click_counts = Counter()
for clicked in train_clicked:
    train_click_counts.update(clicked)
train_total_clicks = sum(train_click_counts.values())
del train_clicked

n_articles = len(articles)
smoothed_zero_pop = 1.0 / (train_total_clicks + n_articles)
novelty_lookup = {}
for aid in articles["article_id"].to_list():
    c = train_click_counts.get(aid, 0)
    pop = (c / train_total_clicks) if c > 0 else smoothed_zero_pop
    novelty_lookup[aid] = -np.log2(pop)
del articles
log_progress(f"  {dataset}: category/novelty lookups built from {n_articles} articles")

top10_col = ranking_results["top10_ids"].to_list()
ild_values = [intra_list_diversity(top10, category_lookup) for top10 in top10_col]
novelty_values = [novelty(top10, novelty_lookup) for top10 in top10_col]
del top10_col

ranking_results = ranking_results.with_columns(
    pl.Series("ild", ild_values),
    pl.Series("novelty", novelty_values),
).drop("top10_ids")
log_progress(f"  {dataset}: beyond-accuracy metrics (ild, novelty) computed")


def compute_coverage(method: str) -> float:
    topk_df = pl.read_parquet(DATA_DIR / dataset / f"{method}_topk.parquet")
    return coverage(topk_df["retrieved_article_ids"].to_list(), n_articles)


coverage_metrics = {method: compute_coverage(method) for method in METHODS}
log_progress(f"  {dataset}: coverage computed {coverage_metrics}")


def compute_bootstrap_metrics() -> dict:
    results = {}
    slim = ranking_results.select(["split", "method", "is_coldstart", "is_head", *METRIC_COLUMNS])
    for (split, method), group in slim.group_by(["split", "method"]):
        slices = {}
        for slice_name, mask_fn in SLICE_DEFINITIONS.items():
            is_overall = slice_name == "overall"
            mask = None if is_overall else mask_fn(group)
            n_rows = group.height if is_overall else int(mask.sum())
            slice_metrics = {}
            for metric in METRIC_COLUMNS:
                if n_rows == 0:
                    slice_metrics[metric] = None
                    continue
                col_values = group[metric] if is_overall else group[metric].filter(mask)
                point, lo, hi = bootstrap_ci(
                    col_values.to_numpy(), n_iterations=BOOTSTRAP_ITERATIONS, seed=BOOTSTRAP_SEED,
                    max_chunk_cells=20_000_000,
                )
                slice_metrics[metric] = {"point": point, "ci_lo": lo, "ci_hi": hi}
            slices[slice_name] = slice_metrics
        results.setdefault(method, {})[split] = slices
        log_progress(f"  {dataset}: bootstrap CIs computed for {method}/{split}")
    return results


bootstrap_metrics = compute_bootstrap_metrics()

# Same on-disk-schema check as evaluation_harness.ipynb's test_no_leakage_columns.
expected_behaviors_cols = {
    "impression_id", "dataset", "user_id", "impression_time",
    "article_ids_inview", "article_ids_clicked", "session_id", "split",
}
expected_history_cols = {
    "user_id", "dataset", "article_id_sequence", "timestamp_sequence",
    "read_time_sequence", "scroll_percentage_sequence",
}
forbidden = {"next_read_time", "next_scroll_percentage"}
behaviors_cols = set(pl.read_parquet_schema(DATA_DIR / dataset / "behaviors.parquet"))
history_cols = set(pl.read_parquet_schema(DATA_DIR / dataset / "history.parquet"))
assert behaviors_cols == expected_behaviors_cols
assert history_cols == expected_history_cols
assert forbidden.isdisjoint(behaviors_cols) and forbidden.isdisjoint(history_cols)

out_dir = DATA_DIR / dataset
payload = {
    "schema_version": 1,
    "build_timestamp": datetime.now(timezone.utc).isoformat(),
    "hyperparameters": {
        "recent_n_clicks": RECENT_N_CLICKS,
        "ndcg_k_values": NDCG_K_VALUES,
        "top_list_k": TOP_LIST_K,
        "head_fraction": HEAD_FRACTION,
        "bootstrap_iterations": BOOTSTRAP_ITERATIONS,
    },
    "ranking_metrics": bootstrap_metrics,
    "coverage": coverage_metrics,
    "anti_gaming_confirmed": True,
}
(out_dir / "eval_metrics.json").write_text(json.dumps(payload, indent=2))
log_progress(f"  {dataset}: wrote eval_metrics.json")

# Round-trip check, matching test_eval_metrics_roundtrip's assertions.
reloaded = json.loads((out_dir / "eval_metrics.json").read_text())
assert set(reloaded["ranking_metrics"]) == set(METHODS)
for method in METHODS:
    assert set(reloaded["ranking_metrics"][method]) == set(SPLITS)
    for split in SPLITS:
        assert set(reloaded["ranking_metrics"][method][split]) == set(SLICE_DEFINITIONS)
assert reloaded["coverage"]["bm25"] == coverage_metrics["bm25"]
assert reloaded["coverage"]["embedding"] == coverage_metrics["embedding"]
assert reloaded["anti_gaming_confirmed"] is True

# Checkpoints deliberately NOT deleted here (unlike write_eval_metrics in
# evaluation_harness.ipynb) -- they represent many hours of real compute
# across many crash/retry cycles; clean them up manually once eval_metrics.json
# has actually been eyeballed and looks right, not automatically the moment
# this script's own round-trip check passes.

log_progress(f"_finish_eval_metrics_standalone: {dataset} completed successfully")
print(f"ok: {dataset}'s eval_metrics.json written and round-trips")
