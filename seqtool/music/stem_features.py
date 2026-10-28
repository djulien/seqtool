"""What the drum, bass and other stems (and the melody) add to music.json (0.22.0).

Measurements only, like the rest of the analysis:

frames (per frame_interval)
    drums, bassline, other      each stem's level against the whole mix, 0..1
                                (1 = that part is as loud as the mix; *_dbfs = absolute)
    melody_norm                 how high the tune is, 0..1 within this song's melodic range,
                                held through rests (so a 'fill' can follow it)
    melody_hz                   the tune's pitch (0 = no clear pitch)
    melody_voiced               share of the frame with a clear pitch, 0..1

events
    kick, snare, hat            drum hits, from the drum stem's low / mid / high bands
    bass                        bass note starts, with "midi" and "note" when pitched
    melody                      melody notes: time, end, midi, note (e.g. "E4"), hz,
                                height (0..1, as melody_norm), source (vocals | other)

The melody is the voice where it sings (vocal stem) and otherwise the strongest clear
pitch in the 'other' stem (piano, guitar, synth lead). The voice's pitch is found with
YIN (de Cheveigne & Kawahara 2002); the 'other' stem, which often holds chords, with a
harmonic-sum salience in which what is held cancels and what moves stands out (see
lead_track). Both are numpy here - no extra package. Where no pitch stands out there
is no melody, rather than a wrong one.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def note_name(midi: float) -> str:
    m = int(round(midi))
    return f"{NOTE_NAMES[m % 12]}{m // 12 - 1}"


def hz_to_midi(hz):
    return 69 + 12 * np.log2(np.maximum(hz, 1e-6) / 440.0)


def read_samples(path: Path) -> np.ndarray:
    from . import decode
    parts = list(decode.chunks(path))
    return np.concatenate(parts).astype(np.float32) if parts else np.zeros(0, np.float32)


def yin(x: np.ndarray, sr: int, hop: int, fmin: float, fmax: float, threshold: float = 0.15,
        batch: int = 1500) -> tuple[np.ndarray, np.ndarray]:
    """Pitch per hop (Hz, 0 = none) and its clarity (0..1). Frame i is centred at i*hop."""
    tmin, tmax = max(2, int(sr / fmax)), int(np.ceil(sr / fmin))
    W = max(tmax, int(0.025 * sr))
    L = W + tmax + 1
    n = max(0, int(np.ceil(len(x) / hop)))
    pad = np.concatenate([np.zeros(L // 2, np.float32), x, np.zeros(L, np.float32)])
    nfft = 1 << int(np.ceil(np.log2(L + W)))
    f0, clar = np.zeros(n), np.zeros(n)
    taus = np.arange(tmax + 1)
    for s in range(0, n, batch):
        m = min(batch, n - s)
        idx = (np.arange(m)[:, None] + s) * hop + np.arange(L)[None, :]
        fr = pad[idx].astype(np.float64)
        F = np.fft.rfft(fr, nfft)
        G = np.fft.rfft(fr[:, :W], nfft)
        r = np.fft.irfft(np.conj(G) * F, nfft)[:, : tmax + 1]
        cs = np.concatenate([np.zeros((m, 1)), np.cumsum(fr ** 2, axis=1)], axis=1)
        e = cs[:, taus + W] - cs[:, taus]
        d = np.maximum(e[:, :1] + e - 2 * r, 0)
        d[:, 0] = 0
        cum = np.cumsum(d[:, 1:], axis=1)
        dp = np.ones_like(d)
        dp[:, 1:] = d[:, 1:] * taus[1:] / np.maximum(cum, 1e-12)
        seg = dp[:, tmin: tmax]
        below = seg < threshold
        has = below.any(axis=1)
        first = np.where(has, below.argmax(axis=1), seg.argmin(axis=1))
        rows = np.arange(m)
        for _ in range(tmax):                                 # walk down to the local minimum
            nxt = np.minimum(first + 1, seg.shape[1] - 1)
            step = seg[rows, nxt] < seg[rows, first]
            if not step.any():
                break
            first = np.where(step, nxt, first)
        t = first + tmin
        a, b, c = dp[rows, np.maximum(t - 1, 0)], dp[rows, t], dp[rows, np.minimum(t + 1, tmax)]
        den = a - 2 * b + c
        shift = np.where(np.abs(den) > 1e-12, 0.5 * (a - c) / np.where(den == 0, 1, den), 0)
        tt = t + np.clip(shift, -1, 1)
        best = seg[rows, first]
        f0[s: s + m] = np.where(best < 0.35, sr / tt, 0)
        clar[s: s + m] = np.clip(1 - best, 0, 1)
    return f0, clar


def _rms_hop(x: np.ndarray, hop: int, n: int) -> np.ndarray:
    m = len(x) // hop
    r = np.sqrt((x[: m * hop].reshape(m, hop) ** 2).mean(axis=1)) if m else np.zeros(0)
    return np.pad(r, (0, max(0, n - len(r))))[:n]


def _peaks(env: np.ndarray, fps: float, threshold: float, min_gap: float) -> list[dict]:
    x = env / (np.percentile(env, 99) or 1.0)
    out: list[dict] = []
    for i in range(1, len(x) - 1):
        if x[i] >= threshold and x[i] >= x[i - 1] and x[i] > x[i + 1]:
            t = i / fps
            if out and t - out[-1]["time"] < min_gap:
                if x[i] > out[-1]["strength"]:
                    out[-1] = {"time": round(t, 3), "strength": float(min(1.0, x[i]))}
                continue
            out.append({"time": round(t, 3), "strength": float(min(1.0, x[i]))})
    return out


def drum_hits(feat: dict, edges_hz: np.ndarray, fps: float) -> dict[str, list[dict]]:
    """kick / snare / hat from the drum stem (fine arrays from analyze.extract): each hit
    of the stem is sorted by where its energy rises - low (kick), mid with noise (snare),
    high only (hi-hat, cymbal). One hit can be a kick and a hat at once."""
    B = feat["bands"]
    floor = np.percentile(B.sum(axis=1), 99) * 1e-4          # -40 dB: bleed and silence don't count
    logB = np.log10(B + floor / B.shape[1])
    lo_edge = edges_hz[:-1]
    groups = {"low": lo_edge < 150, "mid": (lo_edge >= 150) & (lo_edge < 4000), "high": lo_edge >= 5000}
    G = {g: B[:, m].sum(axis=1) for g, m in groups.items()}
    ref = {g: np.percentile(v, 99.5) + 1e-12 for g, v in G.items()}
    cand: list[dict] = []
    for g, m in groups.items():                            # hits in each band (a quiet hat counts too)
        d = np.maximum(np.diff(logB[:, m], axis=0, prepend=logB[:1, m]), 0).sum(axis=1)
        d[:1] = 0
        env = np.maximum(d - np.convolve(d, np.ones(25) / 25, mode="same"), 0)
        cand += _peaks(env, fps, 0.25, 0.05)
    cand.sort(key=lambda h: h["time"])
    hits: list[dict] = []
    for h in cand:
        if hits and h["time"] - hits[-1]["time"] <= 0.03:
            hits[-1]["strength"] = max(hits[-1]["strength"], h["strength"])
        else:
            hits.append(dict(h))
    out: dict[str, list[dict]] = {"kick": [], "snare": [], "hat": []}
    for h in hits:
        i = int(round(h["time"] * fps))
        lvl, rise = {}, {}
        for g, v in G.items():                             # dB against the group's loudest, and the jump
            after, before = v[i: i + 3].max(), v[max(0, i - 3): max(1, i - 1)].mean()
            lvl[g] = 10 * np.log10(after / ref[g] + 1e-12)
            rise[g] = 10 * np.log10((after + floor) / (before + floor))
        if lvl["low"] >= -12 and rise["low"] >= 6:
            out["kick"].append(dict(h))
        if lvl["mid"] >= -10 and lvl["high"] >= -10 and rise["high"] >= 6:
            out["snare"].append(dict(h))
        elif lvl["high"] >= -30 and rise["high"] >= 6:
            out["hat"].append(dict(h))
    return out


def _notes(midi: np.ndarray, voiced: np.ndarray, fps: float, min_len: float = 0.08,
           jump: float = 0.8) -> list[tuple[int, int, float]]:
    """(first, last+1, median midi) runs of steady pitch."""
    out, i, n = [], 0, len(midi)
    while i < n:
        if not voiced[i]:
            i += 1
            continue
        j, ref = i + 1, midi[i]
        while j < n and voiced[j]:
            if abs(midi[j] - ref) > jump:
                k = j                                     # a real change holds for 3 hops
                if all(k + q < n and voiced[k + q] and abs(midi[k + q] - ref) > jump for q in range(3)):
                    break
            ref = float(np.median(midi[i: j + 1][-7:]))
            j += 1
        if (j - i) / fps >= min_len:
            out.append((i, j, float(np.median(midi[i:j]))))
        i = j
    return out


def pitch_track(x: np.ndarray, sr: int, hop: int, n: int, fmin: float, fmax: float,
                gate_db: float = 30.0) -> tuple[np.ndarray, np.ndarray]:
    """Pitch (midi, nan = none) and clarity per hop, with quiet hops left out."""
    f0, clar = yin(x, sr, hop, fmin, fmax)
    f0, clar = np.pad(f0, (0, max(0, n - len(f0))))[:n], np.pad(clar, (0, max(0, n - len(clar))))[:n]
    db = 20 * np.log10(_rms_hop(x, hop, n) + 1e-9)
    loud = db > np.percentile(db, 95) - gate_db
    midi = np.where((f0 > 0) & loud & (clar > 0.6), hz_to_midi(f0), np.nan)
    m = midi.copy()                                       # median over 5 hops, ignoring gaps
    for k in range(2, len(m) - 2):
        w = midi[k - 2: k + 3]
        if not np.isnan(midi[k]) and np.isfinite(w).sum() >= 3:
            m[k] = np.nanmedian(w)
    return m, clar


def lead_track(x: np.ndarray, sr: int, hop: int, n: int, lo_midi: int = 48, hi_midi: int = 96,
               nfft: int = 2048, harmonics: int = 6, batch: int = 2000) -> tuple[np.ndarray, np.ndarray]:
    """The leading pitch of a stem that may hold chords (midi, nan = none; and its clarity):
    harmonic-sum salience (each candidate pitch scores its first harmonics, weaker ones
    less), minus each pitch's average over the surrounding 2 s - what is held (a pad, a
    strummed chord) cancels, what moves (the tune) stands out."""
    cands = np.arange(lo_midi, hi_midi + 1, 1 / 3)
    f = 440 * 2 ** ((cands - 69) / 12)
    hz_bin = sr / nfft
    hs = np.arange(1, harmonics + 1)
    bins = np.clip(np.round(f[:, None] * hs[None, :] / hz_bin).astype(int), 0, nfft // 2)
    w = 0.8 ** (hs - 1)
    win = np.hanning(nfft).astype(np.float32)
    pad = np.concatenate([np.zeros(nfft // 2, np.float32), x, np.zeros(nfft, np.float32)])
    sal = np.zeros((n, len(cands)), np.float32)
    for s in range(0, n, batch):
        m = min(batch, n - s)
        idx = (np.arange(m)[:, None] + s) * hop + np.arange(nfft)[None, :]
        idx = np.minimum(idx, len(pad) - 1)
        M = np.sqrt(np.abs(np.fft.rfft(pad[idx] * win, axis=1)))         # compressed magnitude
        Mx = np.maximum(M, np.maximum(np.roll(M, 1, axis=1), np.roll(M, -1, axis=1)))   # +/-1 bin
        sal[s: s + m] = (Mx[:, bins] * w).sum(axis=2)
    k = int(round(1.0 * sr / hop))
    cs = np.cumsum(np.vstack([np.zeros((1, sal.shape[1]), np.float32), sal]), axis=0)
    i = np.arange(n)
    a, b = np.maximum(i - k, 0), np.minimum(i + k + 1, n)
    mean = (cs[b] - cs[a]) / (b - a)[:, None]
    con = sal - mean
    best = con.argmax(axis=1)
    peak = con[i, best]
    ref = np.percentile(peak, 95) or 1.0
    clar = np.clip(peak / ref, 0, 1)
    db = 20 * np.log10(_rms_hop(x, hop, n) + 1e-9)
    loud = db > np.percentile(db, 95) - 30
    midi = np.where((clar > 0.35) & loud, cands[best], np.nan)
    return midi, clar


def melody(vocals: Path | None, other: Path | None, vocal_active: np.ndarray | None,
           sr: int, hop: int, n_fine: int) -> dict:
    """The tune: voice where it sings, else the 'other' stem's clearest pitch."""
    from ..common.log import info
    tracks = {}
    if vocals is not None:
        info("  melody: pitch of the voice ...")
        tracks["vocals"] = pitch_track(read_samples(vocals), sr, hop, n_fine, 75.0, 1100.0)
    if other is not None:
        info("  melody: pitch of the other instruments ...")
        tracks["other"] = lead_track(read_samples(other), sr, hop, n_fine)
    if not tracks:
        return {}
    midi = np.full(n_fine, np.nan)
    src = np.full(n_fine, "", dtype=object)
    if "other" in tracks:
        o = tracks["other"][0]
        midi, src = np.where(np.isfinite(o), o, midi), np.where(np.isfinite(o), "other", src)
    if "vocals" in tracks:
        v = tracks["vocals"][0]
        sing = np.isfinite(v)
        if vocal_active is not None:
            act = np.pad(vocal_active, (0, max(0, n_fine - len(vocal_active))))[:n_fine]
            sing &= act
            midi = np.where(act & ~np.isfinite(v), np.nan, midi)    # singing without clear pitch: no melody
        midi, src = np.where(sing, v, midi), np.where(sing, "vocals", src)
    voiced = np.isfinite(midi)
    fps = sr / hop
    if voiced.sum() < 10:
        return {"midi": midi, "notes": [], "range": None, "voiced": voiced, "source": src}
    lo, hi = np.percentile(midi[voiced], 5), np.percentile(midi[voiced], 95)
    span = max(hi - lo, 1.0)
    notes = []
    for a, b, mm in _notes(np.where(voiced, midi, 0.0), voiced, fps):
        s = src[a:b]
        notes.append({"time": round(a / fps, 3), "end": round(b / fps, 3), "midi": round(mm, 2),
                      "note": note_name(mm), "hz": round(float(440 * 2 ** ((mm - 69) / 12)), 1),
                      "height": round(float(np.clip((mm - lo) / span, 0, 1)), 3),
                      "source": "vocals" if (s == "vocals").mean() >= 0.5 else "other"})
    return {"midi": midi, "notes": notes, "range": (float(lo), float(hi)), "voiced": voiced, "source": src}


def bass_notes(x: np.ndarray, feat: dict, sr: int, hop: int, fps: float) -> list[dict]:
    """Bass note starts (onsets of the bass stem), with the pitch where it is clear."""
    flux = feat["flux"]
    env = np.maximum(flux - np.convolve(flux, np.ones(25) / 25, mode="same"), 0)
    hits = _peaks(env, fps, 0.35, 0.1)
    if not hits:
        return []
    midi, _ = pitch_track(x, sr, hop, len(flux), 30.0, 300.0, gate_db=24.0)
    for h in hits:
        i = int(h["time"] * fps)
        w = midi[i + 2: i + 12]                          # 20-120 ms after the attack
        w = w[np.isfinite(w)]
        if len(w) >= 3:
            mm = float(np.median(w))
            h["midi"], h["note"] = round(mm, 2), note_name(mm)
    return hits


def hold(x: np.ndarray, default: float = 0.5) -> np.ndarray:
    """Carry the last finite value through gaps (nan); before the first one, `default`."""
    out = np.empty_like(x)
    last = default
    for i, v in enumerate(x):
        if np.isfinite(v):
            last = v
        out[i] = last
    return out


def _near(events: list[dict], t: float, before: float = 0.25) -> dict | None:
    """The latest event at or just before t (within `before` s, or a note still sounding)."""
    best = None
    for e in events:
        if e["time"] > t + 1e-3:
            break
        if e.get("end", e["time"] + before) >= t - 1e-3 or t - e["time"] <= before:
            best = e
    return best


def stems_at(music: dict, t: float) -> list[str]:
    """'explain music @T' lines: the parts' levels and the drum hit / bass and melody note there."""
    an = music["analysis"]
    f, dt = an["frames"]["fields"], an["frame_interval"]
    i = min(int(round(t / dt)), an["frames"]["count"] - 1)
    ev = an["events"]
    lv = "   ".join(f"{name} {f[k][i]:.2f}" for name, k in (("drums", "drums"), ("bass", "bassline"),
                                                             ("other", "other")) if k in f)
    hits = [k for k in ("kick", "snare", "hat") if _near(ev.get(k, []), t, 0.06)]
    out = [f"  stems       {lv}   (each part against the whole mix)"
           + (f";  drum hit: {', '.join(hits)}" if hits else "")]
    b = _near(ev.get("bass", []), t)
    m = _near(ev.get("melody", []), t, 0.0)
    out.append("  notes       bass " + (b.get("note") or "(no clear pitch)" if b else "-")
               + "   melody " + (f"{m['note']} ({m['source']}, height {m['height']:.2f})" if m else "-")
               + "   - presets can react to them: 'presets' lists kick, snare, hat-sparkle, bass-pulse, melody-fill")
    return out


def stems_line(music: dict) -> str | None:
    """One line for 'inspect audio': what the drum, bass and other stems and the melody found."""
    st = music.get("analysis", {}).get("summary", {}).get("stems")
    if not st:
        return None
    parts = []
    d = st.get("drums")
    if d:
        parts.append(f"drums {d.get('kick_count', 0)} kicks, {d.get('snare_count', 0)} snares, "
                     f"{d.get('hat_count', 0)} hats")
    if st.get("bass"):
        parts.append(f"bass {st['bass'].get('note_count', 0)} notes")
    m = st.get("melody")
    if m:
        rng = f" {m['range'][0]}-{m['range'][1]}" if m.get("range") else ""
        parts.append(f"melody {m.get('notes', 0)} notes{rng} ({m.get('from_vocals', 0):.0%} from the voice)")
    return "stems:  " + "; ".join(parts)
