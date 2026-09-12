"""One-command run of A2 Q4's serving and scale analysis.

Executes src/serving_benchmark.ipynb top-to-bottom; every cell's assertions
must pass or the run aborts. Measures the served two-stage pipeline (BM25 and
embedding retrieval over each impression's article_ids_inview, feeding the
LightGBM re-ranker) on this machine: index memory, per-stage and end-to-end
p99 single-request latency, a back-of-envelope cost per 1,000 queries at a
target SLA, and a 10x scaling projection. Writes
data/processed/serving_metrics.json and serving_benchmark.png.

Q4 is a single-machine measurement by nature -- index memory, p99 latency and
cost/QPS only compose if they describe the same host -- so the machine
specification is captured into the output.

Requires A1's feature store, A1 Q3's article_embeddings.parquet, and A2 Q2's
reranker_model_{dataset}.txt plus reranker_eval_test.parquet. Set
SERVING_DATASETS to restrict the run to one dataset per invocation.
See SPEC.md's "A2 Q4" section.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NOTEBOOK = ROOT / "src" / "serving_benchmark.ipynb"


def main() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "jupyter", "nbconvert", "--to", "notebook",
         "--execute", "--inplace", str(NOTEBOOK)],
        cwd=ROOT,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
