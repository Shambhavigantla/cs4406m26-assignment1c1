"""Runs _run_nbconvert_selector_loop.py repeatedly until it succeeds or a max
retry count is hit. Exists because evaluation_harness.ipynb's long-running
kernel keeps hitting an intermittent WinError 10055 kernel-death on this
machine (see SPEC.md Q4 #9) that survives every code-level mitigation tried
so far (memory fixes, chunked/checkpointed evaluate_ranking). Since each
chunk is checkpointed to disk immediately, a crash only ever loses at most
one partial chunk's work -- a fresh retry (this script's whole point) picks
up exactly where the last one died instead of restarting from scratch.

Usage:
    uv run python _run_nbconvert_with_retries.py <notebook_path> <timeout_seconds> [max_retries]
"""
import subprocess
import sys
import time

notebook_path = sys.argv[1]
timeout = sys.argv[2]
max_retries = int(sys.argv[3]) if len(sys.argv) > 3 else 20

for attempt in range(1, max_retries + 1):
    print(f"=== attempt {attempt}/{max_retries} ===", flush=True)
    result = subprocess.run(
        [sys.executable, "_run_nbconvert_selector_loop.py", notebook_path, timeout]
    )
    if result.returncode == 0:
        print(f"=== succeeded on attempt {attempt}/{max_retries} ===", flush=True)
        sys.exit(0)
    print(f"=== attempt {attempt}/{max_retries} failed (exit {result.returncode}), retrying ===", flush=True)
    time.sleep(5)

print(f"=== gave up after {max_retries} attempts ===", flush=True)
sys.exit(1)
