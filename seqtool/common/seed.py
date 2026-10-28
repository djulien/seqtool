"""Deterministic sub-seeding: master seed + named path -> independent stream.

    rng = sub_rng(12345, "matchup", "MegaTree", "w017", "Spirals")

Same inputs always give the same stream, and adding a model or effect never
perturbs the streams of the others (unlike sharing one global RNG).
"""
from __future__ import annotations

import hashlib
import random


def sub_seed(master: int, *path: object) -> int:
    h = hashlib.sha256(str(int(master)).encode())
    for p in path:
        h.update(b"\x1f")
        h.update(str(p).encode("utf-8"))
    return int.from_bytes(h.digest()[:8], "big")


def sub_rng(master: int, *path: object) -> random.Random:
    return random.Random(sub_seed(master, *path))


def uniform(master: int, *path: object, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo + (hi - lo) * (sub_seed(master, *path) / 2**64)
