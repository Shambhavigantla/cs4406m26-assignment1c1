"""Verifies the numeric claims in SPEC.md's `A2 Q2` section against the real
feature store, modules and model artifacts.

Usage:
    uv run python benchmarks/verify_a2q2_claims.py [check]

where `check` is one of `throughput`, `adapters`, `paired-ci`,
`data-properties`, `learning-curve`, or `all` (the default).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cs4406m26_assignment1c1.bm25 import build_index, get_scores, tokenize  # noqa: E402
from cs4406m26_assignment1c1.embeddings import (  # noqa: E402
    cosine_similarity_subset,
    mean_pool,
    normalize_rows,
)
from cs4406m26_assignment1c1.evaluation import (  # noqa: E402
    auc_impression,
    bootstrap_ci,
    ndcg_at_k,
    paired_bootstrap_ci,
)
from cs4406m26_assignment1c1.retrieval import build_stage1_scorers  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "processed"
LARGE = ["ebnerd_large", "mind_large"]
RECENT_N = 20

# Full val+test impression counts, from behaviors.parquet (SPEC.md A2 Q2 #7).
FULL_POPULATION = {"ebnerd_large": 1_678_989 + 12_566_385, "mind_large": 431_517 + 376_471}
# SPEC.md A2 Q2 #7: the evaluation pass is the rate that governs the
# full-population decision, and is slower than the training-feature pass.
CLAIMED_RATE = {"ebnerd_large": 430, "mind_large": 283}

CHUNK_LINE = re.compile(
    r"^\[(?P<ts>[^\]]+)\]\s+(?P<stage>reranker_scores:|reranker_eval:)?\s*"
    r"(?P<dataset>[a-z_]+)/(?P<split>[a-z]+): chunk \d+/\d+ checkpointed \((?P<start>\d+)-(?P<end>\d+)"
)
# Only 50,000-impression chunks belong to the two re-ranker scoring passes.
# A1's evaluate_ranking and feature_engineering emit an identically-shaped
# line for 200,000-*row* chunks; counting those together roughly doubles the
# apparent rate, since a feature row is far cheaper than a scored impression.
IMPRESSION_CHUNK = 50_000


def check_throughput() -> None:
    """SPEC.md A2 Q2 #7: the training-feature pass runs at 527 impressions/s
    (ebnerd_large) and 324/s (mind_large); the evaluation pass, which also
    materializes click labels over larger val/test inview sets, runs at
    ~430/s and ~283/s and is the rate the full-population cost is derived
    from.

    Read back from the recorded per-chunk checkpoint timestamps in
    build_progress.log rather than re-measured: re-running the scoring pass
    is the multi-hour cost the sampling decision exists to avoid, and the log
    is the same evidence the claim was derived from.
    """
    print("== Stage-1 scoring throughput (from build_progress.log) ==")
    log = ROOT / "build_progress.log"
    if not log.exists():
        print("  build_progress.log not found -- nothing to verify")
        return
    runs: dict[tuple[str, str, str], list[tuple[datetime, int, int]]] = {}
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        m = CHUNK_LINE.match(line)
        if m and int(m["end"]) - int(m["start"]) == IMPRESSION_CHUNK:
            stage = (m["stage"] or "reranker_scores:").rstrip(":")
            runs.setdefault((stage, m["dataset"], m["split"]), []).append(
                (datetime.fromisoformat(m["ts"]), int(m["start"]), int(m["end"]))
            )

    per_dataset: dict[str, list[float]] = {}
    for (stage, dataset, split), entries in sorted(runs.items()):
        if dataset not in LARGE or len(entries) < 2:
            continue
        rates = []
        for (t0, _, e0), (t1, s1, e1) in zip(entries, entries[1:]):
            seconds = (t1 - t0).total_seconds()
            # Consecutive chunks of the same pass only: a restart resets the
            # offsets, and the gap across a restart is idle time, not work.
            if s1 == e0 and 0 < seconds < 3600:
                rates.append((e1 - s1) / seconds)
        if rates:
            # Only the evaluation pass feeds the extrapolation below.
            if stage == "reranker_eval":
                per_dataset.setdefault(dataset, []).extend(rates)
            print(f"  {stage:16s} {dataset}/{split}: {len(rates)} intervals, median {np.median(rates):7.1f} impressions/s")

    for dataset in LARGE:
        if dataset not in per_dataset:
            print(f"  {dataset}: no evaluation-pass chunk pairs recorded")
            continue
        rate = float(np.median(per_dataset[dataset]))
        hours = FULL_POPULATION[dataset] / rate / 3600
        claimed = CLAIMED_RATE[dataset]
        ok = abs(rate - claimed) / claimed < 0.25
        print(
            f"  {dataset}: measured {rate:6.1f}/s vs claimed {claimed}/s "
            f"-> full val+test ({FULL_POPULATION[dataset]:,} impressions) = {hours:.1f}h  "
            f"[{'OK' if ok else 'MISMATCH'}]"
        )


def check_adapters(dataset: str = "ebnerd") -> None:
    """SPEC.md A2 Q2 #6: the shared module is bit-identical to the training-time
    implementation, and differs from A1's harness by at most float32 epsilon
    with zero ranking-order flips."""
    print(f"== Shared Stage-1 adapters vs both prior implementations ({dataset}) ==")
    d = DATA / dataset
    articles = pl.read_parquet(d / "articles.parquet", columns=["article_id", "title", "abstract"])
    doc_ids = articles["article_id"].to_numpy()
    hist = pl.read_parquet(d / "history.parquet", columns=["user_id", "article_id_sequence"])
    history = dict(zip(hist["user_id"].to_list(), hist["article_id_sequence"].to_list()))
    raw = pl.read_parquet(d / "article_embeddings.parquet")
    id_to_idx = {a: i for i, a in enumerate(doc_ids)}

    texts = (articles["title"].fill_null("") + " " + articles["abstract"].fill_null("")).to_list()
    index = build_index(articles["article_id"].to_list(), [tokenize(t) for t in texts])
    titles = dict(zip(articles["article_id"].to_list(), articles["title"].to_list()))

    def make_embedding_fn(float64_query: bool):
        if float64_query:  # evaluation_harness.ipynb
            lookup = dict(zip(raw["article_id"].to_list(), [np.asarray(v) for v in raw["embedding"].to_list()]))
            matrix = np.stack([lookup[a] for a in doc_ids]).astype(np.float32)
        else:  # reranker_scores.ipynb
            dim = len(raw["embedding"][0])
            block = raw["embedding"].list.to_array(dim).to_numpy().astype(np.float32)
            pos = {a: i for i, a in enumerate(raw["article_id"].to_list())}
            matrix = block[np.array([pos[a] for a in doc_ids])]
            lookup = {a: matrix[i] for i, a in enumerate(doc_ids)}
        unit = normalize_rows(matrix)

        def fn(uid, ids):
            seq = list(history.get(uid, []))[-RECENT_N:]
            scored = cosine_similarity_subset(mean_pool(seq, lookup), unit, doc_ids, id_to_idx, ids)
            return {a: scored.get(a, 0.0) for a in ids}

        return fn

    def reference_bm25(uid, ids):
        seq = list(history.get(uid, []))[-RECENT_N:]
        scores = get_scores(index, tokenize(" ".join(t for t in (titles.get(a, "") for a in seq) if t)))
        return {a: float(scores[id_to_idx[a]]) for a in ids}

    harness_fn = make_embedding_fn(float64_query=True)
    training_fn = make_embedding_fn(float64_query=False)
    shared = build_stage1_scorers(articles, d / "history.parquet", d / "article_embeddings.parquet")

    beh = (
        pl.read_parquet(d / "behaviors.parquet", columns=["user_id", "article_ids_inview", "article_ids_clicked", "split"])
        .filter(pl.col("split") == "val")
        .sort("user_id")
        .head(3000)
    )
    max_bm25 = max_training = max_harness = 0.0
    flips = 0
    auc_shared, auc_harness = [], []
    for uid, inview, clicked in zip(
        beh["user_id"].to_list(), beh["article_ids_inview"].to_list(), beh["article_ids_clicked"].to_list()
    ):
        ids = list(inview)
        max_bm25 = max([max_bm25] + [abs(v - reference_bm25(uid, ids)[k]) for k, v in shared["bm25"](uid, ids).items()])
        s, t, h = shared["embedding"](uid, ids), training_fn(uid, ids), harness_fn(uid, ids)
        max_training = max([max_training] + [abs(s[k] - t[k]) for k in s])
        max_harness = max([max_harness] + [abs(s[k] - h[k]) for k in s])
        a_s = np.array([s[k] for k in ids])
        a_h = np.array([h[k] for k in ids])
        if list(np.argsort(-a_s, kind="stable")) != list(np.argsort(-a_h, kind="stable")):
            flips += 1
        labels = np.array([k in set(clicked) for k in ids])
        auc_shared.append(auc_impression(a_s, labels))
        auc_harness.append(auc_impression(a_h, labels))

    print(f"  impressions compared: {beh.height}")
    print(f"  bm25      vs reranker_scores : max abs diff {max_bm25:.3e}   [{'OK' if max_bm25 == 0 else 'DRIFT'}]")
    print(f"  embedding vs reranker_scores : max abs diff {max_training:.3e}   [{'OK' if max_training == 0 else 'DRIFT'}]")
    print(f"  embedding vs evaluation_harness (float64 query): max abs diff {max_harness:.3e}")
    print(f"  ranking-order flips vs harness: {flips}/{beh.height}   [{'OK' if flips == 0 else 'FLIPS'}]")
    print(f"  mean per-impression AUC: shared {np.mean(auc_shared):.10f}  harness {np.mean(auc_harness):.10f}")


def check_paired_ci() -> None:
    """SPEC.md A2 Q2 #8: covers a known +0.02 effect, excludes zero, ~6.7x
    tighter than the unpaired interval, chunked equals unchunked."""
    print("== paired_bootstrap_ci ==")
    rng = np.random.default_rng(7)
    n = 20_000
    difficulty = rng.normal(0.55, 0.20, n)
    a = np.clip(difficulty + rng.normal(0, 0.02, n), 0, 1)
    b = np.clip(difficulty + 0.02 + rng.normal(0, 0.02, n), 0, 1)

    diff, lo, hi = paired_bootstrap_ci(a, b, 1000, 0)
    print(f"  true effect +0.0200 -> {diff:+.5f} [{lo:+.5f}, {hi:+.5f}]  "
          f"covers={'OK' if lo < 0.02 < hi else 'NO'}  excludes_zero={'OK' if lo > 0 else 'NO'}")
    _, la, ha = bootstrap_ci(a, 1000, 0)
    print(f"  paired width {hi - lo:.5f} vs unpaired width {ha - la:.5f} -> {(ha - la) / (hi - lo):.1f}x tighter")
    c = np.clip(difficulty + rng.normal(0, 0.02, n), 0, 1)
    _, lo0, hi0 = paired_bootstrap_ci(a, c, 1000, 0)
    print(f"  no-effect pair -> [{lo0:+.5f}, {hi0:+.5f}]  contains_zero={'OK' if lo0 < 0 < hi0 else 'NO'}")
    same = paired_bootstrap_ci(a, b, 1000, 0) == paired_bootstrap_ci(a, b, 1000, 0, max_chunk_cells=n * 7)
    print(f"  chunked == unchunked: {'OK' if same else 'MISMATCH'}")


def check_data_properties() -> None:
    """SPEC.md A2 Q2 #11: duplicate clicks, clicked-in-inview, nDCG@10 < nDCG@5."""
    print("== Dataset properties the assertions encode ==")
    for dataset in ["ebnerd", *LARGE]:
        path = DATA / dataset / "behaviors.parquet"
        if not path.exists():
            continue
        for split in ["val", "test"]:
            b = (
                pl.scan_parquet(path)
                .filter(pl.col("split") == split)
                .select("article_ids_inview", "article_ids_clicked")
                .collect()
            )
            duplicates = int(
                (b["article_ids_clicked"].list.len() - b["article_ids_clicked"].list.unique().list.len()).sum()
            )
            outside = int(
                b.select(
                    pl.col("article_ids_clicked").list.set_difference(pl.col("article_ids_inview")).list.len()
                ).to_series().sum()
            )
            max_clicks = int(b["article_ids_clicked"].list.unique().list.len().max())
            print(
                f"  {dataset}/{split}: duplicate clicked entries {duplicates:>7,}   "
                f"clicked outside inview {outside:>3}   max distinct clicks/impression {max_clicks:>2}"
            )

    scores = np.array([9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0, 0.5, 0.1])
    labels = np.array([1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 1], dtype=bool)
    n5, n10 = ndcg_at_k(scores, labels, 5), ndcg_at_k(scores, labels, 10)
    print(f"  constructed 6-click impression: nDCG@5 {n5:.4f}  nDCG@10 {n10:.4f}  "
          f"ndcg10 < ndcg5 = {'OK' if n10 < n5 else 'NO'}")

    lengths = pl.Series("len", [3, 4, 5], dtype=pl.UInt32).to_numpy()
    naive = np.concatenate([[0], np.cumsum(lengths)]).dtype
    pinned = np.concatenate([[0], np.cumsum(lengths, dtype=np.int64)]).dtype
    print(f"  polars UInt32 len -> np.cumsum: naive concat dtype {naive}, pinned {pinned}  "
          f"[{'OK' if naive == np.float64 and pinned == np.int64 else 'UNEXPECTED'}]")


def check_learning_curve() -> None:
    """SPEC.md A2 Q2 #9: the curve is flat to slightly declining at 400k."""
    print("== Re-ranker learning curve and feature importances ==")
    for dataset in LARGE:
        path = DATA / dataset / f"reranker_metadata_{dataset}.json"
        if not path.exists():
            print(f"  {dataset}: no metadata (run the Kaggle training notebook first)")
            continue
        meta = json.loads(path.read_text(encoding="utf-8"))
        print(f"  {dataset}: best_iteration {meta['best_iteration']} of {meta['num_boost_round']} rounds")
        previous = None
        for point in meta["learning_curve"]:
            arrow = "" if previous is None else f"  ({point['val_auc_per_impression'] - previous:+.4f})"
            print(f"    {point['impressions']:>7,} impressions -> val AUC {point['val_auc_per_impression']:.4f}{arrow}")
            previous = point["val_auc_per_impression"]
        curve = [p["val_auc_per_impression"] for p in meta["learning_curve"]]
        if len(curve) > 1:
            print(f"    net change 100k -> 400k: {curve[-1] - curve[0]:+.4f} "
                  f"({'flat or declining' if curve[-1] <= curve[0] else 'still improving'})")
        zero_gain = [n for n, g in meta["feature_importance_gain"] if g == 0.0]
        print(f"    zero-gain features ({len(zero_gain)}): {', '.join(zero_gain) or 'none'}")


CHECKS = {
    "throughput": check_throughput,
    "adapters": check_adapters,
    "paired-ci": check_paired_ci,
    "data-properties": check_data_properties,
    "learning-curve": check_learning_curve,
}


def main() -> int:
    requested = sys.argv[1] if len(sys.argv) > 1 else "all"
    if requested not in CHECKS and requested != "all":
        print(f"unknown check {requested!r}; expected one of {', '.join(CHECKS)} or all")
        return 2
    for name, fn in CHECKS.items():
        if requested in (name, "all"):
            fn()
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
