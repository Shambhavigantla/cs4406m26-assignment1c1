"""One-command run of A2 Q1's feature engineering notebook (click-history and
session features for the Stage-2 re-ranker).

Executes src/feature_engineering.ipynb top-to-bottom; every cell's assertions
must pass or the run aborts. Requires data/processed/{ebnerd,mind}/ from Q1's
build_pipeline.py and Q3's embedding_retrieval.py (for article_embeddings.parquet).
See SPEC.md's "A2 Q1" section for the feature design.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NOTEBOOK = ROOT / "src" / "feature_engineering.ipynb"


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
