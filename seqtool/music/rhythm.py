"""Tempo (autocorrelation + prior), beats (Ellis-style dynamic programming),
downbeats (phase of the 4-beat cycle with the most low-end onset energy).
All operate on a 100 fps onset envelope (whole-stream; tiny in memory)."""
from __future__ import annotations

import numpy as np

FPS = 100.0


def tempo(onset: np.ndarray, lo_bpm=60.0, hi_bpm=200.0, prior_bpm=120.0) -> tuple[float, float]:
    o = onset - onset.mean()
    n = len(o)
    if n < FPS * 4:
        return prior_bpm, 0.0
    spec = np.fft.rfft(o, 2 * n)
    ac = np.fft.irfft(np.abs(spec) ** 2)[:n]
    ac /= ac[0] or 1.0
    lags = np.arange(int(FPS * 60 / hi_bpm), int(FPS * 60 / lo_bpm) + 1)
    bpm = 60 * FPS / lags
    prior = np.exp(-0.5 * (np.log2(bpm / prior_bpm) / 0.9) ** 2)
    score = ac[lags] + 0.5 * ac[np.minimum(2 * lags, n - 1)]
    weighted = score * prior
    i = int(np.argmax(weighted))
    if 0 < i < len(lags) - 1:     # parabolic refinement of the lag
        a, b, c = weighted[i - 1:i + 2]
        d = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
        lag = lags[i] + float(np.clip(d, -0.5, 0.5))
    else:
        lag = float(lags[i])
    conf = float(np.clip((score[i] - np.median(score)) / (np.max(score) - np.median(score) + 1e-9), 0, 1))
    conf *= float(np.clip(score[i] * 2, 0, 1))
    return 60 * FPS / lag, conf


def beats(onset: np.ndarray, bpm: float, tightness: float = 100.0) -> np.ndarray:
    """Return beat times (s). Classic DP beat tracker."""
    o = onset / (onset.std() or 1.0)
    period = 60 * FPS / bpm
    n = len(o)
    score = o.copy()
    back = np.full(n, -1)
    lo, hi = int(round(period / 2)), int(round(2 * period))
    offs = np.arange(lo, hi + 1)
    penalty = -tightness * np.log(offs / period) ** 2
    for t in range(hi, n):
        cand = score[t - offs] + penalty
        k = int(np.argmax(cand))
        score[t] = o[t] + cand[k]
        back[t] = t - offs[k]
    tail = int(n - period)
    t = tail + int(np.argmax(score[tail:])) if tail > 0 else int(np.argmax(score))
    path = []
    while t >= 0:
        path.append(t)
        t = back[t]
    bt = np.array(sorted(path), dtype=float) / FPS
    return bt[bt > 0.05]


def downbeat_phase(beat_times: np.ndarray, low_onset: np.ndarray) -> int:
    if len(beat_times) < 8:
        return 0
    idx = np.clip((beat_times * FPS).astype(int), 0, len(low_onset) - 1)
    vals = np.array([low_onset[max(0, i - 3):i + 4].max() for i in idx])
    return int(np.argmax([vals[k::4].mean() for k in range(4)]))


def beat_numbers(beats: list[dict], downs: list[dict]) -> list[int]:
    """Beat number within its bar (1 = downbeat), for timing-mark labels."""
    dts = [d["time"] for d in downs]
    per_bar = 4
    if len(dts) > 1 and beats:
        bt = [b["time"] for b in beats]
        counts = [sum(1 for t in bt if a - 1e-3 <= t < b - 1e-3) for a, b in zip(dts, dts[1:])]
        counts = [c for c in counts if c]
        if counts:
            per_bar = max(set(counts), key=counts.count)
    first = dts[0] if dts else (beats[0]["time"] if beats else 0.0)
    pickup = [b for b in beats if b["time"] < first - 0.06]
    out = [(per_bar - len(pickup) + i) % per_bar + 1 for i in range(len(pickup))]
    di, n = 0, 0
    for b in beats[len(pickup):]:
        t = b["time"]
        hit = False
        while di < len(dts) and dts[di] <= t + 0.06:
            hit = hit or abs(dts[di] - t) <= 0.06
            di += 1
        n = 1 if hit else n + 1
        out.append(n)
    return out
