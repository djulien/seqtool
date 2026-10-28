"""Sections from an existing xLights sequence (0.20.3, the user's idea).

Someone has already sequenced the song (by hand, or a bought sequence): where its
effects change all at once and which passages look alike tell the song's structure.

    sections from-xsq Song.xsq [--layout SHOWFOLDER|xlights_rgbeffects.xml] [--apply]

1. Every effect of the .xsq is put on the props it lights: a group's effect on each
   of its members (the layout's groups, nested ones flattened).
2. The song's bars (the current song's analysis) are the grid: for each bar, the set of
   (prop, effect) pairs playing for most of it, and a finer set that also holds the
   colours and the main settings.
3. A bar where many props start a new effect at once, and that looks unlike the bar
   before, is a candidate boundary; the strongest are kept, at least `min_bars` (4)
   apart.
4. Passages are compared bar by bar: alike when most (prop, effect) pairs agree -
   the effect matters most, colours and settings a little (variations in settings
   are allowed for). Alike passages get the same letter (A, B, A, C, A ...).
5. Types: the letter that comes back most, with the busiest effects, is the chorus;
   another repeated letter the verse; a passage at the very start or end that never
   repeats is the intro or outro; any other one-off is a bridge (a breakdown when it
   is sparse).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from bisect import bisect_left
from pathlib import Path

from ..adapters.xlights import xsq as xsq_mod

KEY_SETTINGS = ("Direction", "Speed", "Style", "Type", "Effect")


def layout_groups(xml: Path) -> dict[str, list[str]]:
    """{group: [models]} from xlights_rgbeffects.xml, nested groups flattened."""
    root = ET.parse(xml).getroot()
    raw = {g.get("name"): [x.strip() for x in (g.get("models") or "").split(",") if x.strip()]
           for g in root.iter("modelGroup") if g.get("name")}

    def flat(n, seen):
        out = []
        for x in raw.get(n, []):
            base = x.split("/", 1)[0]
            if x in raw and x not in seen:
                out += flat(x, seen | {x})
            else:
                out.append(base)
        return out
    return {g: list(dict.fromkeys(flat(g, {g}))) for g in raw}


def _sig(e) -> tuple:
    keys = sorted(k for k in e.settings if any(w in k for w in KEY_SETTINGS))
    cols = tuple(xsq_mod.enabled_colors(e.palette))
    return (xsq_mod.norm(e.name), cols, tuple((k, e.settings[k]) for k in keys[:6]))


def bar_sets(seq, groups: dict, bars: list[float]):
    """Per bar: (pairs, sigs, starts) - the (prop, effect) pairs playing most of the bar,
    the same with colours and settings, and the props whose effect starts on it."""
    n = len(bars) - 1
    pairs = [set() for _ in range(n)]
    sigs = [set() for _ in range(n)]
    starts = [set() for _ in range(n)]
    for e in seq.effects:
        if e.element_type not in ("model", "submodel") or e.end <= e.start:
            continue
        who = groups.get(e.element) or [e.element.split("/", 1)[0]]
        eff, sg = xsq_mod.norm(e.name), _sig(e)
        i0 = max(0, bisect_left(bars, e.start) - 1)
        for i in range(i0, n):
            a, b = bars[i], bars[i + 1]
            if a >= e.end:
                break
            ov = min(b, e.end) - max(a, e.start)
            if ov >= 0.5 * (b - a):
                for m in who:
                    pairs[i].add((m, eff))
                    sigs[i].add((m, sg))
            if abs(e.start - a) <= 0.2 * (b - a):
                starts[i].update(who)
    return pairs, sigs, starts


def _jac(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a or b else 1.0


def boundaries(pairs, sigs, starts, min_bars: int = 4) -> list[tuple[int, float]]:
    """[(bar index, strength)] including bar 0."""
    n = len(pairs)
    cand = []
    for i in range(1, n):
        active = {m for m, _ in pairs[i]} | {m for m, _ in pairs[i - 1]}
        if not active:
            continue
        share = len(starts[i] & active) / len(active)
        change = 1.0 - _jac(pairs[i - 1], pairs[i])
        s = 0.6 * share + 0.4 * change
        if share >= 0.3 and change >= 0.3:
            cand.append((i, round(s, 3)))
    keep: list[tuple[int, float]] = []
    for i, s in sorted(cand, key=lambda c: -c[1]):
        if all(abs(i - j) >= min_bars for j, _ in keep) and i >= min_bars // 2 and n - i >= min_bars // 2:
            keep.append((i, s))
    return [(0, 1.0)] + sorted(keep)


def similarity(pairs, sigs, a: tuple[int, int], b: tuple[int, int]) -> float:
    la, lb = a[1] - a[0], b[1] - b[0]
    if not la or not lb or min(la, lb) / max(la, lb) < 0.6:
        return 0.0
    k = min(la, lb)
    vals = [0.8 * _jac(pairs[a[0] + j], pairs[b[0] + j]) + 0.2 * _jac(sigs[a[0] + j], sigs[b[0] + j]) for j in range(k)]
    return sum(vals) / k


def analyse(xsq_path: Path, layout_xml: Path | None, music: dict, min_bars: int = 4) -> dict:
    seq = xsq_mod.read(xsq_path)
    groups = layout_groups(layout_xml) if layout_xml else {}
    ev = music["analysis"]["events"]
    downs = sorted(e["time"] for e in ev.get("downbeats", [])) or sorted(e["time"] for e in ev.get("beats", []))[::4]
    dur = music["audio"]["duration"]
    bars = [0.0] + [d for d in downs if 0.05 < d < dur - 0.05] + [dur]
    pairs, sigs, starts = bar_sets(seq, groups, bars)
    bnd = boundaries(pairs, sigs, starts, min_bars)
    edges = [i for i, _ in bnd] + [len(pairs)]
    segs = [(edges[k], edges[k + 1]) for k in range(len(edges) - 1) if edges[k + 1] > edges[k]]
    n = len(segs)
    letter: list[int | None] = [None] * n
    best: list[tuple[int, float] | None] = [None] * n
    nxt = 0
    for i in range(n):
        for j in range(i):
            s = similarity(pairs, sigs, segs[j], segs[i])
            if s >= 0.6 and (best[i] is None or s > best[i][1]):
                best[i] = (j, round(s, 2))
        if best[i]:
            letter[i] = letter[best[i][0]]
        else:
            letter[i] = nxt
            nxt += 1
    dens = [sum(len(pairs[x]) for x in range(a, b)) / max(1, b - a) for a, b in segs]
    count = {L: letter.count(L) for L in set(letter)}
    rep = [L for L in count if count[L] >= 2]
    mean = {L: sum(d for d, l in zip(dens, letter) if l == L) / count[L] for L in count}
    by_busy = sorted(rep, key=lambda L: (-mean[L], -count[L], L))       # the busiest repeated one: the chorus
    kind = {}
    if by_busy:
        kind[by_busy[0]] = "chorus"
        for L in by_busy[1:]:
            kind[L] = "verse"
    med = sorted(dens)[len(dens) // 2] if dens else 0
    out = []
    for i, ((a, b), L) in enumerate(zip(segs, letter)):
        t = kind.get(L)
        if t is None:
            t = "intro" if i == 0 else "outro" if i == n - 1 else ("breakdown" if dens[i] < 0.6 * med else "bridge")
        out.append({"index": i + 1, "start": round(bars[a], 3), "end": round(bars[b], 3), "bars": b - a,
                    "letter": chr(ord("A") + L % 26), "type": t, "like": (best[i][0] + 1) if best[i] else None,
                    "similarity": best[i][1] if best[i] else None, "density": round(dens[i], 1),
                    "strength": next((s for j, s in bnd if j == a), None)})
    return {"sections": out, "effects": len(seq.effects), "props": len({m for p in pairs for m, _ in p}),
            "groups_known": bool(groups), "version": seq.version}
