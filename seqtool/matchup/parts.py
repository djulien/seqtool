"""The pieces every way of placing an effect shares (0.24.53, plan step 7).

Pins, reactions, choreographies and whole-yard moments each place effects; before, each built
its segments, read settings and times its own way. They now share these:

    segment()        one planned effect: times, section, effect + family, settings, why
    setting_specs()  an effect's settings plus the ones any effect takes (render, area, rotation)
    read_settings()  NAME=VALUE settings as you give them ('dense', '0.2..0.9', '10oclock')
    duration()       a time as you give it: 0.5, '2s', '1b' (bars), '3beats', '25%'
    effect_name()    an effect by seqtool's name or xLights' ('On' -> pulse)
    glide_runs()     keyframe steps -> runs of glides, one effect each with a curve per setting
"""
from __future__ import annotations

import json
import re
from pathlib import Path

EXTRA_SPECS = {"render": {"choices": ["default", "per-model"]},   # a group's effect: as one / per prop
               "area": {"area": True},                            # where on the prop (0.24.46)
               "rotation": {"angle": True}}                       # turned (0.24.48)
_DUR = re.compile(r"^(-?\d+(?:\.\d+)?)\s*(s|sec|secs|seconds?|b|bars?|beats?|%)?$")
DURATION_HELP = "a time in s, bars (1b), beats (2beats) or % - e.g. '2b', '1.5beats', '25%'"


def segment(start: float, end: float, effect: str, section: dict, *, family: str = "", params: dict | None = None,
            why: str = "", palette: str | None = "base", **extra) -> dict:
    seg = {"start": round(start, 3), "end": round(end, 3), "section": section["id"],
           "section_index": section.get("index", 0),
           "selected": {"effect": effect, "family": family or effect, "score": 1.0},
           "parameters": dict(params or {}), "score_breakdown": {"final": 1.0}, "alternatives": [],
           "reasons": [why] if why else [], "why": why}
    if palette is not None:
        seg["palette"] = palette
    seg.update({k: v for k, v in extra.items() if v is not None})
    return seg


def setting_specs(effect_spec: dict) -> dict:
    return {**(effect_spec or {}).get("parameters", {}), **EXTRA_SPECS}


def read_settings(effect: str, effect_spec: dict, given: dict, glides: bool = True) -> tuple[dict, list[str], list[str]]:
    """{name: text} -> (settings, the names you gave, problems). A problem leaves that setting out."""
    from .parameters import glide_value, user_value
    specs = setting_specs(effect_spec)
    out, yours, bad = {}, [], []
    for k, v in (given or {}).items():
        k = str(k).lower()
        if k not in specs:
            bad.append(f"{effect} has no setting '{k}' ('effects {effect}' shows them)")
            continue
        try:
            text = v if not isinstance(v, list) else ",".join(map(str, v))
            out[k] = (glide_value if glides else user_value)(k, specs[k], text)
        except ValueError as e:
            bad.append(str(e))
            continue
        if k == "render":
            out[k] = str(out[k]).replace("-", "_")
        yours.append(k)
    return out, yours, bad


def duration(text, span: float, beat: float) -> float:
    """seconds; '%' is of `span`. ValueError when it isn't a time."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text)
    m = _DUR.match(str(text).strip().lower())
    if not m:
        raise ValueError(DURATION_HELP)
    n, u = float(m.group(1)), (m.group(2) or "s")
    if u == "%":
        return span * n / 100
    if u.startswith("beat"):
        return beat * n
    if u.startswith("b"):
        return 4 * beat * n
    return n


def effect_name(name: str, effects: dict) -> str | None:
    from ..common.vocab import canon
    eff = canon(str(name))
    if eff in effects:
        return eff
    try:
        em = json.loads((Path(__file__).parents[1] / "adapters" / "xlights" / "effect_map.json")
                        .read_text(encoding="utf-8"))["effects"]
    except (OSError, ValueError, KeyError):
        return None
    hit = next((g for g, x in em.items() if isinstance(x, str) and x.lower() == eff.lower()), None)
    return hit if hit in effects else None


def _same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-3
    return a == b


def glide_runs(pieces: list, keys: list | None = None) -> list[tuple[float, float, dict, int]]:
    """keyframes.steps_for() pieces [(a, b, values, step)] -> [(a, b, values, first step)]: pieces
    that carry on from each other (each setting ends where the next starts) are one run, its
    gliding settings {"ramp": [a, b]} or {"curve": [[t, y], ...]} over the run; a jump (a held
    value, a choice changing) starts the next run."""
    keys = keys or sorted({k for _, _, vals, _ in pieces for k in (vals or {})})

    def ends(v):
        if isinstance(v, dict) and "ramp" in v:
            return v["ramp"][0], v["ramp"][1]
        return v, v
    groups, cur = [], []
    for a, b, vals, si in pieces:
        vals = vals or {}
        if cur and any(not _same(ends(cur[-1][2].get(k))[1], ends(vals.get(k))[0]) for k in keys):
            groups.append(cur)
            cur = []
        cur.append((a, b, vals, si))
    if cur:
        groups.append(cur)
    out = []
    for grp in groups:
        a0, b0 = grp[0][0], grp[-1][1]
        span = (b0 - a0) or 1.0
        vals = dict(grp[0][2])
        for k in keys:
            pts = [((grp[0][0] - a0) / span, ends(grp[0][2].get(k))[0])]
            pts += [((b - a0) / span, ends(v.get(k))[1]) for _, b, v, _ in grp]
            ys = [y for _, y in pts]
            if not all(isinstance(y, (int, float)) and not isinstance(y, bool) for y in ys) or len({round(y, 6) for y in ys}) == 1:
                vals[k] = ys[0]
            elif len(pts) == 2:
                vals[k] = {"ramp": [ys[0], ys[1]]}
            else:
                vals[k] = {"curve": [[round(t, 4), y] for t, y in pts]}
        out.append((a0, b0, vals, grp[0][3]))
    return out
