"""Stable JSON serialization and content hashing.

Determinism rules (design doc section 25):
  * floats are rounded to a fixed number of decimals before output
  * content hashes exclude volatile metadata (created_utc) so that re-running a
    stage on identical input produces an identical hash, which is what makes
    downstream staleness detection actually work
  * Python's built-in hash() is never used (it is salted per process)
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

FLOAT_DECIMALS = 4
# Transient keys never contribute to content hashes (timestamps, run timing/host info).
VOLATILE_KEYS = frozenset({"created_utc", "run"})


def round_floats(obj: Any, nd: int = FLOAT_DECIMALS) -> Any:
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise ValueError("NaN/Inf are not valid in seqtool interchange files")
        r = round(obj, nd)
        return 0.0 if r == 0 else r          # normalise -0.0
    if isinstance(obj, dict):
        return {k: round_floats(v, nd) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [round_floats(v, nd) for v in obj]
    return obj


def dumps(obj: Any, *, indent: int | None = 2) -> str:
    """Human-readable but deterministic output (insertion order preserved;
    producers build dicts in a fixed order)."""
    return json.dumps(round_floats(obj), indent=indent, ensure_ascii=False) + "\n"


def write_json(path: str | Path, obj: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)       # results go in subfolders (0.19.9)
    Path(path).write_text(dumps(obj), encoding="utf-8")


class NotJSON(ValueError):
    pass


def read_json(path: str | Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        p = Path(path)
        what = "an audio file" if p.suffix.lower() in (".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac") else "not JSON"
        raise NotJSON(f"{p.name} is {what}, not a seqtool .json file ({e.__class__.__name__})") from None


def _strip_volatile(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_volatile(v) for k, v in obj.items() if k not in VOLATILE_KEYS}
    if isinstance(obj, list):
        return [_strip_volatile(v) for v in obj]
    return obj


def content_sha256(doc: Any) -> str:
    canon = json.dumps(round_floats(_strip_volatile(doc)), sort_keys=True,
                       separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def file_sha256(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()
