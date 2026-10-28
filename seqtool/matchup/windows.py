"""Decision windows: high-res (50 ms) analysis -> ~0.5-8 s decision units.

Windows are cut at every section boundary, then sub-divided on a musical grid
(downbeats, else every 4th beat, else fixed time) toward a target length.
Each window carries aggregated features and the transition strength at its
start, which is what lets strong musical boundaries override continuity.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Window:
    index: int
    start: float
    end: float
    section_id: str
    section_index: int
    section_type: str | None          # the type used for scoring (custom names mapped via section_types)
    section_confidence: float
    section_repeat_key: str
    is_section_start: bool
    transition_strength: float = 0.0
    features: dict[str, float] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.end - self.start


FIELD_MAP = {  # window feature <- frame field
    "energy": "energy_norm",
    "beat": "beat_strength",
    "onset": "onset_norm",
    "brightness": "brightness_norm",
    "bass": "bass_norm",
    "vocal": "vocal",
    "drums": "drums",              # stems only (0.22.0): drum stem level against the mix
    "melody": "melody_voiced",     # stems only: share of the window with a clear tune
}


def _grid(music: dict, cfg: dict, duration: float) -> list[float]:
    ev = music["analysis"]["events"]
    kind = cfg.get("grid", "downbeat")
    if kind == "downbeat" and ev.get("downbeats"):
        return [e["time"] for e in ev["downbeats"]]
    beats = [e["time"] for e in ev.get("beats", [])]
    if kind in ("downbeat", "bar") and len(beats) >= 8:
        return beats[::4]
    if beats:
        return beats
    step = cfg.get("target_window", 4.0) / 2
    return list(np.arange(0.0, duration, step))


def _split_section(start: float, end: float, grid: list[float], cfg: dict) -> list[float]:
    tgt, mn, mx = cfg["target_window"], cfg["min_window"], cfg["max_window"]
    pts = [t for t in grid[bisect_right(grid, start):bisect_left(grid, end)]
           if t - start >= mn * 0.5 and end - t >= mn * 0.5]
    cuts, last = [start], start
    for i, t in enumerate(pts):
        nxt = pts[i + 1] if i + 1 < len(pts) else end
        if t - last >= tgt or (nxt - last > mx and t - last >= mn):
            if end - t >= mn:
                cuts.append(t)
                last = t
    while True:  # enforce max_window even without grid points
        gaps = [(cuts[i + 1] if i + 1 < len(cuts) else end) - c for i, c in enumerate(cuts)]
        i = next((i for i, g in enumerate(gaps) if g > mx), None)
        if i is None:
            break
        cuts.insert(i + 1, cuts[i] + gaps[i] / 2)
    return cuts


def build_windows(music: dict, profile: dict, cfg_decision: dict, cfg_cont: dict,
                  aliases: dict | None = None) -> list[Window]:
    if aliases is None:
        from ..common.config import music_prefs
        aliases = music_prefs().get("section_types", {})
    an = music["analysis"]
    dt = an["frame_interval"]
    f0 = an["frames"]["start"]
    fields = {k: np.asarray(v, dtype=float) for k, v in an["frames"]["fields"].items()}
    n = an["frames"]["count"]
    duration = music["audio"]["duration"]
    grid = sorted(_grid(music, cfg_decision, duration))
    onset_times = sorted(e["time"] for e in an["events"].get("onsets", []))

    tempo = profile["profile"].get("tempo_bpm") or an["summary"].get("tempo", {}).get("bpm", 120.0)

    windows: list[Window] = []
    sections = sorted(profile["sections"], key=lambda s: s["start"])
    repeat_root = {}
    for s in sections:
        repeat_root[s["id"]] = repeat_root.get(s.get("repeat_of"), s.get("repeat_of")) or s["id"]

    for s in sections:
        cuts = _split_section(s["start"], s["end"], grid, cfg_decision)
        bounds = cuts + [s["end"]]
        for j in range(len(cuts)):
            a, b = bounds[j], bounds[j + 1]
            i0 = max(0, min(n, int(round((a - f0) / dt))))
            i1 = max(i0 + 1, min(n, int(round((b - f0) / dt))))
            feats: dict[str, float] = {}
            for wname, fname in FIELD_MAP.items():
                arr = fields.get(fname)
                if arr is not None and i0 < len(arr):
                    feats[wname] = float(np.clip(arr[i0:i1].mean(), 0, 1))
            if "energy" in feats:
                feats["energy_peak"] = float(np.clip(fields["energy_norm"][i0:i1].max(), 0, 1))
            onset = feats.get("onset")
            if onset is None and onset_times:  # fall back to onset density
                cnt = bisect_left(onset_times, b) - bisect_left(onset_times, a)
                onset = min(1.0, cnt / max(b - a, 1e-6) / 8.0)
            if onset is not None:
                feats["sustained"] = 1.0 - onset
            windows.append(Window(
                index=len(windows), start=a, end=b, section_id=s["id"],
                section_index=s.get("index", 0),
                section_type=aliases.get(s.get("type"), s.get("type")),
                section_confidence=s.get("confidence", 0.5),
                section_repeat_key=repeat_root[s["id"]], is_section_start=(j == 0),
                features=feats))

    lo, hi = 60.0, 180.0
    tnorm = float(np.clip((tempo - lo) / (hi - lo), 0, 1))
    prev_energy = None
    for w in windows:
        w.features["tempo"] = tnorm
        e = w.features.get("energy", 0.5)
        if w.index == 0:
            w.transition_strength = 1.0
        elif w.is_section_start:
            sec = next(s for s in sections if s["id"] == w.section_id)
            w.transition_strength = sec.get("transition", {}).get(
                "incoming_strength", cfg_cont["section_boundary_default_strength"])
        else:
            jump = abs(e - prev_energy) if prev_energy is not None else 0.0
            w.transition_strength = float(np.clip(
                cfg_cont["within_section_base_strength"] + cfg_cont["energy_jump_gain"] * jump, 0, 0.6))
        prev_energy = e
    return windows
