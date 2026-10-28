"""Name rules: target settings by naming convention (models.json "rules").

    "rules": [
      {"match": "(?i)flood", "effect_preferences": {"color_wash": 1.5, "chase": 0.5}},
      {"match": "(?i)^arch", "kind": "group", "react": "beat-chase", "react_over": true},
      {"match": "(?i)candy ?cane", "allowed_effects": ["chase", "pulse", "color_wash"]}
    ]

'match' is a regular expression searched in the model or group name ((?i) = any
case; ^ / $ anchor to the start / end). 'kind' (model or group) is optional.
Every rule that matches applies, in order: effect_preferences multiply, other
settings are replaced by later rules. Settings you give a target by name
(targets.<name>, e.g. via 'react' or 'pref') win over rules.
Groups: 'role' (top, unit, detail, unused) sets the role; 'group_kind' (umbrella,
leaf, submodel_view, single) says what kind of group it is, and the role then
follows from the kind (e.g. {"match": "(?i)-all$", "kind": "group", "group_kind": "umbrella"}).
"""
from __future__ import annotations

import copy
import re

KEYS = ("enabled", "role", "group_kind", "allowed_effects", "effect_preferences", "react", "react_over", "enhance",
        "drive_individually")


def matches(rule: dict, model: dict) -> bool:
    kind = rule.get("kind")
    if kind and kind != model.get("kind"):
        return False
    try:
        return re.search(rule.get("match", ""), model["id"]) is not None
    except re.error:
        return False


def problems(mprefs: dict) -> list[str]:
    out = []
    for i, r in enumerate(mprefs.get("rules", []) or []):
        try:
            re.compile(r.get("match", ""))
        except re.error as e:
            out.append(f"rule {i + 1} ({r.get('match')!r}): bad pattern: {e}")
        unknown = [k for k in r if k not in KEYS + ("match", "kind", "note")]
        if unknown:
            out.append(f"rule {i + 1} ({r.get('match')!r}): unknown setting(s) {', '.join(unknown)}")
    return out


def expand(mprefs: dict, models: dict) -> dict:
    """models prefs with each rule applied to the matching layout names. Adds
    targets[name]["_rules"] = [patterns] so explain can say where a setting came from."""
    rules = mprefs.get("rules") or []
    if not rules:
        return mprefs
    out = copy.deepcopy(mprefs)
    explicit = mprefs.get("targets", {})
    targets = out.setdefault("targets", {})
    for m in models.get("models", []):
        got: dict = {}
        hits = []
        for r in rules:
            if not matches(r, m):
                continue
            hits.append(r.get("match", ""))
            for k in KEYS:
                if k not in r:
                    continue
                if k == "effect_preferences":
                    ep = got.setdefault("effect_preferences", {})
                    for e, mult in r[k].items():
                        ep[e] = round(ep.get(e, 1.0) * float(mult), 6)
                else:
                    got[k] = copy.deepcopy(r[k])
        if not hits:
            continue
        mine = explicit.get(m["id"], {})
        merged = dict(got)
        for k, v in mine.items():
            if k == "effect_preferences":
                merged["effect_preferences"] = {**got.get("effect_preferences", {}), **v}
            else:
                merged[k] = v
        merged["_rules"] = hits
        merged["_from_rules"] = [k for k in got if k not in mine]
        targets[m["id"]] = merged
    return out
