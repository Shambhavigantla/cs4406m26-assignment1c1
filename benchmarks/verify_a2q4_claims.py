"""Prints the numbers SPEC.md's `A2 Q4` section quotes, read from the
persisted `serving_metrics.json` files, and re-checks the internal
consistency the spec relies on.

Usage: uv run python benchmarks/verify_a2q4_claims.py

To regenerate the numbers themselves on the current machine:
    SERVING_DATASETS=<dataset> uv run python serving_benchmark.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "processed"
DATASETS = ["ebnerd_large", "mind_large"]


def main() -> int:
    found = 0
    for dataset in DATASETS:
        path = DATA / dataset / "serving_metrics.json"
        if not path.exists():
            print(f"== {dataset}: {path} not found -- run serving_benchmark.py first\n")
            continue
        found += 1
        p = json.loads(path.read_text(encoding="utf-8"))
        m, lat, cost, sc = p["index_memory"], p["latency"], p["cost"], p["scaling"]
        mach = p["machine"]
        print(f"== {dataset}  (measured on {mach['processor'] or mach['platform']}, "
              f"{mach['total_ram_gb']} GB RAM, {mach['logical_cores']} logical cores)")

        bm = m["bm25_index"]
        print(f"  index memory: BM25 {m['bm25_index_total_bytes'] / 1024**2:.1f} MB "
              f"({bm['n_docs']:,} docs, {bm['n_postings']:,} postings) | embeddings "
              f"{m['embedding_matrix_bytes'] / 1024**2:.1f} MB x2 (matrix + unit copy) | "
              f"booster {m['reranker_model_bytes'] / 1024:.0f} KB ({m['reranker_trees']} trees)")
        fs = m["feature_store"]
        print(f"  feature store: {fs['on_disk_total_bytes'] / 1024**3:.2f} GB on disk; "
              f"{fs['feature_rows']:,} rows at {fs['feature_bytes_per_row']:.0f} B/row "
              f"= {fs['feature_in_memory_bytes'] / 1024**3:.2f} GB resident")

        s = lat["served_end_to_end"]
        print(f"  served p50/p95/p99: {s['p50_ms']:.2f} / {s['p95_ms']:.2f} / {s['p99_ms']:.2f} ms "
              f"over {s['n']} requests ({lat['candidates_per_request']['mean']:.1f} candidates mean)")
        parts = ["query_build", "bm25_inview", "embedding_inview", "feature_assembly", "reranker_predict"]
        share = {k: lat[k]["mean_ms"] / s["mean_ms"] for k in parts}
        top = max(share, key=share.get)
        print(f"  dominant stage: {top} at {share[top]:.0%} of the served mean")
        cg, cgb = lat["candgen_embedding_top200"], lat["candgen_embedding_top200_batchfn"]
        print(f"  corpus-wide top-200: bm25 p99 {lat['candgen_bm25_top200']['p99_ms']:.2f} ms | "
              f"embedding serving-shaped p99 {cg['p99_ms']:.2f} ms | "
              f"batch-fn-per-request p99 {cgb['p99_ms']:.1f} ms ({cgb['mean_ms'] / cg['mean_ms']:.0f}x)")

        print(f"  SLA p99 < {cost['sla_p99_ms']:.0f} ms: {'MEETS' if cost['meets_sla'] else 'BREACHES'} "
              f"({cost['p99_headroom_x']}x headroom) | {cost['qps_per_process']:.0f} QPS/process | "
              f"${cost['usd_per_1000_queries']:.6f} per 1,000 queries at ${cost['usd_per_vcpu_hour']}/vCPU-h")

        ten = next(r for r in sc["projection"] if r["factor"] == 10)
        print(f"  10x: serving set {ten['serving_resident_gb']} GB, feature store {ten['feature_store_gb']} GB, "
              f"fits in {sc['machine_ram_gb']} GB: {ten['serving_plus_features_fits']}; "
              f"embedding candgen p99 -> {ten['projected_embedding_candgen_p99_ms']:.1f} ms; "
              f"dominant component now: {sc['dominant_component_now']}")

        # Consistency the spec relies on.
        assert s["p50_ms"] <= s["p95_ms"] <= s["p99_ms"], "percentiles out of order"
        assert abs(cost["qps_per_process"] - 1000.0 / s["mean_ms"]) < 0.1, "QPS not from the mean"
        one = next(r for r in sc["projection"] if r["factor"] == 1)
        assert one["serving_resident_bytes"] == sc["resident_now_bytes"], "1x != measured"
        assert cg["mean_ms"] < cgb["mean_ms"], "batch-fn anti-pattern not slower"
        print("  consistency: OK\n")
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())
