"""Static (per-window) scoring: gates first, then a weighted sum.

Hard gates run BEFORE the weighted sum so that a disallowed or physically
unsuitable effect can never win just because the music loves it.

model_fit vs capability_fit (kept distinct, as the design requires):
  model_fit      - curated table: how good does this effect look on this
                   *class* of prop (geometry_class from models.json)
  capability_fit - measured: does this particular prop's derived capability
                   vector meet the effect's geometry requirements
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..common.seed import uniform
from .windows import Window


@dataclass
class Component:
    model_fit: float
    capability_fit: float
    music_fit: float
    style_fit: float
    section_fit: float
    user_preference: float
    random_variation: float
    static: float


def gate(effect_id: str, eff: dict, target: dict, tprefs: dict) -> str | None:
    """Return a reason string if the effect is excluded for this target."""
    allowed = tprefs.get("allowed_effects")
    if allowed is not None and effect_id not in allowed:
        return "not in allowed_effects"
    if effect_id in tprefs.get("disabled_effects", []):
        return "disabled by preference"
    caps = target.get("capabilities", {})
    for cap, mn in eff.get("hard_min", {}).items():
        if caps.get(cap, 0.0) < mn:
            return f"capability {cap}={caps.get(cap, 0.0):.2f} < hard minimum {mn}"
    if tprefs.get("effect_preferences", {}).get(effect_id, 1.0) <= 0:
        return "preference weight 0"
    return None


def model_fit(eff: dict, target: dict, tprefs: dict | None = None) -> float:
    return render_fit(eff, target, tprefs)[0]


RENDER_STYLES = ("default", "per_model")


def render_fit(eff: dict, target: dict, tprefs: dict | None = None) -> tuple[float, str | None]:
    """(prop-type fit, render style) - 0.24.36: an effect on a group drawn as one picture
    ('default': the group's own layout in xLights, here one canvas) or on each of its props
    ('per_model': xLights' Per Model Default render style). Each has its own affinity: the
    group's shape, or the props' shapes (their mean), times the effect's 'render' weights
    (effects.json, default 1.0 each). A group xLights already draws per model has only that
    one. The target's 'render' preference (or a pin's render=) chooses; 'auto' takes the better."""
    table = eff.get("model_fit", {})
    fit = lambda c: table.get(c, table.get("default", 0.5))           # noqa: E731
    rc = target.get("render_classes")
    if target.get("kind") != "group" or not rc or target.get("render_hint", "per_prop") != "as_one":
        return fit(target.get("geometry_class", "")), None
    w = eff.get("render", {})
    mem = rc.get("per_model") or {}
    n = sum(mem.values()) or 1
    per = sum(fit(c) * k for c, k in mem.items()) / n * float(w.get("per_model", 1.0))
    whole = fit(rc.get("group") or target.get("geometry_class", "")) * float(w.get("group", 1.0))
    want = str((tprefs or {}).get("render", "auto")).replace("-", "_")
    if want in RENDER_STYLES:
        return (per, "per_model") if want == "per_model" else (whole, "default")
    return (per, "per_model") if per > whole + 1e-9 else (whole, "default")


def capability_fit(eff: dict, target: dict, unknown: float) -> float:
    req = eff.get("geometry_requirements", {})
    if not req:
        return 1.0
    caps = target.get("capabilities", {})
    logs = [math.log(max(1e-3, min(1.0, caps.get(c, unknown) / lvl))) for c, lvl in req.items()]
    return math.exp(sum(logs) / len(logs))  # geometric mean: one weak capability hurts


def music_fit(eff: dict, w: Window, fweights: dict) -> float:
    ideal = eff.get("music_fit", {})
    num = den = 0.0
    for feat, target_level in ideal.items():
        if feat in w.features:
            wt = fweights.get(feat, 1.0)
            num += wt * (1.0 - abs(target_level - w.features[feat]))
            den += wt
    return num / den if den else 0.5


def style_fit(eff: dict, styles: dict) -> float:
    aff = eff.get("style_affinity", {})
    tot = sum(styles.values())
    if not tot:
        return 0.5
    return sum(p * aff.get(s, 0.5) for s, p in styles.items()) / tot


def section_fit(eff: dict, w: Window) -> float:
    aff = eff.get("section_affinity", {}).get(w.section_type or "", 0.5)
    c = w.section_confidence
    return c * aff + (1 - c) * 0.5   # low-confidence labels pull toward neutral


def score(effect_id: str, eff: dict, target: dict, tprefs: dict, w: Window,
          styles: dict, cfg: dict, seed: int) -> Component:
    wts = cfg["weights"]
    comp = {
        "model_fit": model_fit(eff, target, tprefs),
        "capability_fit": capability_fit(eff, target, cfg["unknown_capability_value"]),
        "music_fit": music_fit(eff, w, cfg["music_feature_weights"]),
        "style_fit": style_fit(eff, styles),
        "section_fit": section_fit(eff, w),
    }
    base = sum(wts[k] * v for k, v in comp.items()) / sum(wts[k] for k in comp)
    pref = float(tprefs.get("effect_preferences", {}).get(effect_id, 1.0))
    pref *= float(tprefs.get("section_effect_scale", {}).get(str(w.section_index), {}).get(effect_id, 1.0))
    amp = cfg["random_amplitude"]
    rnd = uniform(seed, "score", target["id"], w.section_repeat_key, effect_id, lo=-amp, hi=amp)
    return Component(**comp, user_preference=pref, random_variation=rnd,
                     static=base * pref + rnd)
