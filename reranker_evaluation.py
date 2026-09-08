"""One-command run of A2 Q2's before/after evaluation.

Executes src/reranker_evaluation.ipynb top-to-bottom; every cell's assertions
must pass or the run aborts. Scores BM25, frozen-embedding cosine and the
Stage-2 LightGBM re-ranker on one common sample of impressions per split, and
writes data/processed/{dataset}/reranker_eval_metrics.json with each method's
metrics, the paired bootstrap CI on the difference, and a check that the
sampled population reproduces the full-population baselines in
eval_metrics.json.

Requires Q1's reranker_features.parquet, Q2/Q3's {method}_topk.parquet, A1's
article_embeddings.parquet, and reranker_model_{dataset}.txt from
src/reranker_training_kaggle.ipynb.

Set RERANK_EVAL_DATASETS to restrict the run to one dataset per invocation --
the default holds both large datasets' BM25 indexes and embedding matrices in
one kernel, which does not fit on a 16GB machine.
See SPEC.md's "A2 Q2" section.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NOTEBOOK = ROOT / "src" / "reranker_evaluation.ipynb"


def main() -> int:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "jupyter",
            "nbconvert",
            "--to",
            "notebook",
            "--execute",
            "--inplace",
            str(NOTEBOOK),
        ],
        cwd=ROOT,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
