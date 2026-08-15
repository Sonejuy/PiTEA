"""Stable access to the release model source and its content digest."""

from __future__ import annotations

import hashlib
from pathlib import Path


MODEL_SOURCE_DIRECTORY = Path(__file__).resolve().parent


def model_source_files() -> tuple[Path, ...]:
    """Return release model Python files in deterministic relative-path order."""

    return tuple(
        sorted(
            (
                path
                for path in MODEL_SOURCE_DIRECTORY.glob("*.py")
                if path.name != "provenance.py"
            ),
            key=lambda path: path.name,
        )
    )


def model_source_sha256() -> str:
    """Hash source paths and bytes as a reproducibility fingerprint."""

    digest = hashlib.sha256()
    for path in model_source_files():
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
