# seqtool-inspect: vocals | inspect_vocals | where the singing is: the vocal stem's levels, the gate and the passages: inspect vocals [SONG]
"""Where the singing is, from the Demucs vocal stem (music.json frames vocal_dbfs and
rms_dbfs). Two questions per analysis frame:

  1. Is anyone singing?  The stem's own level against a gate. Between vocal lines
     the stem holds only bleed and noise, its quiet level (the 10th percentile);
     the gate is 10 dB above that (kept 12-18 dB below the loudest singing; a stem
     that is silent between lines gets 18 dB below), unless
     you set it (music.display.vocal_gate_db, in dBFS). Gaps between words and
     breaths up to vocal_gap s (1.0) are bridged, without moving where singing
     starts or stops.
  2. If so, does the voice lead?  The stem against the whole mix: within
     vocal_lead_db (-6 dB) of the mix = vocals (green); quieter = mixed (teal):
     singing under a loud band. Not singing = instrumental (blue).

Passages shorter than min_region (1 s) are then merged into their longer neighbour.
'inspect vocals' shows the levels, the gate, the shares and the passages.
"""
from __future__ import annotations

import numpy as np

DEFAULTS = {"vocal_gate_db": "auto", "vocal_lead_db": -6.0, "vocal_gap": 1.0, "min_region": 1.0}


def display_prefs() -> dict:
    try:
        from ..common.config import music_prefs
        d = music_prefs().get("display", {})
    except Exception:  # noqa: BLE001
        d = {}
    return {k: d.get(k, v) for k, v in DEFAULTS.items()}


def otsu(x: np.ndarray, bins: int = 64) -> float:
    """The threshold that best splits x into two groups (between-class variance)."""
    h, edges = np.histogram(x, bins=bins)
    c = (edges[:-1] + edges[1:]) / 2
    w = np.cumsum(h)
    m = np.cumsum(h * c)
    tot_w, tot_m = w[-1], m[-1]
    w1 = tot_w - w
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (m / w - (tot_m - m) / w1) ** 2 * w * w1
    between = np.nan_to_num(between[:-1])
    return float(c[int(np.argmax(between))]) if len(between) else float(np.median(x))


def analyse(music: dict, prefs: dict | None = None) -> dict | None:
    """{classes: per-frame 'v'|'m'|'i', gate, gate_how, lead, levels...} or None without a stem."""
    an = music.get("analysis", {})
    f = an.get("frames", {}).get("fields", {})
    if "vocal_dbfs" not in f or "rms_dbfs" not in f:
        return None
    p = {**DEFAULTS, **(prefs if prefs is not None else display_prefs())}
    fi = float(an.get("frame_interval", 0.05))
    v = np.asarray(f["vocal_dbfs"], dtype=float)
    mix = np.asarray(f["rms_dbfs"], dtype=float)
    n = min(len(v), len(mix))
    v, mix = v[:n], mix[:n]
    k = max(0, int(round(float(p["vocal_gap"]) / 2 / fi)))       # gaps up to vocal_gap s are bridged
    win = np.lib.stride_tricks.sliding_window_view
    p95 = float(np.percentile(v, 95))
    if p["vocal_gate_db"] in (None, "auto"):
        floor = float(np.percentile(v, 10))          # the stem between vocal lines: bleed and room noise
        gate = float(min(max(floor + 10.0, p95 - 18.0), p95 - 12.0))
        how = f"auto: 10 dB above the stem's quiet level {floor:.0f} dBFS"
    else:
        gate, how = float(p["vocal_gate_db"]), "set by you (music.display.vocal_gate_db)"
    lead = float(p["vocal_lead_db"])
    loud = (v >= gate).astype(np.int8)
    # bridge gaps up to 2 x hold between words / breaths without moving where singing starts or
    # stops: a closing (widen, then shrink back)
    wide = win(np.pad(loud, k, mode="edge"), 2 * k + 1).max(axis=1)
    singing = win(np.pad(wide, k, mode="edge"), 2 * k + 1).min(axis=1).astype(bool)
    leads = (v - mix) >= lead
    classes = np.where(~singing, "i", np.where(leads, "v", "m"))
    return {"classes": classes.tolist(), "gate": gate, "gate_how": how, "lead": lead, "fi": fi,
            "min_region": float(p["min_region"]), "levels": v, "mix": mix, "p95": p95}


def regions(music: dict, prefs: dict | None = None, min_region: float | None = None) -> list[list]:
    """[[start, end, 'v'|'m'|'i'], ...] with passages shorter than min_region merged
    into their longer neighbour (repeatedly, shortest first)."""
    a = analyse(music, prefs)
    if a is None:
        return []
    fi, min_s = a["fi"], a["min_region"] if min_region is None else float(min_region)
    runs: list[list] = []
    for i, k in enumerate(a["classes"]):
        if runs and runs[-1][2] == k:
            runs[-1][1] = (i + 1) * fi
        else:
            runs.append([i * fi, (i + 1) * fi, k])
    while len(runs) > 1:
        j = min(range(len(runs)), key=lambda r: runs[r][1] - runs[r][0])
        if runs[j][1] - runs[j][0] >= min_s:
            break
        left = runs[j - 1] if j > 0 else None
        right = runs[j + 1] if j + 1 < len(runs) else None
        into = left if right is None or (left is not None and left[1] - left[0] >= right[1] - right[0]) else right
        runs[j][2] = into[2]
        merged: list[list] = []
        for r in runs:
            if merged and merged[-1][2] == r[2]:
                merged[-1][1] = r[1]
            else:
                merged.append(list(r))
        runs = merged
    return [[round(a_, 2), round(b, 2), k] for a_, b, k in runs]


WORD = {"v": "vocals", "m": "mixed", "i": "instrumental"}


def gui_levels(music: dict, step: float = 0.1) -> dict | None:
    """What the GUI needs to redo the passages itself while sliders move: the stem and
    mix levels (dB, averaged to `step` s), the automatic gate and the current settings."""
    a = analyse(music)
    if a is None:
        return None
    k = max(1, int(round(step / a["fi"])))
    n = len(a["levels"]) // k * k

    def blocks(x):
        return [round(float(v), 1) for v in np.asarray(x[:n]).reshape(-1, k).mean(axis=1)]
    p = display_prefs()
    auto = analyse(music, {**p, "vocal_gate_db": "auto"})["gate"]
    return {"fi": a["fi"] * k, "stem": blocks(a["levels"]), "mix": blocks(a["mix"]),
            "auto_gate": round(auto, 1), "p95": round(a["p95"], 1),
            "prefs": {"gate": p["vocal_gate_db"], "lead": float(p["vocal_lead_db"]),
                      "gap": float(p["vocal_gap"]), "min_region": float(p["min_region"])}}


def at(music: dict, t: float) -> str | None:
    """'vocals' / 'mixed' / 'instrumental' at time t (after merging), or None without a stem."""
    for a_, b, k in regions(music):
        if a_ <= t < b:
            return WORD[k]
    return None


def inspect_vocals(args) -> list[str]:
    from pathlib import Path
    from ..common import current
    from ..common.canonical import read_json
    from ..common.paths import expand, legacy_name, seqtool_folder, show
    from .sections_cmd import clock
    if args:
        song = expand(" ".join(args), "file")
        cands = [seqtool_folder(song) / f"{song.stem}.music.json", legacy_name(song, "music")]
        mp = next((c for c in cands if c.exists()), None)
    else:
        s = current.song()
        mp = s["music"] if s else None
    if not mp:
        return ["no analysis for that song yet - e.g. 'run --stems' first"]
    music = read_json(Path(mp))
    a = analyse(music)
    if a is None:
        return [f"{show(mp)}: no vocal stem in this analysis - 'run --stems' measures one"]
    v, mix, cls = a["levels"], a["mix"], np.array(a["classes"])
    L = [f"{{head}}vocals in {music['source'].get('filename', show(mp))}{{/}}  (from the Demucs vocal stem)",
         f"  stem level (dBFS): quietest 5% below {np.percentile(v, 5):.0f}, median {np.median(v):.0f}, "
         f"loudest 5% above {a['p95']:.0f};  whole mix median {np.median(mix):.0f}",
         f"  singing gate: {a['gate']:.1f} dBFS ({a['gate_how']})",
         f"  voice leads when the stem is within {abs(a['lead']):g} dB of the mix (music.display.vocal_lead_db)"]
    lo, hi = float(np.floor(np.percentile(v, 1))), float(np.ceil(np.percentile(v, 99.5)))
    h, edges = np.histogram(np.clip(v, lo, hi), bins=24, range=(lo, hi))
    L.append("  how often each stem level occurs (| = the gate):")
    peak = max(1, int(h.max()))
    for n, e0, e1 in zip(h, edges[:-1], edges[1:]):
        bar = "#" * int(round(30 * n / peak))
        mark = " |" if e0 <= a["gate"] < e1 else ""
        L.append(f"    {e0:6.1f} {bar}{mark}")
    regs = regions(music)
    tot = sum(b - a_ for a_, b, _ in regs) or 1
    share = {k: sum(b - a_ for a_, b, kk in regs if kk == k) / tot for k in "vmi"}
    L.append(f"  passages (after merging those under {a['min_region']:g} s): vocals {share['v']:.0%}, "
             f"mixed {share['m']:.0%}, instrumental {share['i']:.0%}")
    for a_, b, k in regs:
        L.append(f"    {clock(a_):>6} - {clock(b):>6}  {WORD[k]}")
    L.append("  {note}if singing shows as instrumental: lower the gate, e.g. 'pref vocal_gate_db = "
             f"{a['gate'] - 6:.0f}' ('auto' again: 'pref reset vocal_gate_db'); more green vs teal: "
             f"'pref vocal_lead_db = {a['lead'] - 3:g}'{{/}}")
    return L
