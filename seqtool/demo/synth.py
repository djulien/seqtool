"""Deterministic synthetic test song (no copyright, no downloads).

128 BPM, 44 bars: intro(8) verse(8) chorus(8) verse(8) chorus(8) outro(4).
Written as 44.1 kHz 16-bit stereo WAV so the decoder's resampling path is
exercised. Ground truth is returned so tests can score the analyzer.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 44100
BPM = 128.0
BEAT = 60.0 / BPM
BAR = 4 * BEAT
PLAN = [("intro", 8), ("verse", 8), ("chorus", 8), ("verse", 8), ("chorus", 8), ("outro", 4)]
ROOTS = [55.0, 43.65, 49.0, 41.2]          # A1 F1 G1 E1 - one per bar, cycling


def truth() -> dict:
    t, secs = 0.0, []
    for name, bars in PLAN:
        secs.append({"type": name, "start": t, "end": t + bars * BAR})
        t += bars * BAR
    return {"bpm": BPM, "duration": t, "sections": secs}


def _env(n, decay):
    return np.exp(-np.arange(n) / (decay * SR))


def _bar(kind: str, bar_idx: int, rng: np.random.Generator, parts: dict | None = None) -> np.ndarray:
    """One bar of the mix; with `parts`, each instrument is also added to parts[stem]
    (drums, bass, other - the stems Demucs would give), for the stem tests."""
    n = int(round(BAR * SR))
    t = np.arange(n) / SR
    out = np.zeros(n)
    stems = {k: np.zeros(n) for k in ("drums", "bass", "other")} if parts is not None else None

    def add(stem, a, b, x):
        out[a:b] += x
        if stems is not None:
            stems[stem][a:b] += x
    root = ROOTS[bar_idx % 4]
    loud = {"intro": 0.35, "verse": 0.6, "chorus": 1.0, "outro": 0.3}[kind]
    # pad (all sections)
    for mult in (2, 2.5, 3, 4):
        add("other", 0, n, 0.05 * np.sin(2 * np.pi * root * mult * t))
    # hats on 8ths (all but outro)
    if kind != "outro":
        hn = int(0.04 * SR)
        for k in range(8):
            s = int(k * BEAT / 2 * SR)
            noise = np.diff(rng.standard_normal(hn + 1))
            add("drums", s, s + hn, (0.04 if kind == "intro" else 0.08) * noise * _env(hn, 0.01))
    if kind in ("verse", "chorus"):
        kn = int(0.25 * SR)
        kt = np.arange(kn) / SR
        kick = np.sin(2 * np.pi * (50 * kt + 70 * (1 - np.exp(-kt * 30)) / 30)) * _env(kn, 0.08)
        for k in range(4):
            s = int(k * BEAT * SR)
            add("drums", s, s + kn, 0.9 * kick[: n - s])
        bn = int(BEAT / 2 * SR)
        for k in range(8):                      # bass eighths
            s = int(k * BEAT / 2 * SR)
            bt = np.arange(bn) / SR
            add("bass", s, s + bn, 0.25 * np.sign(np.sin(2 * np.pi * root * bt)) * _env(bn, 0.12))
    if kind == "chorus":
        sn = int(0.15 * SR)
        for k in (1, 3):                        # snare on 2 and 4
            s = int(k * BEAT * SR)
            add("drums", s, s + sn, 0.35 * rng.standard_normal(sn) * _env(sn, 0.05))
        melody = [4, 5, 6, 5, 4, 3, 4, 6]
        ln = int(BEAT / 2 * SR)
        for k, m in enumerate(melody):          # bright square lead
            s = int(k * BEAT / 2 * SR)
            lt = np.arange(ln) / SR
            add("other", s, s + ln, 0.07 * np.sign(np.sin(2 * np.pi * root * m * 2 * lt)) * _env(ln, 0.3))
    if stems is not None:
        for k, x in stems.items():
            parts.setdefault(k, []).append(x * loud)
    return out * loud


def _wav(path: Path, x: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
        w.writeframes(np.repeat(pcm[:, None], 2, axis=1).tobytes())


def write_stems(folder: Path, seed: int = 7) -> dict:
    """The song's instruments as separate files (drums.wav, bass.wav, other.wav and a
    silent vocals.wav), as perfect stems for testing the stem analysis."""
    rng = np.random.default_rng(seed)
    folder.mkdir(parents=True, exist_ok=True)
    parts: dict = {}
    bar_idx = 0
    for kind, bars in PLAN:
        for _ in range(bars):
            _bar(kind, bar_idx, rng, parts)
            bar_idx += 1
    out = {}
    for k, xs in parts.items():
        _wav(folder / f"{k}.wav", np.concatenate(xs) * 0.6)
        out[k] = folder / f"{k}.wav"
    _wav(folder / "vocals.wav", np.zeros(sum(len(x) for x in parts["drums"])))
    out["vocals"] = folder / "vocals.wav"
    return out


def write(path: Path, seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        bar_idx = 0
        for kind, bars in PLAN:
            for _ in range(bars):
                x = np.tanh(_bar(kind, bar_idx, rng) * 1.2) * 0.7
                pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
                w.writeframes(np.repeat(pcm[:, None], 2, axis=1).tobytes())
                bar_idx += 1
    return truth()
