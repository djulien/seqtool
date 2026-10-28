"""Creative controls - the song's 'feel' (0.24.30).

Four broad settings, each 0..1 with 0.5 = as seqtool does it anyway; they turn existing
planning settings, the same way every time (no randomness of their own):

    busy       how often effects change: continuity's change penalty and persistence bonus,
               and the decision window length (busy = shorter windows, more changes)
    intensity  which effects win: effects made for loud music (music_fit.energy) score higher
               (intense) or lower (calm) - per song, or per section (and its repeats)
    warmth     the palette's colours pulled towards warm (reds, ambers) or cool (blues)
    unison     the yard together or each prop its own: how many whole-yard moments (base pass)

Stored per song (songs.json "feel": {"busy": 0.7, ..., "sections": [{"name", "at", "value",
"repeats"}]}); 'feel' sets them.
"""
from __future__ import annotations

import copy

NAMES = ("busy", "intensity", "warmth", "unison")
PER_SECTION = ("intensity",)
ABOUT = {
    "busy": "how often effects change: 0 = long, steady effects ... 1 = they change often",
    "intensity": "which effects: 0 = calm (washes, twinkles) ... 1 = intense (chases, strobes, fire)",
    "warmth": "colours: 0 = cool (blues) ... 1 = warm (reds, ambers)",
    "unison": "together or apart: 0 = every prop its own, no whole-yard moments ... 1 = more moments "
              "where the whole yard moves together",
}
WORDS = {"low": 0.2, "lower": 0.35, "neutral": 0.5, "normal": 0.5, "medium": 0.5, "higher": 0.65, "high": 0.8,
         "min": 0.0, "max": 1.0}


def value(text: str) -> float:
    t = str(text).strip().lower()
    if t in WORDS:
        return WORDS[t]
    pct = t.endswith("%")
    v = float(t.rstrip("%"))
    if pct or v > 1.0:
        v /= 100.0
    if not 0.0 <= v <= 1.0:
        raise ValueError(t)
    return round(v, 3)


def song_value(feel: dict | None, name: str) -> float:
    v = (feel or {}).get(name)
    return 0.5 if v is None else float(v)


def apply_scoring(scfg: dict, feel: dict | None) -> dict:
    """The scoring preferences turned by busy and unison."""
    if not feel:
        return scfg
    s = copy.deepcopy(scfg)
    b = song_value(feel, "busy")
    if b != 0.5:
        f = 2 ** ((0.5 - b) * 2)                       # busy 1: half the change penalty; 0: double
        c = s.setdefault("continuity", {})
        for k in ("change_penalty", "persistence_bonus"):
            if k in c:
                c[k] = round(c[k] * f, 4)
        d = s.setdefault("decision", {})
        g = 2 ** ((0.5 - b) * 1.0)                     # busy 1: windows ~0.7x as long; 0: ~1.4x
        for k in ("target_window", "min_window", "max_window"):
            if k in d:
                d[k] = round(d[k] * g, 3)
    u = song_value(feel, "unison")
    if u != 0.5:
        base = s.setdefault("passes", {}).setdefault("base", {})
        if u <= 0.05:
            base["enabled"] = False
        else:
            base["per_minute"] = round(float(base.get("per_minute", 1.5)) * 2 ** ((u - 0.5) * 2.4), 3)
    return s


def intensity_map(feel: dict | None, profile: dict, windows) -> dict | None:
    """{"song": i, "by_section": {section id: i}} for plan_target, or None when all neutral."""
    if not feel:
        return None
    song = song_value(feel, "intensity")
    by: dict[str, float] = {}
    from .pins import _section_at
    roots = {w.section_id: w.section_repeat_key for w in windows}
    for e in feel.get("sections") or []:
        if e.get("name") != "intensity" or e.get("at") is None:
            continue
        sec = _section_at(profile, float(e["at"]))
        root = roots.get(sec["id"], sec["id"])
        for sid, rk in roots.items():
            if sid == sec["id"] or (e.get("repeats", True) and rk == root):
                by[sid] = float(e["value"])
    if song == 0.5 and not by:
        return None
    return {"song": song, "by_section": by}


def intensity_factor(fi: dict, window, eff: dict) -> float:
    """How much an effect's score is turned in this window: effects for loud music (energy
    near 1) up when intense, down when calm; effects for quiet music the other way."""
    i = fi["by_section"].get(window.section_id, fi["song"])
    if i == 0.5 or eff.get("family") == "none":
        return 1.0
    en = float((eff.get("music_fit") or {}).get("energy", 0.5))
    return max(0.1, 1.0 + 0.6 * (2 * i - 1) * (2 * en - 1))


def with_warmth(palette: dict | None, feel: dict | None) -> dict | None:
    w = song_value(feel, "warmth")
    if w == 0.5:
        return palette
    return {**(palette or {}), "warmth": w}


def warm(color: str, w: float) -> str:
    """#RRGGBB pulled round the colour wheel towards warm (30 degrees) or cool (215)."""
    import colorsys
    c = color.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l_, s = colorsys.rgb_to_hls(r, g, b)
    if s < 0.08:                                       # white, greys: as they are
        return "#" + c.upper()
    target = 30 / 360 if w > 0.5 else 215 / 360
    amt = abs(w - 0.5) * 2 * 0.6
    d = ((target - h + 0.5) % 1.0) - 0.5               # the short way round
    r, g, b = colorsys.hls_to_rgb((h + d * amt) % 1.0, l_, s)
    return "#" + "".join(f"{round(v * 255):02X}" for v in (r, g, b))
