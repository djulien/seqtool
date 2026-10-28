"""Structural boundaries from a whole-song feature matrix (checkerboard
novelty on a bar-synchronous self-similarity matrix). Returns unlabeled
boundaries; labeling happens in the classifier."""
from __future__ import annotations

import numpy as np


def sync_features(feat: np.ndarray, frame_times: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Average frame features (T,D) over each [edges[i], edges[i+1])."""
    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        m = (frame_times >= a) & (frame_times < b)
        out.append(feat[m].mean(axis=0) if m.any() else np.zeros(feat.shape[1]))
    return np.asarray(out)


def novelty(X: np.ndarray, half: int) -> np.ndarray:
    Z = (X - X.mean(axis=0)) / (X.std(axis=0) + 1e-9)
    Z /= np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9
    S = Z @ Z.T
    n = len(S)
    k = np.arange(-half, half)
    g = np.exp(-0.5 * ((k + 0.5) / (half * 0.5)) ** 2)
    K = np.outer(g, g) * np.sign(k + 0.5)[:, None] * np.sign(k + 0.5)[None, :]
    nov = np.zeros(n)
    for i in range(half, n - half + 1):
        nov[i] = (S[i - half:i + half, i - half:i + half] * K).sum()
    nov = np.maximum(nov, 0)
    return nov / (nov.max() or 1.0)


def energy_novelty(level_db: np.ndarray, half: int, full_scale_db: float = 6.0) -> np.ndarray:
    """|mean level of next `half` units - previous `half` units|, 6 dB -> 1.0.
    Catches verse->chorus lifts that timbre novelty underrates."""
    n = len(level_db)
    w = np.arange(half, 0, -1, dtype=float)          # triangular: nearest units weigh most
    out = np.zeros(n)
    for i in range(1, n):
        a, b = level_db[max(0, i - half):i][::-1], level_db[i:i + half]
        if len(a) and len(b):
            out[i] = abs((b * w[:len(b)]).sum() / w[:len(b)].sum()
                         - (a * w[:len(a)]).sum() / w[:len(a)].sum()) / full_scale_db
    return out                                        # unclipped so steps stay peaked


def boundaries(X: np.ndarray, edges: np.ndarray, level_db: np.ndarray | None = None,
               half: int = 4, min_units: int = 4) -> list[dict]:
    if len(X) < 2 * half + 2:
        return []
    nov = novelty(X, half)
    if level_db is not None:
        nov = np.maximum(nov, energy_novelty(level_db, half))
    capped = np.minimum(nov, 1.0)
    thr = max(0.15, capped.mean() + 0.5 * capped.std())
    cands = [i for i in range(1, len(nov) - 1)
             if capped[i] >= thr and nov[i] >= nov[i - 1] and nov[i] >= nov[i + 1]]
    chosen: list[int] = []
    for i in sorted(cands, key=lambda i: -nov[i]):      # strongest first, enforce spacing
        if all(abs(i - j) >= min_units for j in chosen) and i >= min_units // 2 \
                and len(X) - i >= min_units // 2:
            chosen.append(i)
    return [{"time": float(edges[i]), "strength": float(min(1.0, nov[i])),
             "confidence": float(min(1.0, 0.4 + 0.6 * min(1.0, nov[i])))} for i in sorted(chosen)]
