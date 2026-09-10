"""One-command build of A2 Q3's NRMS Kaggle inputs.

Executes src/nrms_inputs.ipynb top-to-bottom; every cell's assertions must pass
or the run aborts. Writes data/kaggle_nrms/ -- the sampled train/val/test
impressions, the truncated per-user history, the staged article embeddings and
a manifest -- which is uploaded as one Kaggle Dataset and consumed by
src/nrms_baseline_kaggle.ipynb.

The val/test populations are drawn by reranker_evaluation.ipynb's own sampling
function at its own seed, so Q3's NRMS numbers land on the same impressions as
A2 Q2's BM25/embedding/re-ranker numbers; when reranker_eval_{split}.parquet
already exists the notebook asserts that identity directly.

Requires A1's feature store (behaviors/history) and article_embeddings.parquet.
Set NRMS_INPUT_DATASETS to restrict the run to one dataset per invocation.
See SPEC.md's "A2 Q3" section.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NOTEBOOK = ROOT / "src" / "nrms_inputs.ipynb"


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
