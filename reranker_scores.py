"""One-command run of A2 Q2's Stage-1 retrieval scoring pass.

Executes src/reranker_scores.ipynb top-to-bottom; every cell's assertions must
pass or the run aborts. Produces data/processed/{dataset}/reranker_scores.parquet
(bm25/embedding scores plus top-200 membership flags for a sampled slice of
train and val), which the Kaggle training notebook joins onto Q1's
reranker_features.parquet to build the re-ranker's design matrix.

Requires Q1's reranker_features.parquet and Q2/Q3's {method}_topk.parquet.
Set SCORE_DATASETS to restrict the run to one dataset per invocation.
See SPEC.md's "A2 Q2" section.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NOTEBOOK = ROOT / "src" / "reranker_scores.ipynb"


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
