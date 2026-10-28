"""CSS-style keyframes for reaction presets.

    "keyframes": {
      "from":        {"position": 0},
      "37.5%":       {"position": 0.8, "animation-timing-function": "ease-out"},
      "62.5%, 87.5%":{"position": 0.2},
      "75%":         {"position": 0.9}
    }

Selectors are CSS keyframe selectors: percentages of the event (a bar when the
preset is 'on: downbeat'), 'from' (= 0%) and 'to' (= 100%), or a comma list.
Each keyframe starts a step at that point; a step lasts until the next
keyframe. Values carry over from earlier keyframes and the preset's params.

animation-timing-function (CSS names) says how a step gets to the next
keyframe's values:
    step-end (default here - hold the value; CSS's default would be ease),
    linear, ease, ease-in, ease-out, ease-in-out, cubic-bezier(x1, y1, x2, y2),
    steps(N) (N equal holds), step-start
Glides become ramps ({"ramp": [a, b]}): curved ones are split into short
linear pieces so any ramp-capable output (xLights value curves) can follow.
"""
from __future__ import annotations

import re

EASING = {"linear": (0.0, 0.0, 1.0, 1.0), "ease": (0.25, 0.1, 0.25, 1.0), "ease-in": (0.42, 0.0, 1.0, 1.0),
          "ease-out": (0.0, 0.0, 0.58, 1.0), "ease-in-out": (0.42, 0.0, 0.58, 1.0)}
TF_KEYS = ("animation-timing-function", "timing")
PIECES = 3                     # linear pieces per curved glide


def offsets(selector: str) -> list[float]:
    out = []
    for part in str(selector).split(","):
        s = part.strip().lower()
        if s == "from":
            out.append(0.0)
        elif s == "to":
            out.append(1.0)
        else:
            m = re.fullmatch(r"(-?[\d.]+)\s*%", s)
            if not m:
                raise ValueError(f"keyframe selector {part.strip()!r}: use 'from', 'to' or a percentage like '37.5%'")
            v = float(m.group(1)) / 100
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"keyframe selector {part.strip()!r} is outside 0%-100%")
            out.append(v)
    return out


def parse(kf: dict) -> list[tuple[float, dict]]:
    """{selector: declarations} -> sorted [(offset, declarations)], same offsets merged (later wins, as in CSS)."""
    at: dict[float, dict] = {}
    for sel, decl in kf.items():
        for off in offsets(sel):
            at.setdefault(round(off, 6), {}).update(decl or {})
    return sorted(at.items())


def timing_function(spec: str | None):
    """-> ('hold', None) | ('steps', n, start) | ('curve', (x1, y1, x2, y2))"""
    s = (spec or "step-end").strip().lower()
    if s in ("step-end", "hold", "none"):
        return ("hold", None)
    if s == "step-start":
        return ("steps", 1, True)
    m = re.fullmatch(r"steps\(\s*(\d+)\s*(?:,\s*(jump-start|start|jump-end|end))?\s*\)", s)
    if m:
        return ("steps", max(1, int(m.group(1))), (m.group(2) or "end") in ("start", "jump-start"))
    if s in EASING:
        return ("curve", EASING[s])
    m = re.fullmatch(r"cubic-bezier\(([^)]*)\)", s)
    if m:
        vals = [float(x) for x in m.group(1).split(",")]
        if len(vals) == 4:
            return ("curve", tuple(vals))
    raise ValueError(f"unknown animation-timing-function {spec!r}")


def bezier(p: tuple, x: float) -> float:
    """CSS cubic-bezier: progress (0..1 of time) -> eased progress."""
    x1, y1, x2, y2 = p

    def coord(t, a, b):
        return 3 * a * t * (1 - t) ** 2 + 3 * b * t * t * (1 - t) + t ** 3
    lo, hi = 0.0, 1.0
    for _ in range(40):                       # bisection on x(t) = x
        mid = (lo + hi) / 2
        if coord(mid, x1, x2) < x:
            lo = mid
        else:
            hi = mid
    return coord((lo + hi) / 2, y1, y2)


def steps_for(kfs: list[tuple[float, dict]], base: dict, preset_tf: str | None = None):
    """-> [(start_frac, end_frac, values, step_index)] where values hold plain values
    or {"ramp": [a, b]} for glides. 'base' = the preset's params (unevaluated)."""
    if not kfs or kfs[0][0] > 0:
        kfs = [(0.0, {})] + list(kfs)
    out = []
    cur = dict(base)
    for i, (off, decl) in enumerate(kfs):
        if off >= 1.0:
            break
        cur = {**cur, **{k: v for k, v in decl.items() if k not in TF_KEYS}}
        nxt_off = kfs[i + 1][0] if i + 1 < len(kfs) else 1.0
        nxt = {**cur, **{k: v for k, v in (kfs[i + 1][1] if i + 1 < len(kfs) else {}).items() if k not in TF_KEYS}}
        tf = timing_function(next((decl[k] for k in TF_KEYS if k in decl), None) or preset_tf)
        glide = {k for k in cur if isinstance(cur.get(k), (int, float)) and isinstance(nxt.get(k), (int, float))
                 and not isinstance(cur.get(k), bool) and cur[k] != nxt[k]}
        if tf[0] == "hold" or not glide:
            out.append((off, nxt_off, dict(cur), i))
        elif tf[0] == "steps":
            n, start = tf[1], tf[2]
            for j in range(n):
                frac = (j + (1 if start else 0)) / n
                vals = {k: (cur[k] + (nxt[k] - cur[k]) * frac if k in glide else v) for k, v in cur.items()}
                a = off + (nxt_off - off) * j / n
                b = off + (nxt_off - off) * (j + 1) / n
                out.append((a, b, {k: round(v, 4) if k in glide else v for k, v in vals.items()}, i))
        else:
            curve = tf[1]
            pieces = 1 if curve == EASING["linear"] else PIECES
            for j in range(pieces):
                x0, x1 = j / pieces, (j + 1) / pieces
                e0, e1 = bezier(curve, x0) if pieces > 1 else x0, bezier(curve, x1) if pieces > 1 else x1
                vals = {}
                for k, v in cur.items():
                    if k in glide:
                        vals[k] = {"ramp": [round(cur[k] + (nxt[k] - cur[k]) * e0, 4),
                                            round(cur[k] + (nxt[k] - cur[k]) * e1, 4)]}
                    else:
                        vals[k] = v
                out.append((off + (nxt_off - off) * x0, off + (nxt_off - off) * x1, vals, i))
    return out
