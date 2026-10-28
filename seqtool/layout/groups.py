# seqtool-command: groups | main | setup | list group kinds and roles; change roles
"""seqtool groups [NAME | LAYOUT] [--list] [--preferences DIR]

Lists every group, numbered, with its kind, member count, role and why it has that
role (set by you, or guessed from the layout: the whole-yard group is top, a group
with the same sequenced props as a larger one is unused, a group of submodels plays
in place of its props). A short guide to the roles comes first. On a terminal it then
asks whether to change any: type a group's number or name (several: 3,7 or 3-6) and
its role, in any order; Enter alone finishes. --list only prints the table.

    groups                 the table (and the question)
    groups 1.ALL           what is in a group: its groups, its props (and parts), where it is used
    groups arch            every group whose name contains 'arch' (and props that do)
    groups Flood01U        a prop: the groups it is in, the closest first, then the groups those are in
    groups arch --all      every name, also past models.json max_list (8)

Roles:
  top     the whole-yard group: takes over whole sections (intro / outro by default); only the
          widest top group plays (scoring.passes.top.max_groups, default 1) - a warning says when
          groups you made top won't
  unit    sequenced as one target in the main pass, in place of its props
  detail  parts of props: accents on top of the props' own effects (detail pass)
  unused  not sequenced (was 'off')

Answers are saved as per-group overrides in the user preference folder
(default ~/seqtool-prefs/models.json); the built-in defaults are never changed.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from ..common import config
from ..common.canonical import read_json
from ..common.log import good, info
from ..common.paths import show
from ..common.prompt import ask, interactive
from ..matchup.engine import group_role, group_role_why
from ..common.paths import arg as paths_arg

ROLES = {"t": "top", "u": "unit", "d": "detail", "n": "unused", "o": "unused"}


def _groups(doc: dict) -> list[dict]:
    if doc.get("schema") == "seqtool.layout":
        return [{"id": g["id"], "members": g["members"], "group_kind": g.get("structure", {}).get("kind", "leaf"),
                 "structure": g.get("structure", {})} for g in doc["groups"]]
    return [m for m in doc["models"] if m["kind"] == "group"]


def natural(name: str) -> list:
    """'2.House' before '10.Yard': numbers compare as numbers."""
    import re
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def top_report(groups: list[dict], mprefs: dict, max_groups: int = 1) -> list[str]:
    """Which top group the top pass uses, and a warning for groups made top (by you or a
    name rule) that it won't use - nested in it, overlapping it, or past max_groups (0.20.8)."""
    tops = [g for g in groups if group_role(g, mprefs) == "top" and g.get("supported_for_generation", True)]
    if not tops:
        return ["{note}no top group: nothing takes over whole sections (the top pass has nothing to do){/}"]
    lvl = lambda g: (g.get("role_guess") or {}).get("level")                       # noqa: E731
    tops.sort(key=lambda g: (-(g.get("role_guess") or {}).get("coverage", 0), lvl(g) if lvl(g) is not None else 999,
                             -len(g.get("members", [])), g["id"]))           # as the top pass sorts them
    chosen, covered = [], set()
    for g in tops:
        mem = set(g.get("members", []))
        if not (mem & covered) and len(chosen) < max_groups:
            chosen.append(g)
            covered |= mem
    L = ["{note}top pass: " + ", ".join(g["id"] for g in chosen) + (" (the widest top group; only "
         f"{max_groups} is used - scoring.passes.top.max_groups)" if max_groups == 1 else
         f" (max_groups {max_groups}, not overlapping)") + "{/}"]
    ch = {g["id"] for g in chosen}
    for g in tops:
        if g["id"] in ch:
            continue
        why = group_role_why(g, mprefs)[1]
        if not why.startswith("set by"):
            continue                                  # guessed: an umbrella; quietly a loose-props unit or unused
        mem = set(g.get("members", []))
        big = next((c for c in chosen if mem <= set(c.get("members", []))), None)
        how = (f"it is inside {big['id']}" if big else
               f"it overlaps {chosen[0]['id']}" if mem & covered else f"max_groups is {max_groups}")
        L.append(f"{{warn}}{g['id']} is top ({why}), but the top pass won't use it: {how}{{/}} - only the widest "
                 f"plays; 'pref models/targets/{g['id']}/role = unit' plays it as one in the main pass instead")
    return L


def table(groups, mprefs) -> None:
    if any(mprefs.get("targets", {}).get(g["id"], {}).get("group_kind") for g in groups):
        print("{note}(* = kind set by a name rule: 'rules' lists them){/}")
    print(f"{{head}}{'#':>3} {'group':<26}{'kind':<15}{'members':>8}  {'role':<7} why{{/}}")
    recent: list[str] = []                       # 0.21.8: generic words said in the last rows are left out
    shown: dict[str, int] = {}
    for num, g in enumerate(groups, 1):
        st = g.get("structure", {})
        note = f"  (submodels: {len(st['submodels'])})" if st.get("submodels") else ""
        role, why = group_role_why(g, mprefs)
        m_ = re.match(r"(.*?\S): (.+?)((?:, level \d+)?)$", why)
        if m_ and len(m_.group(2)) > 25:
            head, gen, lvl = m_.groups()
            if gen in recent and num - shown.get(gen, -99) <= 12:    # said lately: once more every dozen rows
                why = head + lvl
            else:
                shown[gen] = num
            recent = (recent + [gen])[-4:]
        rk = mprefs.get("targets", {}).get(g["id"], {}).get("group_kind")
        kind = rk + "*" if rk and rk != g.get("group_kind") else g.get("group_kind", "?")
        print(f"{num:>3} {g['id'][:25]:<26}{kind:<15}{len(g.get('members', [])):>8}  "
              f"{role:<7} {{note}}{why.replace(' (a name rule makes it ' + str(rk) + ')', '')}{{/}}{note}")


GUIDE = """{head}Choosing a role{/} (what seqtool does with the group):
  {b}top{/}     the group that covers (almost) the whole yard: it takes over whole sections - the intro and
          outro by default (scoring.passes.top) - so everything moves as one there. {b}Only the widest
          top group is used{/} (scoring.passes.top.max_groups = 1); other umbrella groups guessed top play
          as one for props no unit covers (models.json loose_props_to_umbrella), or not at all.
  {b}unit{/}    props that should always look alike - arches, mini trees, floods, a row of columns: the group
          gets one effect at a time and its props get none of their own. A group of submodels (parts
          of props) is a unit too: it plays in place of those props.
  {b}detail{/}  parts of props (spokes, rings, faces) that should add accents ON TOP of the props' own effects.
  {b}unused{/}  duplicates, one-prop groups, or groups kept only for xLights' own use.
  {note}Unsure? Leave the guess. Groups that overlap: the larger unit wins; 'explain GROUP' says why.{/}"""


def review(groups, pref_dir: Path | None, kinds: set[str] | None, mprefs: dict | None = None) -> int:
    """Change roles in any order (0.20.5): pick groups by their number or name."""
    mprefs = mprefs or config.load("models", pref_dir)
    if ask("Change any roles? [y/N]", "n", show_default=False).lower() not in ("y", "yes"):
        return 0
    by_n = {str(i): g for i, g in enumerate(groups, 1)}
    by_name = {g["id"].lower(): g for g in groups}
    changes = {}
    print("{note}type a group's number or name (several: 3,7,12 or 3-6), then its role "
          "(t / u / d / n = top / unit / detail / unused); Enter alone finishes{/}")
    while True:
        pick = ask("group(s)?", "", show_default=False).strip()
        if not pick:
            break
        chosen = []
        for part in [x.strip() for x in pick.split(",") if x.strip()]:
            m = re.fullmatch(r"(\d+)-(\d+)", part)
            if m:
                chosen += [by_n[str(i)] for i in range(int(m.group(1)), int(m.group(2)) + 1) if str(i) in by_n]
            elif part in by_n:
                chosen.append(by_n[part])
            elif part.lower() in by_name:
                chosen.append(by_name[part.lower()])
            else:
                hits = [g for k, g in by_name.items() if part.lower() in k]
                if len(hits) == 1:
                    chosen.append(hits[0])
                else:
                    print(f"  no single group matches '{part}'" + (f" ({len(hits)} do)" if hits else "")
                          + " - its number from the table works too")
        if not chosen:
            continue
        cur = group_role(chosen[0], mprefs)
        ans = ask(f"  role for {', '.join(g['id'] for g in chosen[:4])}{' ...' if len(chosen) > 4 else ''}"
                  f" (now {cur}) [t/u/d/n]", cur).lower()
        role = ROLES.get(ans[:1], ans if ans in ROLES.values() else None)
        if role is None:
            print("  t, u, d or n - nothing changed")
            continue
        for g in chosen:
            changes[g["id"]] = {"role": role}
            mprefs = {**mprefs, "targets": {**mprefs.get("targets", {}), g["id"]: {**mprefs.get("targets", {}).get(g["id"], {}), "role": role}}}
        print(f"  {len(chosen)} group(s) -> {role}")
    if changes:
        f = config.update("models", {"targets": changes}, pref_dir)
        good(f"saved {len(changes)} role change(s) to {show(f)} - 'run' uses them")
    return len(changes)


def _wrap_list(label: str, items: list[str], limit: int = 0) -> None:
    """The items, wrapped under the label; past `limit` (models.json max_list, 0 = all;
    --all) the rest are counted (0.20.7, the user's rule for long lists)."""
    import textwrap
    shown = items if not limit or len(items) <= limit else items[:limit] + [f"... and {len(items) - limit} more"]
    for ln in textwrap.wrap(", ".join(shown), 96, initial_indent=f"  {label}: ", subsequent_indent="      ",
                            break_on_hyphens=False):
        print(ln)


def show_group(doc: dict, name: str, mprefs: dict, limit: int | None = None) -> int:
    """groups NAME: what is in it - its groups, its props (and parts) - and its role. NAME may
    also be part of a name (every group that matches) or a prop (the groups it is in, the
    closest first)."""
    from ..models.analyze import containing_groups
    lim = int(mprefs.get("max_list", 8) if limit is None else limit)
    groups = sorted([m for m in doc["models"] if m["kind"] == "group"], key=lambda g: natural(g["id"]))
    by = {m["id"]: m for m in doc["models"]}
    low = name.lower()
    exact = [g for g in groups if g["id"].lower() == low]
    hits = exact or [g for g in groups if low in g["id"].lower()]
    props = [m for m in doc["models"] if m["kind"] == ("submodel" if "/" in name else "model")]
    props = [m for m in props if m["id"].lower() == low] or \
        ([] if exact else [m for m in props if low in m["id"].lower()])
    if not hits and not props:
        from ..common.suggest import suggest
        raise SystemExit(f"no group or prop '{name}'" + suggest(name, [g["id"] for g in groups])
                         + " - 'groups' lists the groups, 'models' the props")
    full = hits if not lim else hits[:lim]
    if len(hits) > 1:
        print(f"{len(hits)} groups match '{name}'" + ("" if len(full) == len(hits) else
              f" - the first {len(full)} in full ('groups FULLNAME' for one, --all for every one)"))
    for g in full:
        role, why = group_role_why(g, mprefs)
        print(f"{{head}}{g['id']}{{/}}  {g.get('group_kind')}, role {role} {{note}}({why}){{/}}")
        if g.get("child_groups"):
            _wrap_list("groups in it", g["child_groups"], lim)
        if g.get("detail_members"):
            _wrap_list(f"parts (submodels, {len(g['detail_members'])})", g["detail_members"], lim)
        mem = list(dict.fromkeys(g.get("members", [])))
        ok = [x for x in mem if by.get(x, {}).get("supported_for_generation")]
        _wrap_list(f"props ({len(mem)}, {len(ok)} sequenced)",
                   [x + ("" if x in ok else " (not sequenced)") for x in mem] or ["none"], lim)
        inn = [h["id"] for h in groups if h is not g and g["id"] in h.get("child_groups", [])]
        if inn:
            _wrap_list("inside", inn, lim)
    if len(full) < len(hits):
        _wrap_list("also matching", [g["id"] for g in hits[len(full):]], lim)
    for m in props[:lim or None]:                          # a prop: its groups, the closest first (0.20.7)
        state = "sequenced" if m.get("supported_for_generation", True) else \
            "not sequenced: " + m.get("unsupported_reason", "")
        print(f"{{head}}{m['id']}{{/}}  {m['kind']}, {state}")
        cg = containing_groups(doc["models"], m["id"])
        if not cg:
            print("  in no group")
        for d in sorted({d for _, d, _ in cg}):
            names = [g["id"] + (" (its parts)" if p else "") for g, dd, p in cg if dd == d]
            _wrap_list("in" if d == 0 else ("inside those" if d == 1 else f"{d} levels up"), names, lim)
    if len(props) > (lim or len(props)):
        _wrap_list("props also matching", [m["id"] for m in props[lim:]], lim)
    return 0


# what decides the roles shown here (printed under the table, the user's rule 0.20.0)
LAYOUT_PREFS = ("xlights.exclude_controllers", "xlights.exclude_layout_groups", "xlights.exclude_name_patterns", "xlights.exclude_models", "xlights.umbrella_name_patterns", "xlights.shadow_models")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool groups", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("layout", nargs="?", default=None,
                    help="a group's name (what is in it), or a layout.json / layout.models.json (default: the "
                         "stored show layout)")
    ap.add_argument("--list", action="store_true", help="only print the table, don't ask")
    ap.add_argument("--all", action="store_true", help="with NAME: list everything (models.json max_list cuts long lists)")
    ap.add_argument("--role", choices=("top", "unit", "detail", "unused", "auto"),
                    help="with NAME: set the group's role (auto: back to the guess) - the GUI's layout panel uses it")
    ap.add_argument("--kinds", default="umbrella,submodel_view",
                    help="which group kinds to ask about (default umbrella,submodel_view; 'all')")
    ap.add_argument("--preferences", type=paths_arg, default=None)
    from ..common.args import dash_words
    a = ap.parse_args(dash_words(ap, argv))
    name = None
    if a.layout is not None and not (a.layout.endswith(".json") or Path(a.layout).expanduser().exists()):
        name, a.layout = a.layout, None                  # 'groups 1.ALL': what is in that group
    elif a.layout is not None:
        a.layout = paths_arg(a.layout)
    if a.layout is None:
        from . import store
        if store.source_info() is None:
            raise SystemExit("groups: no show layout stored yet - run 'layout path/to/show' first, or give a layout.json")
        a.layout = store.folder() / "layout.models.json"
    doc = read_json(a.layout)
    if doc.get("schema") == "seqtool.layout":           # role guesses live in the models file
        mf = Path(a.layout).with_name(Path(a.layout).name.replace("layout.json", "layout.models.json"))
        if mf.exists():
            doc = read_json(mf)
    groups = sorted(_groups(doc), key=lambda g: natural(g["id"]))
    from ..matchup import rules as name_rules
    mp = name_rules.expand(config.load("models", a.preferences), doc) if doc.get("schema") == "seqtool.models" \
        else config.load("models", a.preferences)
    if name is not None and a.role:                   # 0.21.8: one group's role, without the questions
        g = next((x for x in groups if x["id"].lower() == name.lower()), None)
        if g is None:
            from ..common.suggest import suggest
            raise SystemExit(f"no group '{name}'" + suggest(name, [x["id"] for x in groups]) + " - 'groups' lists them")
        if a.role == "auto":
            f = config.unset("models", ["targets", g["id"], "role"], a.preferences)
        else:
            f = config.update("models", {"targets": {g["id"]: {"role": a.role}}}, a.preferences)
        mp = config.load("models", a.preferences)
        role, why = group_role_why(g, mp)
        good(f"{g['id']}: role {role} ({why}) - saved to {show(f)}; 'run' again to update the plan")
        return 0
    if name is not None:
        return show_group(doc, name, mp, 0 if a.all else None)
    print(GUIDE)
    table(groups, mp)
    try:
        mg = int(config.load("scoring", a.preferences).get("passes", {}).get("top", {}).get("max_groups", 1))
    except (TypeError, ValueError):
        mg = 1
    for ln in top_report(groups, mp, mg):
        print(ln)
    from ..common.prefcmd import uses
    for ln in uses(*LAYOUT_PREFS, "models.group_roles", "scoring.passes.top.max_groups"):
        print(ln)
    if a.list:
        return 0
    if not interactive():
        info("(not a terminal: roles listed only)")
        return 0
    print("{note}'groups NAME' shows what is in a group ('groups PROP': the groups a prop is in){/}")
    review(groups, a.preferences, None if a.kinds == "all" else set(a.kinds.split(",")), mp)
    from . import store
    src = store.source_info()
    if src:
        config.remember("groups_reviewed", src["sha256"])   # 'doctor' stops suggesting a review
    return 0


if __name__ == "__main__":
    sys.exit(main())
