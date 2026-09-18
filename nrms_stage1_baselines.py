"""One-command run of A2 Q3's Stage-1 baseline measurement.

Executes src/nrms_stage1_baselines.ipynb top-to-bottom; every cell's assertions
must pass or the run aborts. Scores BM25 and frozen-embedding cosine over the
*same* impressions Q3's NRMS run scored -- the ones staged in
data/kaggle_nrms/nrms_{dataset}_{split}.parquet -- and writes
data/processed/{dataset}/stage1_per_impression_{split}.npz (per-impression
metric arrays in staged-file order, for a later paired comparison) and
stage1_vs_nrms.json (point estimates with bootstrap CIs, the paired
bm25-vs-embedding interval, and NRMS's own numbers alongside).

Requires the Q1 feature store, article_embeddings.parquet, and the staged
population from nrms_inputs.py. A split whose .npz already exists is skipped,
so an interrupted run resumes.

Set STAGE1_DATASETS to restrict the run to one dataset per invocation -- the
default holds both large datasets' BM25 indexes and embedding matrices in one
kernel, which does not fit on a 16GB machine.
See SPEC.md's "A2 Q3" section.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NOTEBOOK = ROOT / "src" / "nrms_stage1_baselines.ipynb"


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
