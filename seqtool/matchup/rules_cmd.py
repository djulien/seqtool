# seqtool-command: rules | main | refine | settings by name pattern: rules add '(?i)flood' prefer=color_wash*1.5 | react=beat
r"""seqtool rules [list | test PATTERN | add PATTERN SETTING... | remove N]

Name rules give every model or group whose name matches a pattern the same
settings, so new props that follow your naming convention get them too.

    rules                                         list the rules and what each matches
    rules test '(?i)arch'                         which names a pattern matches
    rules add '(?i)flood' prefer=color_wash*1.5   floods lean towards colour washes
    rules add '(?i)flood' prefer=chase*0          ... and never chase (0 = excluded)
    rules add '(?i)^arch' kind=group react=beat-chase over=yes
    rules add '(?i)candy' only=chase,pulse,color_wash
    rules add '(?i)^test' enabled=no
    rules add '(?i)-all$' kind=group group_kind=leaf   groups named ...-all as one unit (umbrella by default)
    rules add '^1\.' kind=group role=top                 level-1 groups ('1.ALL') are the top group
    rules remove 2

Settings:
    prefer=EFFECT*N[,EFFECT*N]   multiply that effect's score (1 = no change, 0 = never)
    only=EFFECT[,EFFECT]         the only effects allowed
    react=PRESET[,PRESET]        follow the music ('presets'); over=yes puts it above the normal layer
    role=top|unit|detail|unused  for groups: what the group is used for ('groups' shows them)
    group_kind=umbrella|leaf|submodel_view|single
                                 for groups: what kind of group it is; the role follows from it
    enabled=yes|no               plan this target at all (for submodels: plan it in the detail pass)
    enhance=yes|no               a second layer of accents on this prop (the enhance pass)
    kind=model|group             only match models, or only groups

PATTERN is a regular expression searched anywhere in the name: (?i) ignores case,
^ and $ anchor to the start and end, | means or (e.g. '(?i)flood|spot'), . is any one
character and .* any run of characters (e.g. '(?i)mega.*tree').
Every matching rule applies, in order; settings for a target by name (react,
pref) win over rules. A preference only biases the score, so the rest of the
matching (fit, music, continuity) still works; 0 removes the effect.
"""
from __future__ import annotations

import argparse
import re
import sys

from ..common import config
from ..common.log import good, info, warn


def _names() -> list[dict]:
    try:
        from ..layout import store
        cur = store.current()
        if cur:
            return cur[1]["models"]
    except Exception:  # noqa: BLE001
        pass
    try:                                    # no stored layout: the current song's (e.g. the demo's)
        from ..common import current
        from ..common.canonical import read_json
        song = current.song() or {}
        mf = song.get("matchup")
        if mf:
            m = read_json(mf)
            from pathlib import Path
            f = Path(mf).with_name(m["source"]["models"]["filename"])
            return read_json(f)["models"]
    except Exception:  # noqa: BLE001
        pass
    return []


def _save(rules: list[dict]) -> None:
    f = config.user_dir() / "models.json"
    from ..common.canonical import read_json
    cur = read_json(f) if f.exists() else {}
    cur["rules"] = rules
    config.save("models", cur)


def _summary(r: dict) -> str:
    parts = []
    if r.get("kind"):
        parts.append(f"{r['kind']}s only")
    if r.get("effect_preferences"):
        parts.append("prefer " + ", ".join(f"{e}*{v:g}" for e, v in r["effect_preferences"].items()))
    if r.get("allowed_effects"):
        parts.append("only " + ",".join(r["allowed_effects"]))
    if r.get("react"):
        parts.append(f"react {r['react']}" + (" (over)" if r.get("react_over") else ""))
    for k in ("role", "group_kind", "enabled", "drive_individually", "enhance"):
        if k in r:
            parts.append(f"{k} {r[k]}")
    return "; ".join(parts) or "(no settings)"


def _matching(r: dict, models: list[dict]) -> list[str]:
    from .rules import matches
    return [m["id"] for m in models if matches(r, m)]


def _parse(settings: list[str]) -> dict:
    out: dict = {}
    yes = {"yes": True, "y": True, "true": True, "1": True, "on": True,
           "no": False, "n": False, "false": False, "0": False, "off": False}
    effects = config.load("effects")["effects"]
    for s in settings:
        if "=" not in s:
            raise SystemExit(f"'{s}': use SETTING=VALUE (see 'rules -h')")
        k, v = (x.strip() for x in s.split("=", 1))
        if k == "prefer":
            ep = out.setdefault("effect_preferences", {})
            for item in v.split(","):
                e, _, mult = item.partition("*")
                e = e.strip()
                if e not in effects:
                    raise SystemExit(f"unknown effect '{e}' ('effects' lists them)")
                ep[e] = float(mult or 1.0)
        elif k == "only":
            names = [x.strip() for x in v.split(",") if x.strip()]
            bad = [x for x in names if x not in effects]
            if bad:
                raise SystemExit(f"unknown effect(s) {', '.join(bad)} ('effects' lists them)")
            out["allowed_effects"] = names
        elif k == "react":
            from . import reactive
            bad = reactive.check(v, reactive.load_presets(), effects)
            if bad:
                raise SystemExit("; ".join(bad))
            out["react"] = ",".join(reactive.names_of(v))
        elif k == "over":
            out["react_over"] = yes.get(v.lower(), True)
        elif k in ("enabled", "drive_individually", "enhance"):
            out[k] = yes.get(v.lower(), True)
        elif k == "role":
            from ..common.vocab import canon_role
            v = canon_role(v)
            if v not in ("top", "unit", "detail", "unused"):
                raise SystemExit("role must be top, unit, detail or unused, e.g. 'rules add \'^1\\.\' kind=group role=top'")
            out["role"] = v
        elif k == "group_kind":
            kinds = ("umbrella", "leaf", "submodel_view", "single")
            if v not in kinds:
                raise SystemExit(f"group_kind must be {', '.join(kinds)}, e.g. 'rules add \'(?i)-all$\' kind=group group_kind=umbrella'")
            out["group_kind"] = v
            out.setdefault("kind", "group")
        elif k == "kind":
            if v not in ("model", "group"):
                raise SystemExit("kind must be model or group, e.g. 'rules add \'(?i)^arch\' kind=group react=beat'")
            out["kind"] = v
        else:
            raise SystemExit(f"unknown setting '{k}' (see 'rules -h')")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool rules", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", nargs="?", default="list", choices=("list", "test", "add", "remove"))
    ap.add_argument("args", nargs="*")
    from ..common.args import dash_words
    a = ap.parse_args(dash_words(ap, argv))          # a pattern may start with '-' ('-all$', 0.20.8)
    rules = list(config.load("models").get("rules", []) or [])
    models = _names()
    if a.action == "list":
        if not rules:
            print("no name rules yet - e.g.  rules add '(?i)flood' prefer=color_wash*1.5")
            return 0
        from .rules import problems
        for i, r in enumerate(rules, 1):
            hit = _matching(r, models)
            print(f"  {i}. /{r.get('match', '')}/  {_summary(r)}")
            if models:
                print(f"       matches {len(hit)}: " + (", ".join(hit[:8]) + (" ..." if len(hit) > 8 else "") if hit else "nothing"))
        for p in problems({"rules": rules}):
            warn(f"  {p}")
        return 0
    if a.action == "test":
        if not a.args:
            raise SystemExit("rules test PATTERN  (e.g. 'rules test (?i)arch')")
        try:
            re.compile(a.args[0])
        except re.error as e:
            raise SystemExit(f"bad pattern: {e} - patterns are regular expressions, e.g. '(?i)flood|spot'")
        if not models:
            raise SystemExit("no layout found - run 'layout' (or a run) first")
        hit = _matching({"match": a.args[0]}, models)
        print(f"/{a.args[0]}/ matches {len(hit)} of {len(models)} names" + (":" if hit else ""))
        for h in hit:
            print(f"  {h}")
        return 0
    if a.action == "add":
        if len(a.args) < 2:
            raise SystemExit("rules add PATTERN SETTING=VALUE ...  (see 'rules -h')")
        pat = a.args[0]
        try:
            re.compile(pat)
        except re.error as e:
            raise SystemExit(f"bad pattern: {e} - patterns are regular expressions, e.g. '(?i)flood|spot'")
        r = {"match": pat, **_parse(a.args[1:])}
        rules.append(r)
        _save(rules)
        hit = _matching(r, models)
        good(f"rule {len(rules)}: /{pat}/  {_summary(r)}")
        if models:
            (info if hit else warn)(f"  matches {len(hit)}: " + (", ".join(hit[:8]) + (" ..." if len(hit) > 8 else "")
                                                                 if hit else "nothing in the stored layout"))
        if str(r.get("role", "")).lower() == "top" and len(hit) > 1:
            warn(f"  {len(hit)} groups made top, but only the widest top group plays in the top pass "
                 "(scoring.passes.top.max_groups) - 'groups' shows which one and warns about the others")
        info("run again to update the plan ('run' reuses the analysis)")
        return 0
    if not a.args or not a.args[0].isdigit() or not 1 <= int(a.args[0]) <= len(rules):
        raise SystemExit(f"rules remove N  (1-{len(rules)})" if rules else "no rules to remove")
    r = rules.pop(int(a.args[0]) - 1)
    _save(rules)
    good(f"removed /{r.get('match')}/  {_summary(r)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
