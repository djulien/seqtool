"""Abstract (xLights-independent) parameters and palettes.

Seeded choices are keyed on the section's *repeat root*, so every chorus that
repeats chorus 1 makes the same direction choice -> visual motifs recur with
the music instead of being re-rolled each time.
"""
from __future__ import annotations

from ..common.seed import sub_rng


def parameters(effect_id: str, eff: dict, feats: dict, target_id: str,
               repeat_key: str, seed: int, shape: str | None = None) -> dict:
    out = {}
    for name, spec in eff.get("parameters", {}).items():
        if spec.get("text") or ("default" in spec and "range" not in spec and "choices" not in spec):
            if "default" in spec:                      # 0.24.46: a setting you give (a picture's file)
                out[name] = spec["default"]
            continue
        if "choices" in spec and "default" in spec:
            out[name] = spec["default"]
            continue
        if "choices" in spec:
            rng = sub_rng(seed, "param", target_id, effect_id, repeat_key, name)
            ch = (spec.get("by_class") or {}).get(shape or "") or spec["choices"]   # 0.24.25: per prop shape
            out[name] = ch[rng.randrange(len(ch))]
        else:
            lo, hi = spec["range"]
            x = feats.get(spec["driver"], 0.5)
            out[name] = round(lo + (hi - lo) * x, 3)
    return out


VALUE_WORDS = {"min": 0.0, "none": 0.0, "very low": 0.1, "sparse": 0.2, "slow": 0.2, "low": 0.2, "few": 0.25,
               "medium-slow": 0.35, "medium-low": 0.35, "medium": 0.5, "neutral": 0.5, "normal": 0.5,
               "medium-fast": 0.65, "medium-high": 0.65, "fast": 0.8, "high": 0.8, "many": 0.8, "dense": 0.9,
               "full": 1.0, "max": 1.0, "very high": 0.95, "very fast": 0.95}


ANGLE_HELP = "an angle: 90deg, 3oclock (12 o'clock = 0), or a share of a turn 0-1 / 0-100%"


def angle_value(name: str, text) -> float:
    """'90deg' / '90°' -> 0.25; "3oclock" / "3 o'clock" / '3:00' -> 0.25 (12 = 0, clockwise);
    0.25 / '25%' -> 0.25. A share of one turn, 0..1."""
    import re as _re
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        v = float(text)
        return round(v / 100 if v > 1 else v, 4)
    t = str(text).strip().lower().replace("’", "'").replace(" ", "")
    m = _re.fullmatch(r"(\d+(?:\.\d+)?)(?:o'?clock|:00|h)", t)
    if m:
        return round((float(m.group(1)) % 12) / 12, 4)
    m = _re.fullmatch(r"(-?\d+(?:\.\d+)?)(?:deg|degrees?|°)", t)
    if m:
        d = float(m.group(1))
        return round(d / 360 if 0 <= d <= 360 else (d % 360) / 360, 4)      # 360deg: a whole turn
    try:
        v = float(t.rstrip("%"))
    except ValueError:
        raise ValueError(f"{name}: {ANGLE_HELP}") from None
    if t.endswith("%") or v > 1:
        v /= 100
    if not 0 <= v <= 1:
        raise ValueError(f"{name}: {ANGLE_HELP}")
    return round(v, 4)


def glide_value(name: str, spec: dict, text: str):
    """'0.2..0.9' -> {"ramp": [0.2, 0.9]}; '10oclock..7oclock..10oclock' -> {"curve": [[0, a], [0.5, b],
    [1, c]]} (evenly spaced) - a setting that changes over the effect (0.24.48). Else user_value."""
    parts = [x for x in str(text).split("..")] if isinstance(text, str) and ".." in text else None
    if not parts or len(parts) < 2 or any(not x.strip() for x in parts):
        return user_value(name, spec, text)
    if "choices" in spec or spec.get("text") or spec.get("area"):
        raise ValueError(f"{name}: only a number or an angle can change over the effect (a..b)")
    vals = [user_value(name, spec, x) for x in parts]
    if len(vals) == 2:
        return {"ramp": vals}
    n = len(vals) - 1
    return {"curve": [[round(i / n, 4), v] for i, v in enumerate(vals)]}


def user_value(name: str, spec: dict, text: str):
    """A setting you give a pinned effect (0.24.36: 'pin Matrix @#1 meteors direction=explode
    speed=medium-fast'): a choice by name, or a level 0-1 / 0-100% / a word (low ... dense)."""
    if spec.get("text"):                               # a name or a file, as given
        return str(text).strip()
    if spec.get("area"):                               # x,y,w,h in percent from the top left
        try:
            v = [float(x) for x in str(text).split(",")]
        except ValueError:
            v = []
        if len(v) != 4 or any(x < 0 or x > 100 for x in v):
            raise ValueError(f"{name}: x,y,w,h in percent from the top left, e.g. 0,37,25,25")
        return v
    if spec.get("angle"):                              # 0.24.48: a turn - degrees, o'clock or a share
        return angle_value(name, text)
    t = str(text).strip().lower().replace("_", "-")
    if "choices" in spec:
        hit = [c for c in spec["choices"] if c.lower() == t] or [c for c in spec["choices"] if c.lower().startswith(t)]
        if len(hit) != 1:
            raise ValueError(f"{name}: one of {', '.join(spec['choices'])}")
        return hit[0]
    if t in VALUE_WORDS:
        return VALUE_WORDS[t]
    try:
        v = float(t.rstrip("%"))
    except ValueError:
        raise ValueError(f"{name}: a level 0-1 (or 0-100%, or {', '.join(k for k in VALUE_WORDS if ' ' not in k)})") from None
    if t.endswith("%") or v > 1.0:
        v /= 100.0
    if not 0.0 <= v <= 1.0:
        raise ValueError(f"{name}: a level 0-1")
    return round(v, 3)


def hue_shift(color: str, deg: float) -> str:
    """#RRGGBB turned round the colour wheel by deg (greys and white stay)."""
    import colorsys
    c = color.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l_, s = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb((h + deg / 360.0) % 1.0, l_, s)
    return "#" + "".join(f"{round(v * 255):02X}" for v in (r, g, b))


def build_palettes(styles: dict, pal_cfg: dict, seed: int, override: dict | None = None) -> tuple[dict, str, str]:
    """Return (palettes, base_id, accent_id). override (0.24.25, 'palette' for a song): {"style": S
    - its palettes instead of the music's style, "pick": N (0-based) - that one of them, "hue": DEG
    - every colour turned round the colour wheel}."""
    ov = override or {}
    ranked = sorted(styles.items(), key=lambda kv: (-kv[1], kv[0]))
    lib = pal_cfg["styles"]
    auto = next((s for s, p in ranked if s in lib and p > 0), "unknown")
    style = ov["style"] if ov.get("style") in lib else auto
    choices = lib[style]
    pick = sub_rng(seed, "palette", style).randrange(len(choices))
    if ov.get("pick") is not None and ov.get("style") == style:
        pick = int(ov["pick"]) % len(choices)
    base = list(choices[pick])
    rot = sub_rng(seed, "palette-rot", style).randrange(len(base))
    base = base[rot:] + base[:rot]
    own = [c.upper() for c in (ov.get("colors") or [])]          # 0.24.46: your colours for this song, as given
    if own:
        base, rot, style = own, 0, "yours"
    hue = float(ov.get("hue") or 0.0)
    if hue:
        base = [hue_shift(c, hue) for c in base]
    if ov.get("warmth") is not None and float(ov["warmth"]) != 0.5:      # 'feel warmth' (0.24.30)
        from .feel import warm
        base = [warm(c, float(ov["warmth"])) for c in base]
    acc_cols = [c.upper() for c in ov["accent"]] if own and ov.get("accent") else pal_cfg.get("high_energy_accent", [])
    accent = base[:3] + [c for c in acc_cols if c not in base]
    top = ranked[0] if ranked else ("unknown", 0)
    if own:
        why = f"your colours ('palette colors'; the music's style is '{auto}')"
    elif style != auto:
        why = f"style '{style}' chosen by you ('palette'; the music's is '{auto}')"
    else:
        why = (f"style '{style}' ({styles.get(style, 0):.2f}" +
               (", the strongest style" if top[0] == style else f"; '{top[0]}' scored higher but has no palettes") + ")")
    why += ("" if own else (f": palette {pick + 1} of {len(choices)}"
                            + (" (yours)" if ov.get("pick") is not None and ov.get("style") == style else " (chosen by the seed)")
                            + f", colours rotated by {rot}"))
    why += (f", turned {hue:+.0f} degrees round the colour wheel (yours)" if hue else "")
    why += (f", {'warmer' if float(ov['warmth']) > 0.5 else 'cooler'} ('feel warmth {ov['warmth']}')"
            if ov.get("warmth") is not None and float(ov["warmth"]) != 0.5 else "")
    return ({"base": {"colors": base, "style": style, "why": why, "auto_style": auto, "pick": pick, "hue": hue},
             "accent": {"colors": accent, "style": style,
                        "why": "high-energy segments (energy >= 0.75): the base palette's first 3 colours plus "
                               + ", ".join(pal_cfg.get("high_energy_accent", [])) + "; " + why}},
            "base", "accent")
