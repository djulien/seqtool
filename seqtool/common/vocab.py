"""Effect vocabulary helpers shared by the matchup, validator, exporter and viewers.

'transparent' = no effect from this pass: lower layers and the base pass show through.
'dark'        = the prop explicitly black (masks lower layers and earlier rows).
Up to 0.15 'transparent' was called 'off'; old names in preference files, rules and
presets are read as the new ones (fold_*), so nothing the user saved breaks.
"""
from __future__ import annotations

ALIASES = {"off": "transparent"}
NOT_LIT = frozenset({"transparent", "dark", "off", "choreo"})   # no light from this effect (choreo: its parts give it)


ROLE_ALIASES = {"off": "unused"}


def canon_role(role):
    """Group roles: 'off' (before 0.16.1) is 'unused' - not sequenced."""
    return ROLE_ALIASES.get(role, role) if isinstance(role, str) else role


def canon(name):
    return ALIASES.get(name, name) if isinstance(name, str) else name


def lit(effect: str) -> bool:
    return effect not in NOT_LIT


def _fold_target(t: dict) -> dict:
    if not isinstance(t, dict):
        return t
    t = dict(t)
    if "role" in t:
        t["role"] = canon_role(t["role"])
    if isinstance(t.get("allowed_effects"), list):
        t["allowed_effects"] = list(dict.fromkeys(canon(e) for e in t["allowed_effects"]))
    if isinstance(t.get("effect_preferences"), dict):
        ep = {}
        for k, v in t["effect_preferences"].items():
            ep[canon(k)] = v
        t["effect_preferences"] = ep
    return t


def fold(name: str, doc: dict) -> dict:
    """Read old effect names in a merged preference file as the current ones."""
    if name == "effects" and isinstance(doc.get("effects"), dict) and "off" in doc["effects"]:
        effs = dict(doc["effects"])
        old = effs.pop("off")
        effs["transparent"] = {**effs.get("transparent", {}), **old} if isinstance(old, dict) else effs.get("transparent")
        return {**doc, "effects": effs}
    if name == "models":
        doc = dict(doc)
        if isinstance(doc.get("group_roles"), dict):
            doc["group_roles"] = {k: canon_role(v) for k, v in doc["group_roles"].items()}
        if "defaults" in doc:
            doc["defaults"] = _fold_target(doc["defaults"])
        if isinstance(doc.get("targets"), dict):
            doc["targets"] = {k: _fold_target(v) for k, v in doc["targets"].items()}
        if isinstance(doc.get("rules"), list):
            doc["rules"] = [_fold_target(r) for r in doc["rules"]]
        return doc
    if name == "presets" and isinstance(doc.get("presets"), dict):
        ps = {}
        for k, p in doc["presets"].items():
            ps[k] = {**p, "effect": canon(p["effect"])} if isinstance(p, dict) and "effect" in p else p
        return {**doc, "presets": ps}
    return doc
