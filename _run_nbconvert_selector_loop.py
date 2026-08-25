"""Runs nbconvert --execute --inplace with WindowsSelectorEventLoopPolicy instead
of the default WindowsProactorEventLoopPolicy. The Proactor loop doesn't implement
add_reader, so ipykernel/tornado falls back to an extra selector thread for ZMQ --
a known source of flakiness on Windows (WSAENOBUFS / "error not defined" crashes
seen repeatedly after long-running kernels in this session). Usage:
    uv run python _run_nbconvert_selector_loop.py <notebook_path> <timeout_seconds>
"""
import asyncio
import sys

asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from nbconvert.nbconvertapp import main

notebook_path = sys.argv[1]
timeout = sys.argv[2]

sys.argv = [
    "jupyter-nbconvert",
    "--to", "notebook",
    "--execute",
    "--inplace",
    notebook_path,
    f"--ExecutePreprocessor.timeout={timeout}",
]
main()
