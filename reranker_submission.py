"""One-command run of A2 Q5 Part B: Codabench submissions for the two-stage
pipeline (Stage-1 BM25/embedding scores + Q1 features + Q2 LightGBM re-ranker)
on the blind ebnerd_testset and mind_large_test populations.

Executes src/reranker_submission.ipynb top-to-bottom; every cell's assertions
must pass or the run aborts. Writes
submissions/{population}/{population}_reranker_predictions.zip in each
competition's exact format.

Requires, per population: data/processed/{population}/behaviors.parquet +
history.parquet (A1 Q5), reranker_features.parquet from
`FEATURE_DATASETS={population} uv run python feature_engineering.py`, and the
training dataset's reranker_model_*.txt + metadata from
src/reranker_training_kaggle.ipynb.

Set SUBMISSION_DATASETS to one population per invocation -- the default runs
both in one kernel, which holds two BM25 indexes and embedding matrices at
once. See SPEC.md's "A2 Q5" section (#6).
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NOTEBOOK = ROOT / "src" / "reranker_submission.ipynb"


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
