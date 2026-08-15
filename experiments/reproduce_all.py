#!/usr/bin/env python3
"""Run both PiTEA reproduction experiments in sequence."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def run(script: str) -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "experiments" / script)],
        cwd=ROOT,
        check=True,
    )


def main() -> None:
    run("reproduce_transport_results.py")
    run("reproduce_buffer_design.py")
    print(f"All reproduction outputs are under {ROOT / 'outputs'}")


if __name__ == "__main__":
    main()
