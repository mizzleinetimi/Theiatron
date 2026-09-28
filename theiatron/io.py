"""Atomic publication for files consumed while a worker is running."""
import json
import os
import tempfile
from pathlib import Path


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".publish-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def atomic_json(path: Path, value) -> None:
    atomic_bytes(path, json.dumps(value, allow_nan=False, sort_keys=True).encode())
