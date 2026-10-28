"""Laplacian structural segmentation (McFee & Ellis, "Analyzing song structure
with spectral clustering", ISMIR 2014) - the method behind librosa's
segmentation example, implemented with numpy only.

  1. beat-synchronous chroma (harmony) and timbre (cepstrum of log bands)
  2. recurrence graph: each beat linked to the beats that sound most alike
     harmonically (mutual k-nearest neighbours), with repeated *sequences*
     emphasised by a diagonal median filter
  3. path graph: each beat linked to its neighbours, weighted by timbre similarity
  4. both graphs balanced and combined; the normalised Laplacian's eigenvectors
     give a low-dimensional embedding where beats of the same section type cluster
  5. k-means on the first k eigenvectors -> a section-type label per beat;
     boundaries where the label changes. k comes from the eigengap.

Returns boundaries (with a strength) AND segment labels, so repeats are found
by the same analysis (same label = same kind of material).
"""
from __future__ import annotations

import numpy as np


def _knn_affinity(X: np.ndarray, width: int = 3) -> np.ndarray:
    n = len(X)
    Xn = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
    D = 1.0 - Xn @ Xn.T                                    # cosine distance
    idx = np.arange(n)
    D[np.abs(idx[:, None] - idx[None, :]) < width] = np.inf  # ignore the beat's own neighbourhood
    k = max(2, min(n - 1, 2 * int(np.ceil(np.sqrt(max(n - 2 * width + 1, 1))))))
    R = np.zeros((n, n))
    nn = np.argsort(D, axis=1)[:, :k]
    rows = np.repeat(idx, k)
    R[rows, nn.ravel()] = 1.0
    R = np.minimum(R, R.T)                                  # mutual neighbours only
    finite = D[np.isfinite(D) & (R > 0)]
    sigma = np.median(finite) if finite.size else 1.0
    return R * np.exp(-np.where(np.isfinite(D), D, 0) / (sigma + 1e-9))


def _diag_median(R: np.ndarray, size: int = 7) -> np.ndarray:
    """Median filter along diagonals: keeps repeated sequences, drops isolated matches."""
    n, h = len(R), size // 2
    pad = np.pad(R, h)
    stack = np.stack([pad[h + k:h + k + n, h + k:h + k + n] for k in range(-h, h + 1)])
    return np.median(stack, axis=0)


def _path_affinity(M: np.ndarray) -> np.ndarray:
    n = len(M)
    d = np.sum(np.diff(M, axis=0) ** 2, axis=1)
    sigma = np.median(d) if len(d) else 1.0
    w = np.exp(-d / (sigma + 1e-9))
    A = np.zeros((n, n))
    A[np.arange(n - 1), np.arange(1, n)] = w
    A[np.arange(1, n), np.arange(n - 1)] = w
    return A


def _kmeans(X: np.ndarray, k: int, restarts: int = 6, iters: int = 50) -> np.ndarray:
    """Deterministic k-means (fixed seeds, k-means++ init); best of several restarts."""
    best, best_cost = None, np.inf
    for r in range(restarts):
        rng = np.random.default_rng(1000 + r)
        centers = [X[rng.integers(len(X))]]
        for _ in range(1, k):
            d2 = np.min([np.sum((X - c) ** 2, axis=1) for c in centers], axis=0)
            p = d2 / d2.sum() if d2.sum() > 0 else None
            centers.append(X[rng.choice(len(X), p=p)])
        C = np.array(centers)
        for _ in range(iters):
            lab = np.argmin(((X[:, None, :] - C[None]) ** 2).sum(-1), axis=1)
            newC = np.array([X[lab == j].mean(0) if np.any(lab == j) else C[j] for j in range(k)])
            if np.allclose(newC, C):
                break
            C = newC
        cost = sum(((X[lab == j] - C[j]) ** 2).sum() for j in range(k))
        if cost < best_cost:
            best, best_cost = lab, cost
    return best


def segment(chroma_b: np.ndarray, timbre_b: np.ndarray, k: int | None = None,
            k_range: tuple[int, int] = (2, 6)) -> tuple[np.ndarray, int]:
    """Per-beat section-type labels and the k used."""
    n = len(chroma_b)
    if n < 16:
        return np.zeros(n, dtype=int), 1
    C = np.log1p(10 * chroma_b / (chroma_b.max(axis=1, keepdims=True) + 1e-9))
    Rf = _diag_median(_knn_affinity(C))
    Rp = _path_affinity((timbre_b - timbre_b.mean(0)) / (timbre_b.std(0) + 1e-9))
    deg_p, deg_r = Rp.sum(1), Rf.sum(1)
    mu = deg_p.dot(deg_p + deg_r) / (np.sum((deg_p + deg_r) ** 2) + 1e-9)
    A = mu * Rf + (1 - mu) * Rp
    d = A.sum(1)
    d[d == 0] = 1e-9
    Dm = 1.0 / np.sqrt(d)
    L = np.eye(n) - (Dm[:, None] * A * Dm[None, :])
    evals, evecs = np.linalg.eigh(L)
    # smooth the eigenvectors in time (suppresses one-beat label flicker)
    pad = 4
    E = np.pad(evecs, ((pad, pad), (0, 0)), mode="edge")
    evecs = np.median(np.stack([E[i:i + n] for i in range(2 * pad + 1)]), axis=0)
    lo, hi = k_range
    hi = min(hi, n // 4)
    if k is None:
        gaps = np.diff(evals[: hi + 1])
        k = int(np.argmax(gaps[lo - 1:hi]) + lo) if hi >= lo else lo
    Cnorm = np.cumsum(evecs ** 2, axis=1) ** 0.5
    X = evecs[:, :k] / (Cnorm[:, k - 1:k] + 1e-9)
    return _kmeans(X, k), k


def boundaries(labels: np.ndarray, beat_times: np.ndarray, duration: float) -> list[dict]:
    """Boundary at every label change; strength = how long the material on both sides lasts
    (short flickers are weak). Segment label kept for repeat detection."""
    out = []
    n = len(labels)
    change = [i for i in range(1, n) if labels[i] != labels[i - 1]]
    edges = [0] + change + [n]
    for j, i in enumerate(change):
        left, right = edges[j + 1] - edges[j], edges[j + 2] - edges[j + 1]
        strength = float(min(1.0, min(left, right) / 16))   # 16 beats (4 bars) on both sides = full strength
        out.append({"time": float(beat_times[i]), "strength": strength, "label": int(labels[i])})
    return out


def segment_labels_for(cuts: list[float], beat_times: np.ndarray, labels: np.ndarray) -> list[int]:
    """Majority label of the beats inside each [cut_i, cut_i+1) - for any set of section cuts."""
    out = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        m = (beat_times >= a) & (beat_times < b)
        out.append(int(np.bincount(labels[m]).argmax()) if m.any() else -1)
    return out
