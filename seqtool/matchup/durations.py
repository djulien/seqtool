"""Effect duration limits and one-aspect variations (0.20, the user's requests).

    scoring.durations    the shortest and longest an effect may last:
        {"default": {"min": 1.0, "max": "8 bars"},
         "family": {"color": {"max": "16 bars"}}, "effect": {"fire": {"max": "16 bars"}},
         "pass": {"top": {"max": "16 bars"}}}
      a number is seconds; "N bars" / "N beats" follow the song's tempo; null = no limit.
      The most specific wins: effect, then family, then pass, then default.

    scoring.passes.variation   what happens to an effect that would run past its maximum:
        {"enabled": true, "aspect": "auto", "every": 4}
      it is divided on phrase lines (every N bars, from its start) and each part changes
      exactly one aspect from the part before: its colours (the palette turned on by one),
      its direction (the next direction choice), or the effect itself (the next best
      choice, keeping colours) - 'auto' alternates direction and colour (colour only when
      the effect has no direction). Repeated sections get the same variations (nothing
      here is random).

Under the minimum, a segment that isn't at a section start is absorbed by the segment
before it on the same row (or the one after). Pinned segments, reactive plans and the
base pass's moments are left alone.
"""
from __future__ import annotations

import re
from bisect import bisect_left

from ..common.vocab import lit

DEFAULTS = {"default": {"min": 1.0, "max": "8 bars"}, "family": {"color": {"max": "16 bars"}}}
VAR_DEFAULTS = {"enabled": True, "aspect": "auto", "every": 4}
ASPECT_WORD = {"color": "colour only", "direction": "direction only", "effect": "effect only"}


def seconds(v, beat: float) -> float | None:
    """2.5 | "4 bars" | "8 beats" | None -> seconds (None = no limit)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.fullmatch(r"\s*([\d.]+)\s*(bars?|beats?|s|sec|seconds?)?\s*", str(v))
    if not m:
        return None
    n, unit = float(m.group(1)), (m.group(2) or "s")
    return n * 4 * beat if unit.startswith("bar") else n * beat if unit.startswith("beat") else n


def limits(cfg: dict, effect: str, family: str, pass_: str, beat: float) -> tuple[float | None, float | None]:
    cfg = cfg or DEFAULTS
    out = {}
    for key in ("min", "max"):
        v = "unset"
        for scope, name in (("effect", effect), ("family", family), ("pass", pass_)):
            node = (cfg.get(scope) or {}).get(name) or {}
            if key in node:
                v = node[key]
                break
        if v == "unset":
            v = (cfg.get("default") or {}).get(key)
        out[key] = seconds(v, beat)
    return out["min"], out["max"]


def _section_starts(profile: dict) -> set[float]:
    return {round(s["start"], 2) for s in profile["sections"]}


def enforce_min(plan: dict, cfg: dict, beat: float, starts: set[float]) -> int:
    """Absorb too-short segments into a neighbour. Returns how many."""
    segs, n, i = plan["segments"], 0, 0
    while i < len(segs):
        g = segs[i]
        mn, _ = limits(cfg, g["selected"]["effect"], g["selected"].get("family", ""), plan.get("pass", "main"), beat)
        d = g["end"] - g["start"]
        if mn is None or d >= mn - 1e-6 or g.get("pinned"):
            i += 1
            continue
        prev = segs[i - 1] if i > 0 else None
        nxt = segs[i + 1] if i + 1 < len(segs) else None
        at_start = round(g["start"], 2) in starts
        if prev and not prev.get("pinned") and abs(prev["end"] - g["start"]) < 0.05 and not at_start:
            segs[i - 1] = {**prev, "end": g["end"], "reasons": prev.get("reasons", []) +
                           [f"lasts on over a {d:.1f} s {g['selected']['effect']} (shorter than the {mn:.1f} s minimum)"]}
            segs.pop(i)
            n += 1
            continue
        if nxt and not nxt.get("pinned") and abs(g["end"] - nxt["start"]) < 0.05 and \
                round(nxt["start"], 2) not in starts:
            segs[i + 1] = {**nxt, "start": g["start"], "reasons": nxt.get("reasons", []) +
                           [f"starts early over a {d:.1f} s {g['selected']['effect']} (shorter than the {mn:.1f} s minimum)"]}
            segs.pop(i)
            n += 1
            continue
        i += 1
    return n


def _cuts(a: float, b: float, downs: list[float], every_s: float) -> list[float]:
    """Phrase lines from a every `every_s`, moved to the nearest downbeat."""
    out, t = [], a + every_s
    while t < b - every_s * 0.5:
        j = bisect_left(downs, t)
        near = [x for x in downs[max(0, j - 1):j + 1] if a + 1.0 < x < b - 1.0]
        best = min(near, key=lambda x: abs(x - t)) if near else None
        c = best if best is not None and abs(best - t) < every_s * 0.3 else t
        if not out or c - out[-1] > 1.0:
            out.append(round(c, 3))
        t += every_s
    return out


def _vary(g: dict, part: int, of: int, aspect: str, state: dict, effs: dict, pal_map: dict, layer: int) -> dict:
    eff = state["effect"]
    params = dict(state["params"])
    if aspect == "direction":
        ch = (effs.get(eff, {}).get("parameters", {}).get("direction") or {}).get("choices") or []
        if ch:
            cur = params.get("direction", ch[0])
            params["direction"] = ch[(ch.index(cur) + 1) % len(ch)] if cur in ch else ch[0]
    elif aspect == "color":
        state["rot"] += 1
    elif aspect == "effect":
        alts = [x["effect"] for x in g.get("alternatives", []) if lit(x["effect"]) and x["effect"] != eff
                and layer in effs.get(x["effect"], {}).get("layers", [0])]
        new = state["original"] if eff != state["original"] else (alts[0] if alts else eff)
        if new != eff:
            spec = effs.get(new, {}).get("parameters", {})
            params = {k: v for k, v in state["orig_params"].items() if k in spec}
            for k, sp in spec.items():
                if k not in params:
                    params[k] = sp["choices"][0] if "choices" in sp else round(sum(sp["range"]) / 2, 3)
            eff = new
    state["effect"], state["params"] = eff, params
    cols = list(g.get("palette_colors") or pal_map.get(g.get("palette", "base"), []))
    seg = {**g, "selected": {**g["selected"], "effect": eff, "family": effs.get(eff, {}).get("family", "")},
           "parameters": params, "variation": {"part": part, "of": of, "aspect": aspect},
           "reasons": list(g.get("reasons", [])) + [f"variation {part} of {of} ({ASPECT_WORD[aspect]})"]}
    if cols and state["rot"]:
        r = state["rot"] % len(cols)
        seg["palette_colors"] = cols[r:] + cols[:r]
    return seg


def enforce_max(plan: dict, cfg: dict, vcfg: dict, beat: float, downs: list[float], effs: dict,
                pal_map: dict) -> int:
    """Divide too-long segments into one-aspect variations. Returns how many were divided."""
    vcfg = {**VAR_DEFAULTS, **(vcfg or {})}
    if not vcfg.get("enabled", True):
        return 0
    every_s = max(2 * beat, float(vcfg.get("every", 4)) * 4 * beat)
    out, n = [], 0
    for g in plan["segments"]:
        e = g["selected"]["effect"]
        _, mx = limits(cfg, e, g["selected"].get("family", ""), plan.get("pass", "main"), beat)
        if mx is None or g["end"] - g["start"] <= mx + 1e-6 or g.get("pinned") or not lit(e) or g.get("moment"):
            out.append(g)
            continue
        cuts = _cuts(g["start"], g["end"], downs, every_s)
        if not cuts:
            out.append(g)
            continue
        n += 1
        has_dir = bool((effs.get(e, {}).get("parameters", {}).get("direction") or {}).get("choices"))
        want = vcfg.get("aspect", "auto")
        cycle = (["direction", "color"] if has_dir else ["color"]) if want == "auto" else \
            ([want] if want != "direction" or has_dir else ["color"])
        bounds = [g["start"]] + cuts + [g["end"]]
        of = len(bounds) - 1
        state = {"effect": e, "original": e, "params": dict(g.get("parameters", {})),
                 "orig_params": dict(g.get("parameters", {})), "rot": 0}
        for k in range(of):
            piece = {**g, "start": bounds[k], "end": bounds[k + 1]}
            if k == 0:
                piece = {**piece, "variation": {"part": 1, "of": of, "aspect": "first"},
                         "reasons": list(g.get("reasons", [])) + [f"variation 1 of {of} (as chosen; it would run "
                                                                  f"{g['end'] - g['start']:.0f} s, the maximum is "
                                                                  f"{mx:.0f} s)"]}
            else:
                piece = _vary(piece, k + 1, of, cycle[(k - 1) % len(cycle)], state, effs, pal_map, plan.get("layer", 0))
            if k:
                piece.pop("continuity", None)
            out.append(piece)
    plan["segments"] = out
    return n


def apply(plans: list[dict], music: dict, profile: dict, effects_cfg: dict, palettes: dict, scfg: dict,
          notes: list) -> None:
    cfg = scfg.get("durations") or DEFAULTS
    vcfg = (scfg.get("passes") or {}).get("variation") or VAR_DEFAULTS
    bpm = music["analysis"]["summary"].get("tempo", {}).get("bpm") or 120.0
    beat = 60.0 / bpm
    ev = music["analysis"]["events"]
    downs = sorted(e["time"] for e in ev.get("downbeats", [])) or sorted(e["time"] for e in ev.get("beats", []))[::4]
    starts = _section_starts(profile)
    pal_map = {k: v["colors"] for k, v in palettes.items()}
    absorbed = divided = 0
    for p in plans:
        if p.get("react") or p.get("pass") not in (None, "main", "top"):
            continue
        absorbed += enforce_min(p, cfg, beat, starts)
        divided += enforce_max(p, cfg, vcfg, beat, downs, effects_cfg["effects"], pal_map)
    if absorbed or divided:
        notes.append(f"durations: {divided} long effect(s) varied one aspect at a time, {absorbed} short one(s) "
                     "absorbed by a neighbour (scoring.durations, scoring.passes.variation)")
