"""Verifies the numeric and structural claims in SPEC.md's `A2 Q3` section
against the real feature store, the staged Kaggle inputs and the notebooks
themselves.

Usage:
    uv run python benchmarks/verify_a2q3_claims.py [check]

where `check` is one of `population`, `inputs`, `ndcg`, `recency`,
`metric-parity`, or `all` (the default).
"""

from __future__ import annotations

import ast
import json
import math
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cs4406m26_assignment1c1.evaluation import ndcg_at_k  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "processed"
KAGGLE_INPUTS = ROOT / "data" / "kaggle_nrms"
NOTEBOOK = ROOT / "src" / "nrms_baseline_kaggle.ipynb"
EVALUATION_MODULE = ROOT / "src" / "cs4406m26_assignment1c1" / "evaluation.py"

LARGE = ["ebnerd_large", "mind_large"]
SPLITS = ["val", "test"]

# SPEC.md A2 Q3 #5
CLAIMED_EVAL_IMPRESSIONS = 200_000
CLAIMED_TRAIN_IMPRESSIONS = 400_000
CLAIMED_HISTORY_SIZE = 20
# SPEC.md A2 Q3 #3
HALF_LIFE_HOURS = 72.0
HALF_LIFE_CLICKS = 5.0
# SPEC.md A2 Q3 #6: mean candidates per impression, the factor of
# news-encoder work the shortcut removes.
CLAIMED_CANDIDATES = {"ebnerd_large": 11.9, "mind_large": 37.0}
# SPEC.md A2 Q3 #7
CLAIMED_NDCG10 = 0.993078

# The functions the Kaggle notebook restates from evaluation.py because
# Kaggle has no access to the package (SPEC.md A2 Q3 #7).
RESTATED_FUNCTIONS = [
    "_rank_avg",
    "auc_impression",
    "mrr",
    "ndcg_at_k",
    "bootstrap_ci",
    "paired_bootstrap_ci",
]


def _missing(path: Path, hint: str) -> bool:
    if path.exists():
        return False
    print(f"  {path.relative_to(ROOT)} not found -- {hint}")
    return True


def check_population() -> None:
    """SPEC.md A2 Q3 #5: Q3's val/test impressions are the same impressions
    A2 Q2 evaluated, not merely the same size."""
    print("== Evaluation population is identical to A2 Q2's ==")
    if _missing(KAGGLE_INPUTS, "run `uv run python nrms_inputs.py` first"):
        return
    for dataset in LARGE:
        seen = {}
        for split in SPLITS:
            ours = KAGGLE_INPUTS / f"nrms_{dataset}_{split}.parquet"
            theirs = DATA / dataset / f"reranker_eval_{split}.parquet"
            if not ours.exists():
                print(f"  {dataset}/{split}: not staged")
                continue
            ids = pl.read_parquet(ours, columns=["impression_id"])["impression_id"].sort()
            seen[split] = set(ids.to_list())
            line = f"  {dataset}/{split}: {ids.len():>7,} impressions"
            line += "  count == 200,000: " + ("OK" if ids.len() == CLAIMED_EVAL_IMPRESSIONS else "NO")
            if theirs.exists():
                q2 = (
                    pl.scan_parquet(theirs)
                    .select("impression_id")
                    .unique()
                    .collect()["impression_id"]
                    .sort()
                )
                same = q2.len() == ids.len() and q2.to_list() == ids.to_list()
                line += f"   same set as A2 Q2 ({q2.len():,}): " + ("OK" if same else "MISMATCH")
            else:
                line += "   A2 Q2 output absent, comparison skipped"
            print(line)
        train_path = KAGGLE_INPUTS / f"nrms_{dataset}_train.parquet"
        if train_path.exists():
            train_ids = set(
                pl.read_parquet(train_path, columns=["impression_id"])["impression_id"].to_list()
            )
            print(
                f"  {dataset}/train: {len(train_ids):>7,} impressions"
                f"  count == 400,000: {'OK' if len(train_ids) == CLAIMED_TRAIN_IMPRESSIONS else 'NO'}"
                f"   disjoint from val/test: "
                + (
                    "OK"
                    if all(not (train_ids & seen.get(s, set())) for s in SPLITS)
                    else "OVERLAP"
                )
            )
        if len(seen) == 2:
            print(
                f"  {dataset}: val/test disjoint: "
                + ("OK" if not (seen["val"] & seen["test"]) else "OVERLAP")
            )


def check_inputs() -> None:
    """SPEC.md A2 Q3 #5-#6: history truncation, per-dataset candidate counts,
    cold-start population, upload size."""
    print("== Staged Kaggle inputs ==")
    if _missing(KAGGLE_INPUTS, "run `uv run python nrms_inputs.py` first"):
        return
    total_bytes = 0
    for dataset in LARGE:
        hist_path = KAGGLE_INPUTS / f"nrms_{dataset}_history.parquet"
        if not hist_path.exists():
            print(f"  {dataset}: not staged")
            continue
        hist = pl.read_parquet(hist_path)
        lengths = hist["article_id_sequence"].list.len()
        basis = "elapsed_time" if "timestamp_sequence" in hist.columns else "ordinal_proxy"
        print(
            f"  {dataset}: {hist.height:>8,} users   history max {int(lengths.max()):>2} "
            f"(<= {CLAIMED_HISTORY_SIZE}: {'OK' if int(lengths.max()) <= CLAIMED_HISTORY_SIZE else 'NO'})"
            f"   mean {float(lengths.mean()):>5.1f}   cold-start {int((lengths == 0).sum()):>6,}"
            f"   basis {basis}"
        )
        for split in ["train", *SPLITS]:
            path = KAGGLE_INPUTS / f"nrms_{dataset}_{split}.parquet"
            if not path.exists():
                continue
            df = pl.read_parquet(path, columns=["article_ids_inview", "article_ids_clicked"])
            mean_cands = float(df["article_ids_inview"].list.len().mean())
            claimed = CLAIMED_CANDIDATES[dataset]
            outside = int(
                df.select(
                    pl.col("article_ids_clicked").list.set_difference(pl.col("article_ids_inview")).list.len()
                )
                .to_series()
                .sum()
            )
            print(
                f"    {split:<5}: mean candidates/impression {mean_cands:>5.2f} "
                f"(claimed ~{claimed})   clicked outside inview {outside}"
            )
    for path in sorted(KAGGLE_INPUTS.glob("*")):
        total_bytes += path.stat().st_size
    print(f"  upload set: {total_bytes / 1e6:,.1f} MB across {len(list(KAGGLE_INPUTS.glob('*')))} files")


def check_ndcg() -> None:
    """SPEC.md A2 Q3 #7: the constructed case the notebook pins its nDCG
    implementation to -- six positives at ranks 1-5 and 7 of eight
    candidates give nDCG@5 = 1.000 and nDCG@10 = 0.993078."""
    print("== nDCG@10 below nDCG@5, exact value ==")
    scores = np.array([8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0])
    labels = np.array([1, 1, 1, 1, 1, 0, 1, 0], dtype=bool)
    n5 = ndcg_at_k(scores, labels, 5)
    n10 = ndcg_at_k(scores, labels, 10)
    # Hand-computed, independent of the implementation under test.
    dcg5 = sum(1.0 / math.log2(i + 2) for i in range(5))
    dcg10 = dcg5 + 1.0 / math.log2(8)
    idcg10 = dcg5 + 1.0 / math.log2(7)
    print(f"  ndcg_at_k(.., 5)  = {n5:.6f}   hand-computed 1.000000  [{'OK' if abs(n5 - 1.0) < 1e-12 else 'NO'}]")
    print(
        f"  ndcg_at_k(.., 10) = {n10:.6f}   hand-computed {dcg10 / idcg10:.6f}"
        f"  claimed {CLAIMED_NDCG10:.6f}  "
        f"[{'OK' if abs(n10 - CLAIMED_NDCG10) < 1e-5 and abs(n10 - dcg10 / idcg10) < 1e-12 else 'NO'}]"
    )
    print(f"  ndcg10 < ndcg5: {'OK' if n10 < n5 else 'NO'}")


def check_recency() -> None:
    """SPEC.md A2 Q3 #3: the two recency bases, and that the basis is decided
    by null count rather than dtype (the A2 Q1 #3 mislabelling)."""
    print("== Recency-weight basis per dataset ==")
    for dataset in LARGE:
        path = DATA / dataset / "history.parquet"
        if _missing(path, "build the feature store first"):
            continue
        lf = pl.scan_parquet(path)
        dtype = lf.collect_schema()["timestamp_sequence"]
        non_null = int(lf.select(pl.col("timestamp_sequence").is_not_null().sum()).collect().item())
        by_nulls = "elapsed_time" if non_null > 0 else "ordinal_proxy"
        by_dtype = "ordinal_proxy" if dtype == pl.Null else "elapsed_time"
        print(
            f"  {dataset}: timestamp_sequence dtype {str(dtype):<20} non-null rows {non_null:>8,}"
            f"   basis by null count {by_nulls:<13} by dtype {by_dtype:<13}"
            f" {'AGREE' if by_nulls == by_dtype else 'DTYPE WOULD MISLABEL'}"
        )
    print("  half-life semantics (one half-life back weighs exactly half the newest click):")
    print(
        f"    elapsed_time, {HALF_LIFE_HOURS:.0f}h old: "
        f"exp(-ln2 * {HALF_LIFE_HOURS:.0f}/{HALF_LIFE_HOURS:.0f}) = "
        f"{math.exp(-math.log(2) * HALF_LIFE_HOURS / HALF_LIFE_HOURS):.4f}"
    )
    print(
        f"    ordinal_proxy, {HALF_LIFE_CLICKS:.0f} clicks back: "
        f"exp(-ln2 * {HALF_LIFE_CLICKS:.0f}/{HALF_LIFE_CLICKS:.0f}) = "
        f"{math.exp(-math.log(2) * HALF_LIFE_CLICKS / HALF_LIFE_CLICKS):.4f}"
    )


def _function_body(source: str, name: str) -> list[str]:
    """The normalised body of a top-level function: comments, blank lines and
    the docstring dropped, whitespace collapsed. Signature excluded, since the
    notebook's copies bind defaults to notebook constants."""
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    body = body[1:]
            return [ast.dump(stmt) for stmt in body]
    raise KeyError(name)


def check_metric_parity() -> None:
    """SPEC.md A2 Q3 #7: the Kaggle notebook restates evaluation.py's
    estimators and they must stay identical, or Q3's numbers are not
    comparable to A1's and A2 Q2's."""
    print("== Restated metric functions match evaluation.py ==")
    if _missing(NOTEBOOK, "the Kaggle notebook is missing") or _missing(
        EVALUATION_MODULE, "the local evaluation module is missing"
    ):
        return
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    cells = ["".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code"]
    notebook_source = "\n\n".join(cells)
    module_source = EVALUATION_MODULE.read_text(encoding="utf-8")

    for name in RESTATED_FUNCTIONS:
        try:
            theirs = _function_body(module_source, name)
        except KeyError:
            print(f"  {name}: absent from evaluation.py")
            continue
        try:
            ours = _function_body(notebook_source, name)
        except (KeyError, SyntaxError) as exc:
            print(f"  {name}: could not parse the notebook copy ({type(exc).__name__})")
            continue
        same = theirs == ours
        print(f"  {name:<22} statements {len(theirs):>2} vs {len(ours):>2}   {'IDENTICAL' if same else 'DIFFERS'}")
        if not same:
            for i, (a, b) in enumerate(zip(theirs, ours)):
                if a != b:
                    print(f"    first difference at statement {i + 1}")
                    break


CHECKS = {
    "population": check_population,
    "inputs": check_inputs,
    "ndcg": check_ndcg,
    "recency": check_recency,
    "metric-parity": check_metric_parity,
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
