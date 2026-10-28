# seqtool-command: models | main | setup | list the props of the stored layout: models [PATTERN] [--unused] [--disable | --enable]
"""seqtool models [PATTERN] [--unused] [--submodels] [--disable | --enable]

Every prop (model) of the stored show layout, one per line: its shape class as
seqtool sees it, its number of lights, its controller, the groups it is in, and
whether it is sequenced - if not, why (an excluded layout group, a name pattern,
a shadow model's helper ...). 'groups' does the same for the groups.

    models                 all props
    models arch            props whose name contains 'arch' (a regular expression, any case)
    models --unused        only those that aren't sequenced, with the reason
    models --submodels     their submodels too
    models Tree --disable  Tree is not sequenced any more (models.json targets.Tree.enabled = false);
                           --enable undoes it. Every prop matching the pattern - check the list first.
                           (To leave it out of the layout itself: pref xlights.exclude_models)

Groups are listed closest first: the groups that list the prop themselves, then the
groups those are in ('groups PROP' shows the levels).
"""
from __future__ import annotations

import argparse
import re
import sys

from ..common.canonical import read_json
from .groups import LAYOUT_PREFS, natural

CLASS_WORDS = {"LINEAR": "line", "ARC": "arch", "RADIAL": "spinner", "RING": "ring", "SURFACE_2D": "matrix",
               "CONE": "tree", "FIGURE": "figure", "FLOOD": "flood", "POINT": "point", "VOLUME": "3-D",
               "IRREGULAR": "irregular", "STAR": "star"}


def rows(models: dict, layout: dict, pattern: str | None = None, unused: bool = False, subs: bool = False,
         mprefs: dict | None = None):
    from ..models.analyze import containing_groups
    lay = {p["id"]: p for p in layout.get("props", [])}
    tg = (mprefs or {}).get("targets", {})
    rx = re.compile(pattern, re.I) if pattern else None
    out = []
    for m in sorted(models["models"], key=lambda m: natural(m["id"])):
        if m["kind"] == "group" or (m["kind"] == "submodel" and not subs):
            continue
        if rx and not rx.search(m["id"]):
            continue
        ok = m.get("supported_for_generation", True)
        why = m.get("unsupported_reason", "")
        if ok and tg.get(m["id"], {}).get("enabled") is False:
            ok, why = False, "disabled by you ('models NAME --enable' undoes it)"
        if unused and ok:
            continue
        o = (lay.get(m["id"]) or {}).get("origin", {})
        gs = [g["id"] for g, _, _ in containing_groups(models["models"], m["id"])] if m["kind"] == "model" else []
        cls = m.get("geometry_class", "?")
        out.append({"id": m["id"], "class": CLASS_WORDS.get(cls, cls.lower()), "lights": m.get("node_count", 0),
                    "controller": o.get("Controller", "") if m["kind"] == "model" else "",
                    "channels": o.get("absolute", ""), "ctrl_channels": o.get("channels", ""),
                    "groups": gs, "ok": ok, "why": why})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool models", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pattern", nargs="?", help="only props whose name matches (regular expression, any case)")
    ap.add_argument("--unused", action="store_true", help="only the props that aren't sequenced, and why")
    ap.add_argument("--submodels", action="store_true", help="list submodels too")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--disable", action="store_true", help="don't sequence the props matching PATTERN")
    g.add_argument("--enable", action="store_true", help="sequence them again")
    ap.add_argument("--exact", action="store_true", help="PATTERN is a name, not a pattern (the GUI uses it)")
    from ..common.args import dash_words
    a = ap.parse_args(dash_words(ap, argv))
    if a.exact and a.pattern:
        a.pattern = "^" + re.escape(a.pattern) + "$"
    from . import store
    if store.source_info() is None:
        raise SystemExit("no show layout stored yet - 'layout SHOWFOLDER' first (e.g. 'layout ~/xLights/show')")
    lay = read_json(store.folder() / "layout.json")
    models = read_json(store.folder() / "layout.models.json")
    try:
        rx = re.compile(a.pattern, re.I) if a.pattern else None  # noqa: F841 - checked here, used in rows()
    except re.error as e:
        raise SystemExit(f"'{a.pattern}' isn't a valid pattern ({e}) - e.g. 'models arch' or 'models \"^col\"'")
    from ..common import config
    mp = config.load("models")
    if a.disable or a.enable:
        if not a.pattern:
            raise SystemExit("models PATTERN --disable: which props? e.g. 'models \"^Tree$\" --disable'")
        hit = [r["id"] for r in rows(models, lay, a.pattern, False, a.submodels, mp)]
        if not hit:
            raise SystemExit(f"no props match '{a.pattern}' - 'models' lists them")
        f = config.update("models", {"targets": {h: {"enabled": not a.disable} for h in hit}})
        from ..common.log import good
        label = (f"{'disabled' if a.disable else 'enabled'} {len(hit)} prop(s): {', '.join(hit[:10])}"
                 + (" ..." if len(hit) > 10 else "") + f" (saved to {f})")
        mp = config.load("models")
        _replan(label, hit, a.disable, models)
    R = rows(models, lay, a.pattern, a.unused, a.submodels, mp)
    if not R:
        print("no props match" + (f" '{a.pattern}'" if a.pattern else "") + " - 'models' lists them all")
        return 0
    w = min(28, max(len(r["id"]) for r in R) + 2)
    absolute = any(r["channels"] for r in R)
    chw = max([len(r["channels"] or r["ctrl_channels"]) for r in R] + [8]) + 2
    print(f"{{head}}{'prop':<{w}}{'shape':<10}{'nodes':>7}  {'controller':<16} {'channels':<{chw}}{'sequenced':<10} "
          "groups (closest first) / why not{/}")
    for r in R:
        grp = ", ".join(r["groups"][:3]) + (f" (+{len(r['groups']) - 3})" if len(r["groups"]) > 3 else "")
        tail = grp if r["ok"] else "{warn}" + r["why"] + "{/}" + (f"   ({grp})" if grp else "")
        seq = "yes       " if r["ok"] else "{warn}no{/}        "
        ch = r["channels"] or r["ctrl_channels"]
        print(f"{r['id']:<{w}}{r['class']:<10}{r['lights']:>7}  {r['controller'][:16]:<16} {ch:<{chw}}{seq} {tail}")
    n_ok = sum(1 for r in R if r["ok"])
    print(f"{len(R)} prop(s), {n_ok} sequenced" + ("" if n_ok == len(R) else
                                                     f", {len(R) - n_ok} not ('models --unused' lists those)"))
    if absolute:
        one = next((r for r in R if r["channels"]), None)
        a_, b_ = one["channels"].split("-")
        print(f"{{note}}channels: absolute (from xlights_networks.xml) - what an .fseq holds; e.g. "
              f"'python fseqdump.py SONG.fseq --start {a_} --count {int(b_) - int(a_) + 1} --from 1:00 --to 1:01' "
              f"shows {one['id']}{{/}}")
    else:
        print("{note}channels: per controller (CONTROLLER:first-last); with xlights_networks.xml beside "
              "xlights_rgbeffects.xml 'layout SHOWFOLDER' gives absolute ones, for fseqdump{/}")
    from ..common.prefcmd import uses
    for ln in uses(*LAYOUT_PREFS):
        print(ln)
    return 0


def _replan(label: str, hit: list[str], disabled: bool, models: dict) -> None:
    """0.24.14: the plan follows at once (as after pin or react), when there is one; a disabled
    prop that a sequenced group holds is still lit by that group's effects in xLights - said."""
    from ..common import config
    from ..common.log import good, info, warn
    if not config.answer("last_run") or not config.answer("last_matchup"):
        good(label + " - 'run' makes a plan with it")
        return
    try:
        from ..matchup.reroll import _context
        _, old_m, profile, _ = _context()
    except SystemExit:
        good(label + " - 'run' again to update the plan")
        return
    from ..matchup.pins import _apply_and_show
    _apply_and_show(label, old_m, profile)
    if not disabled:
        return
    from pathlib import Path
    new_m = read_json(Path(config.answer("last_matchup")))
    driven = {p["target"] for p in new_m.get("plans", []) if p.get("segments")}
    groups = {g["id"]: g for g in models["models"] if g["kind"] == "group"}

    def holders(pid: str) -> list[str]:
        out, todo, seen = [], [pid], set()
        while todo:
            x = todo.pop()
            for gid, g in groups.items():
                if x in g.get("members", []) and gid not in seen:
                    seen.add(gid)
                    todo.append(gid)
                    if gid in driven:
                        out.append(gid)
        return sorted(out)
    for h in hit[:10]:
        gs = holders(h)
        if gs:
            warn(f"{h} has no effects of its own now, but it is in {', '.join(gs[:3])}" + (" ..." if len(gs) > 3 else "")
                 + f", whose effects still light it in xLights. To keep it dark all song instead: "
                 f"'models {h} --exact --enable' then 'pin {h} dark'")


if __name__ == "__main__":
    sys.exit(main())
