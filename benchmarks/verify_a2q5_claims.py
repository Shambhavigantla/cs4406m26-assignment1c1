"""Prints and cross-checks the A2 Q5 extended evaluation (all metrics, all
slices, bootstrap CIs) for the two-stage pipeline, read from
data/processed/{dataset}/reranker_eval_metrics.json.

Usage: uv run python benchmarks/verify_a2q5_claims.py [dataset ...]
       uv run python benchmarks/verify_a2q5_claims.py head-diagnostic [dataset] [split]
       uv run python benchmarks/verify_a2q5_claims.py submissions [population ...]

Cross-check: A1's eval_metrics.json holds ILD and novelty for the bm25 and
embedding baselines over the FULL val/test populations. The same two methods
are re-measured here on the 200,000-impression sample, so agreement extends
A2 Q2 #7's sample-representativeness argument from the ranking metrics to
the beyond-accuracy ones.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "processed"
METHODS = ["bm25", "embedding", "reranker"]
SLICES = ["overall", "cold_start", "warm", "head", "tail"]
METRICS = ["auc", "mrr", "ndcg5", "ndcg10", "ild", "novelty"]


def fmt(e, width=8, prec=4):
    return f"{'null':>{width}}" if e is None else f"{e['point']:{width}.{prec}f}"


def main(datasets) -> int:
    failures = 0
    for d in datasets:
        path = DATA / d / "reranker_eval_metrics.json"
        if not path.exists():
            print(f"== {d}: {path} not found\n")
            continue
        p = json.loads(path.read_text(encoding="utf-8"))
        if "extended_metrics" not in p:
            print(f"== {d}: no extended_metrics yet -- run reranker_evaluation.py\n")
            continue
        print(f"== {d}  ({p['hyperparameters']['eval_impressions']:,} impressions/split, "
              f"{p['hyperparameters']['bootstrap_iterations']} bootstrap iterations)")
        for split in ["val", "test"]:
            ext = p["extended_metrics"][split]
            sizes = p["slice_sizes"][split]
            print(f"\n  -- {split} --   slice sizes: " + ", ".join(f"{s}={sizes[s]:,}" for s in SLICES))
            for metric in METRICS:
                print(f"  {metric:8s}" + "".join(f"  {m:>9s}" for m in METHODS) + "    slice")
                for sl in SLICES:
                    print(f"  {'':8s}" + "".join(f"  {fmt(ext[m][sl][metric], 9)}" for m in METHODS) + f"    {sl}")
            cov = p["coverage_top10"][split]
            print(f"  coverage_top10 (sample, top-10 union / catalogue): "
                  + "  ".join(f"{m} {cov[m]:.4f}" for m in METHODS))

            # Consistency the write-up relies on.
            for m in METHODS:
                for sl in SLICES:
                    e = ext[m][sl]
                    if e["n"] == 0:
                        assert all(e[k] is None for k in METRICS), (d, split, m, sl)
                    else:
                        for k in METRICS:
                            assert e[k]["ci_lo"] <= e[k]["point"] <= e[k]["ci_hi"], (d, split, m, sl, k)
            assert sizes["cold_start"] + sizes["warm"] == sizes["overall"] == sizes["head"] + sizes["tail"]

            # Cross-check ILD/novelty against A1's full-population baselines.
            q4 = DATA / d / "eval_metrics.json"
            if q4.exists():
                a1 = json.loads(q4.read_text(encoding="utf-8"))["ranking_metrics"]
                print(f"  sample vs A1 full population (ild / novelty, overall):")
                for m in ["bm25", "embedding"]:
                    for k in ["ild", "novelty"]:
                        full = a1[m][split]["overall"][k]["point"]
                        s = ext[m]["overall"][k]
                        inside = s["ci_lo"] <= full <= s["ci_hi"]
                        gap = abs(s["point"] - full)
                        flag = "OK" if inside or gap < 0.01 * max(abs(full), 1e-9) else "DIFFERS"
                        if flag == "DIFFERS":
                            failures += 1
                        print(f"    {m:10s} {k:8s} sample {s['point']:.4f} [{s['ci_lo']:.4f},{s['ci_hi']:.4f}]  "
                              f"full {full:.4f}  {flag}")
        print("  consistency: OK\n")
    return 1 if failures else 0


def head_diagnostic(dataset: str = "ebnerd_large", split: str = "test") -> None:
    """SPEC.md A2 Q5 #4: why the re-ranker is below chance on EB-NeRD's test
    head slice. Recomputes the age gap between clicked head and tail articles,
    and where the re-ranker ranks the clicked head article."""
    import polars as pl

    sys.path.insert(0, str(ROOT / "src"))
    from cs4406m26_assignment1c1.evaluation import train_click_counts

    print(f"== head-slice diagnostic: {dataset}/{split}")
    df = pl.read_parquet(DATA / dataset / f"reranker_eval_{split}.parquet",
                         columns=["impression_id", "article_id", "clicked", "freshness_hours",
                                  "popularity", "reranker_score"])
    beh = (pl.scan_parquet(DATA / dataset / "behaviors.parquet").filter(pl.col("split") == "train")
           .select("article_ids_clicked").collect())
    counts = train_click_counts(beh["article_ids_clicked"].to_list())
    ever = sorted(counts.items(), key=lambda kv: -kv[1])
    head = {a for a, _ in ever[: max(1, int(len(ever) * 0.2))]}
    df = df.with_columns(pl.col("article_id").is_in(list(head)).alias("is_head_article"))
    head_imps = df.filter(pl.col("clicked") & pl.col("is_head_article"))["impression_id"].unique()
    df = df.with_columns(pl.col("impression_id").is_in(head_imps.implode()).alias("head_impression"))

    clicked = df.filter(pl.col("clicked"))
    h = clicked.filter(pl.col("head_impression") & pl.col("is_head_article"))
    t = clicked.filter(~pl.col("head_impression"))
    if h["freshness_hours"].null_count() == h.height:
        print("  no freshness_hours on this dataset -- the freshness mechanism cannot apply here")
        return
    print(f"  clicked head articles: n={h.height:,}  median age {h['freshness_hours'].median():.1f} h  "
          f"median train-popularity {h['popularity'].median():.2e}")
    print(f"  clicked tail articles: n={t.height:,}  median age {t['freshness_hours'].median():.1f} h  "
          f"median train-popularity {t['popularity'].median():.2e}")
    hi = df.filter(pl.col("head_impression"))
    g = hi.group_by("impression_id").agg(
        pl.col("freshness_hours").filter(pl.col("clicked") & pl.col("is_head_article")).first().alias("clicked_age"),
        pl.col("freshness_hours").min().alias("freshest_in_view"),
        pl.col("freshness_hours").median().alias("median_in_view"),
        pl.col("reranker_score").rank(descending=True)
          .filter(pl.col("clicked") & pl.col("is_head_article")).first().alias("rr_rank"),
        pl.len().alias("n_cand"))
    older = float((g["clicked_age"] > g["median_in_view"]).mean())
    print(f"  head impressions: n={g.height:,}; clicked head article median age {g['clicked_age'].median():.0f} h; "
          f"freshest in-view candidate {g['freshest_in_view'].median():.0f} h")
    print(f"  re-ranker's median rank of the clicked head article: {g['rr_rank'].median():.0f} of {g['n_cand'].median():.0f}")
    print(f"  share of head impressions where the clicked article is older than the median candidate: {older:.0%}")
    print()


def submissions(populations=("mind_large_test", "ebnerd_testset")) -> int:
    """SPEC.md A2 Q5 #6: the two leaderboard submission files and the runs
    that produced them -- row/impression counts, wall-clock per stage from
    build_progress.log, line-by-line agreement with behaviors.parquet order,
    and the share of impressions with a non-constant re-ranker score."""
    import re
    import zipfile
    from datetime import datetime

    import polars as pl

    sys.path.insert(0, str(ROOT / "src"))
    from cs4406m26_assignment1c1.reranker import SUBMISSION_POPULATIONS

    log = (ROOT / "build_progress.log").read_text(encoding="utf-8").splitlines()

    def ts(line):
        return datetime.fromisoformat(line[1:line.index("]")])

    def last_span(start_pat, end_pat):
        """Wall-clock between the LAST matching end line and the last
        matching start line before it (an earlier crashed attempt is
        superseded by the completed one)."""
        ends = [i for i, l in enumerate(log) if re.search(end_pat, l)]
        if not ends:
            return None
        e = ends[-1]
        starts = [i for i, l in enumerate(log[:e]) if re.search(start_pat, l)]
        return (ts(log[e]) - ts(log[starts[-1]])).total_seconds() / 60 if starts else None

    failures = 0
    for pop in populations:
        cfg = SUBMISSION_POPULATIONS[pop]
        meta_path = DATA / pop / "feature_metrics.json"
        zip_path = ROOT / "submissions" / pop / f"{pop}_reranker_predictions.zip"
        ranks_path = DATA / "_submission_checkpoints" / pop / "reranker_ranks.parquet"
        if not (meta_path.exists() and zip_path.exists()):
            missing = meta_path.name if not meta_path.exists() else zip_path.name
            print(f"== {pop}: missing {missing}\n")
            failures += 1
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        n_imp = meta["n_impressions_by_split"]["test"]
        print(f"== {pop}  (trained on {meta['train_dataset']}, catalog {meta['catalog_dataset']}, row order: {meta['row_order']})")
        print(f"  feature table: {meta['n_rows']:,} rows over {n_imp:,} impressions "
              f"({meta['n_rows'] / n_imp:.2f} candidates/impression); has_click_labels={meta['has_click_labels']}")
        fe_min = last_span(rf"feature_engineering started .*'{pop}'", rf"{pop}: reranker_features\.parquet \+ feature_metrics\.json written")
        sub_min = last_span(rf"reranker_submission started \(datasets=\['{pop}'\]\)", rf"reranker_submission:   {pop}: all \d+ chunks merged")
        line = f"  wall-clock: feature build {fe_min:.1f} min" if fe_min else "  wall-clock: feature build n/a"
        if sub_min:
            line += f", stage-1 + re-rank {sub_min:.1f} min"
        print(line)
        if fe_min:
            line = f"  throughput: features {n_imp / (fe_min * 60):,.0f} imp/s"
            if sub_min:
                line += f", stage-1 + re-rank {n_imp / (sub_min * 60):,.0f} imp/s"
            print(line)

        beh = pl.scan_parquet(DATA / pop / "behaviors.parquet").select(
            "impression_id", pl.col("article_ids_inview").list.len().alias("n")).collect()
        ids = beh["impression_id"].to_list()
        lens = beh["n"].to_list()
        if cfg["strip_impression_prefix"]:
            ids = [i.rsplit("_", 1)[-1] for i in ids]
        n = 0
        n_sentinel = 0
        with zipfile.ZipFile(zip_path) as zf:
            assert zf.namelist() == [cfg["prediction_filename"]], zf.namelist()
            with zf.open(cfg["prediction_filename"]) as fh:
                for raw in fh:
                    iid, ranks = raw.decode("utf-8").rstrip("\n").split(" ", 1)
                    assert iid == ids[n], (pop, n, iid, ids[n])
                    r = ranks.strip("[]").split(",")
                    assert len(r) == lens[n], (pop, n, len(r), lens[n])
                    if n % 1009 == 0 or len(r) > 100:
                        assert sorted(map(int, r)) == list(range(1, len(r) + 1))
                    n_sentinel += iid == "0"
                    n += 1
        assert n == len(ids) == n_imp, (pop, n, len(ids), n_imp)
        line = f"  {zip_path.name}: {n:,} lines in behaviors order, lengths match, permutations valid"
        if n_sentinel:
            line += f"; {n_sentinel:,} beyond-accuracy lines (impression_id 0)"
        print(line)
        if ranks_path.exists():
            share = pl.scan_parquet(ranks_path).select((pl.col("score_range") > 0).mean()).collect().item()
            print(f"  share of impressions with a non-constant re-ranker score: {share:.4f}")
        print()
    return 1 if failures else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "head-diagnostic":
        head_diagnostic(*args[1:])
        raise SystemExit(0)
    if args and args[0] == "submissions":
        raise SystemExit(submissions(tuple(args[1:])) if args[1:] else submissions())
    raise SystemExit(main(args or ["ebnerd_large", "mind_large"]))
