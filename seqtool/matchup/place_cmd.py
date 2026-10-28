# seqtool-command: promote | main_promote | refine | move props' effect up to a group that holds them: promote Flood01U Flood02U @#3 [--up N | --to GROUP]
# seqtool-command: demote | main_demote | refine | hand a group's effect down to its groups or props: demote 4.Floods-all @#3 [--down N | --to props]
"""seqtool promote TARGET... @#N|@TIME|--all [--up N | --to GROUP] [--effect E] [--only]
       seqtool demote GROUP @#N|@TIME|--all [--down N | --to props|GROUP...] [--effect E] [--only]

Deciding in advance which groups get effects (roles, rules) is hard to picture, so
these work on the plan you see (0.21, the user's design):

    promote Flood01U Flood02U @#3      the effect those props show in section 3 moves to the
                                       closest group holding both: the group plays it there,
                                       everything inside the group rests
    promote Flood01U @#3 --up 2        two groups up (the next larger group that holds it)
    promote Flood01U @#3 --to 2.HOUSE  straight to that group
    promote Flood01U --all --to 4.Floods-all   the whole row: every section's effect, each in its own
                                       section (the GUI: Ctrl+click the row's name)
    demote 4.Floods-all @#3            the group's effect goes to what is in it one level down
                                       (its groups, and props listed in it directly); the group
                                       itself rests there
    demote 2.HOUSE @#3 --down 2        two levels down
    demote 2.HOUSE @#3 --to props      to every prop in it

Both are pins (pass 'place'): they survive rerolls and re-runs, 'pin' lists them and
'unpin TARGET @#N' undoes one. Like pins they cover the section's repeats unless
--only. When the props show different effects, the most common is promoted (say which
with --effect). The groups a prop is in, closest first: 'groups PROP'.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from ..common import config, songs
from ..common.canonical import read_json
from ..common.log import info, warn
from ..common.vocab import canon


def _models_doc(path: Path, m: dict) -> dict:
    try:
        return read_json(path.with_name(m["source"]["models"]["filename"]))
    except (KeyError, OSError, ValueError):
        raise SystemExit("the models file of the last run is missing - 'run' again") from None


def props_under(by: dict, tid: str) -> set[str]:
    m = by.get(tid)
    if m is None:
        return {tid.split("/", 1)[0]}
    if m["kind"] == "group":
        return {x.split("/", 1)[0] for x in (m.get("members") or [])}
    return {m.get("parent", tid.split("/", 1)[0])} if m["kind"] == "submodel" else {tid}


def groups_over(models: dict, ids: list[str], why_not: list | None = None) -> list[dict]:
    """Groups holding everything in ids, the closest first (fewest props, then nearest in the
    layout's nesting). Every such group is offered (0.21.2: 6.Wise-all was still missing - a
    group holding nothing but the selected prop, or the twin of a closer group, was left out);
    only a selected group's twins are not its parents. why_not collects the groups that hold
    them but can't be used, with the reason."""
    by = {x["id"]: x for x in models["models"]}
    want = set().union(*(props_under(by, i) for i in ids))
    one_group = len(ids) == 1 and by.get(ids[0], {}).get("kind") == "group"
    cands = []
    for g in models["models"]:
        if g["kind"] != "group" or g["id"] in ids:
            continue
        have = props_under(by, g["id"])
        if not want <= have:
            continue
        if one_group and have == want and ids[0] not in g.get("child_groups", []):
            continue                                       # the selected group under another name
        if not g.get("supported_for_generation", True):
            if why_not is not None:
                why_not.append({"id": g["id"], "why": g.get("unsupported_reason") or "not usable"})
            continue
        cands.append(g)
    from ..models.analyze import containing_groups
    dist = {g["id"]: d for g, d, _ in containing_groups(models["models"], ids[0])}
    cands.sort(key=lambda g: (len(props_under(by, g["id"])), dist.get(g["id"], 99), g["id"]))
    return cands


def report(models: dict, ids: list[str]) -> list[tuple[str, bool, str]]:
    """Every group the first selected target is in (closest first, as 'groups' shows them),
    whether promote offers it, and why not (0.21.3: to see why a group is missing)."""
    from ..models.analyze import containing_groups
    by = {x["id"]: x for x in models["models"]}
    why_not: list = []
    offered = {g["id"] for g in groups_over(models, ids, why_not)}
    nots = {w["id"]: w["why"] for w in why_not}
    want = set().union(*(props_under(by, i) for i in ids))
    out = []
    for g, d, parts in containing_groups(models["models"], ids[0]):
        if g["id"] in offered:
            out.append((g["id"], True, ""))
        elif g["id"] in nots:
            out.append((g["id"], False, nots[g["id"]]))
        elif not want <= props_under(by, g["id"]):
            miss = sorted(want - props_under(by, g["id"]))
            out.append((g["id"], False, f"doesn't hold {', '.join(miss[:3])}"))
        else:
            out.append((g["id"], False, "the selected group under another name"))
    return out


def children(models: dict, gid: str, down: int = 1) -> list[str]:
    """What is in a group, `down` levels: its groups and the props listed in it directly."""
    by = {x["id"]: x for x in models["models"]}
    cur = [gid]
    for _ in range(max(1, down)):
        nxt = []
        for t in cur:
            g = by.get(t)
            if g is None or g["kind"] != "group":
                nxt.append(t)
                continue
            kids = [c for c in g.get("child_groups", []) if c in by]
            inner = set().union(*(props_under(by, c) for c in kids)) if kids else set()
            for c in kids:                             # a one-prop or unusable group: its props instead
                if len(props_under(by, c)) < 2 or not by[c].get("supported_for_generation", True):
                    nxt += sorted(props_under(by, c))
                else:
                    nxt.append(c)
            nxt += [p for p in dict.fromkeys(x.split("/", 1)[0] for x in g.get("members", [])) if p not in inner]
        cur = list(dict.fromkeys(nxt))
    return cur


def options(ids: list[str]) -> dict:
    """For the GUI's menu (0.21): the groups above the selection (closest first) and, for one
    group, what is in it one, two and three levels down."""
    from .reroll import _context
    path, m, _, _ = _context()
    models = _models_doc(path, m)
    by = {x["id"]: x for x in models["models"]}
    ids = [i for i in ids if i in by]
    if not ids:
        return {"up": [], "down": []}
    why_not: list = []
    up = [{"id": g["id"], "props": len(props_under(by, g["id"]))} for g in groups_over(models, ids, why_not)[:12]]
    down = []
    if len(ids) == 1 and by[ids[0]]["kind"] == "group":
        seen = None
        for n in (1, 2, 3):
            k = children(models, ids[0], n)
            if k != seen:
                down.append({"levels": n, "to": k})
            seen = k
        allp = sorted(props_under(by, ids[0]))
        if allp != seen:
            down.append({"levels": "props", "to": allp})
    seen = {u["id"] for u in up} | {w["id"] for w in why_not}
    why_not += [{"id": gid, "why": why} for gid, ok, why in report(models, ids) if not ok and gid not in seen]
    return {"up": up, "down": down, "not": why_not[:10]}


def _span(words: list[str], profile: dict):
    from .explain import parse_time
    from .pins import _section_at
    times = [w for w in words if w.startswith("@")]
    if not times:
        raise SystemExit("which part of the song? e.g. '@#3' (section 3) or '@1:05'")
    t = parse_time(times[0], profile)
    sec = _section_at(profile, t)
    at = (sec["start"] + sec["end"]) / 2 if times[0].startswith("@#") else t
    return round(at, 3), sec


def _effect_of(m: dict, tid: str, sec: dict) -> tuple[str | None, str]:
    """The effect a target shows in a section (its own, or its group's), and its pass."""
    from .pins import _current_effect, _resolve
    target, pass_ = _resolve(m, tid)
    if pass_ == "pin":                                   # carried by a group
        for sk in m.get("diagnostics", {}).get("skipped_targets", []):
            if sk["id"] == tid and sk["reason"].startswith("driven via group "):
                g = sk["reason"][len("driven via group "):]
                own = _current_effect(m, tid, "place", sec["start"], sec["end"]) or \
                    _current_effect(m, tid, "pin", sec["start"], sec["end"])
                return own or _current_effect(m, g, "main", sec["start"], sec["end"]), "pin"
    for ps in ("place", pass_, "top"):
        e = _current_effect(m, target, ps, sec["start"], sec["end"])
        if e:
            return e, ps
    return None, pass_


def _same_section(profile: dict, a, b) -> bool:
    from .pins import _section_at
    return a is not None and b is not None and _section_at(profile, float(a)) is _section_at(profile, float(b))


def _sections(a, words: list[str], profile: dict):
    """[(at, section, repeats)]: the one asked for, or with --all every section (no repeats)."""
    if getattr(a, "all", False):
        return [(round((x["start"] + x["end"]) / 2, 3), x, False) for x in profile["sections"]]
    at, sec = _span(words, profile)
    return [(at, sec, not a.only)]


def _effect_arg(a, what: str) -> str | None:
    if not a.effect:
        return None
    e = canon(a.effect)
    if e not in config.load("effects")["effects"]:
        raise SystemExit(f"{what}: unknown effect '{a.effect}' - 'effects' lists them")
    return e


def main_promote(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool promote", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("words", nargs="+", help="TARGET... @#N|@TIME")
    ap.add_argument("--up", type=int, default=1, help="how many groups up (1 = the closest group holding them all)")
    ap.add_argument("--to", help="the group to promote to")
    ap.add_argument("--effect", help="the effect to give the group (default: the one the props show most)")
    ap.add_argument("--only", action="store_true", help="this section only, not the sections that repeat it")
    ap.add_argument("--all", action="store_true", help="the whole row: every section's effect, each in its section")
    ap.add_argument("--list", action="store_true", help="only list the groups it could go to, and why others can't")
    a = ap.parse_args(argv)
    from .reroll import _context
    from .pins import _apply_and_show
    path, m, profile, sha = _context()
    models = _models_doc(path, m)
    by = {x["id"]: x for x in models["models"]}
    names = [w for w in a.words if not w.startswith("@")]
    if not names:
        raise SystemExit("promote: which props? e.g. 'promote Flood01U Flood02U @#3'")
    if a.list:
        ids_ = [next((k for k in by if k.lower() == n.lower()), n) for n in names]
        print(f"{{head}}groups holding {', '.join(ids_)}{{/}} (closest first; from {path.with_name(m['source']['models']['filename']).name}):")
        for gid, ok, why in report(models, ids_):
            print(f"  {gid:<28} " + ("{ok}offered{/}" if ok else "{warn}not offered{/}: " + why))
        return 0
    low = {k.lower(): k for k in by}
    ids = []
    for n in names:
        for part in [x for x in n.split(",") if x]:
            if part.lower() not in low:
                from ..common.suggest import suggest
                raise SystemExit(f"promote: no prop or group '{part}'" + suggest(part, list(by)) + " - 'models' lists them")
            ids.append(low[part.lower()])
    if not a.all and not any(w.startswith("@") for w in a.words):
        raise SystemExit(f"promote: which part of the song? e.g. 'promote {names[0]} @#3', or --all for the whole row")
    ups = groups_over(models, ids)
    if not ups:
        raise SystemExit(f"promote: no group holds {', '.join(ids)} - 'groups {ids[0]}' shows its groups")
    if a.to:
        g = next((x for x in ups if x["id"].lower() == a.to.lower()), None)
        if g is None:
            raise SystemExit(f"promote: {a.to} doesn't hold {', '.join(ids)} - the groups that do, closest first: "
                             + ", ".join(x["id"] for x in ups[:8]))
    else:
        if a.up > len(ups):
            warn(f"only {len(ups)} group(s) above: {', '.join(x['id'] for x in ups)} - using the last")
        g = ups[min(a.up, len(ups)) - 1]
    forced = _effect_arg(a, "promote")
    pins = list(songs.get(sha).get("pins", []))
    inside = props_under(by, g["id"])
    done, gone_n = [], 0
    for at, sec, reps in _sections(a, a.words, profile):
        effs = {i: _effect_of(m, i, sec)[0] for i in ids}
        cnt = Counter(e for e in effs.values() if e and e != "transparent")
        effect = forced or (cnt.most_common(1)[0][0] if cnt else None)
        if effect is None:
            if not a.all:
                raise SystemExit(f"promote: {', '.join(ids)} show nothing in section #{sec['index']} - name the effect, "
                                 f"e.g. 'promote {' '.join(names)} @#{sec['index']} --effect color_wash'")
            continue
        if len(cnt) > 1 and not forced:
            info(f"  #{sec['index']}: different effects - " + ", ".join(f"{i} {e}" for i, e in effs.items())
                 + f"; promoting {effect} (the most common; --effect picks another)")
        gone = [p for p in pins if p.get("pass") == "place" and p["target"] != g["id"]
                and props_under(by, p["target"]) <= inside and _same_section(profile, p.get("at"), at)]
        gone_n += len(gone)
        pins = [p for p in pins if p not in gone and not (p["target"] == g["id"] and _same_section(profile, p.get("at"), at)
                                                          and (p.get("pass") == "place" or p.get("how") == "demoted"))]
        pins.append({"target": g["id"], "pass": "place", "at": at, "effect": effect, "repeats": reps,
                     "how": "promoted from " + ", ".join(ids)})
        done.append(f"#{sec['index']} {effect}")
    if not done:
        raise SystemExit(f"promote: {', '.join(ids)} show nothing anywhere - 'run' first?")
    songs.update(sha, pins=pins)
    more = [x["id"] for x in ups[ups.index(g) + 1:ups.index(g) + 4]]
    where = f"@#{done[0].split()[0][1:]}" if not a.all else "--all"
    _apply_and_show(f"promoted {', '.join(ids)} to {g['id']}: " + ", ".join(done)
                    + (f" (replaces {gone_n} placed effect(s) inside it)" if gone_n else ""), m, profile)
    print("  {note}" + (f"'unpin {g['id']} {where}' undoes it" if not a.all else f"'unpin {g['id']}' undoes it")
          + (f"; further up: {', '.join(more)} ('promote {g['id']} {where}')" if more else "") + "{/}")
    return 0


def main_demote(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool demote", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("words", nargs="+", help="GROUP @#N|@TIME")
    ap.add_argument("--down", type=int, default=1, help="how many levels down (1 = its groups and direct props)")
    ap.add_argument("--to", nargs="+", help="'props' (every prop in it) or the groups / props to hand it to")
    ap.add_argument("--effect", help="the effect to hand down (default: the one the group shows there)")
    ap.add_argument("--only", action="store_true", help="this section only, not the sections that repeat it")
    ap.add_argument("--all", action="store_true", help="the whole row: every section's effect, each in its section")
    a = ap.parse_args(argv)
    from .reroll import _context
    from .pins import _apply_and_show
    path, m, profile, sha = _context()
    models = _models_doc(path, m)
    by = {x["id"]: x for x in models["models"]}
    names = [w for w in a.words if not w.startswith("@")]
    if len(names) != 1:
        raise SystemExit("demote: one group, e.g. 'demote 4.Floods-all @#3'")
    gid = next((k for k in by if k.lower() == names[0].lower()), None)
    if gid is None or by[gid]["kind"] != "group":
        raise SystemExit(f"demote: no group '{names[0]}' - 'groups' lists them (a prop has nothing to hand down to)")
    if not a.all and not any(w.startswith("@") for w in a.words):
        raise SystemExit(f"demote: which part of the song? e.g. 'demote {gid} @#3', or --all for the whole row")
    if a.to:
        if [t.lower() for t in a.to] == ["props"]:
            kids = sorted(props_under(by, gid))
        else:
            kids = []
            inside = props_under(by, gid)
            for t in a.to:
                k = next((x for x in by if x.lower() == t.lower()), None)
                if k is None or not props_under(by, k) <= inside:
                    raise SystemExit(f"demote: '{t}' isn't in {gid} - 'groups {gid}' shows what is")
                kids.append(k)
    else:
        kids = children(models, gid, a.down)
    kids = [k for k in kids if k != gid and (by.get(k, {}).get("supported_for_generation", True))]
    if not kids:
        raise SystemExit(f"demote: nothing in {gid} to hand down to")
    forced = _effect_arg(a, "demote")
    pins = list(songs.get(sha).get("pins", []))
    done = []
    for at, sec, reps in _sections(a, a.words, profile):
        effect, pass_ = _effect_of(m, gid, sec)
        effect = forced or effect
        if effect is None or effect == "transparent":
            if not a.all:
                raise SystemExit(f"demote: {gid} shows nothing in section #{sec['index']} - name the effect with --effect")
            continue
        mine = [p for p in pins if p["target"] == gid and p.get("pass") == "place" and _same_section(profile, p.get("at"), at)]
        pins = [p for p in pins if p not in mine]
        if not mine:                                 # the group's own plan rests there
            pins = [p for p in pins if not (p["target"] == gid and p.get("pass", "main") == pass_
                                             and _same_section(profile, p.get("at"), at))]
            pins.append({"target": gid, "pass": pass_, "at": at, "effect": "transparent", "repeats": reps,
                         "how": "demoted"})
        for k in kids:
            pins = [p for p in pins if not (p["target"] == k and p.get("pass") == "place"
                                             and _same_section(profile, p.get("at"), at))]
            pins.append({"target": k, "pass": "place", "at": at, "effect": effect, "repeats": reps,
                         "how": f"demoted from {gid}"})
        done.append(f"#{sec['index']} {effect}")
    if not done:
        raise SystemExit(f"demote: {gid} shows nothing anywhere to hand down")
    songs.update(sha, pins=pins)
    _apply_and_show(f"demoted {gid} to {len(kids)} target(s) ({', '.join(kids[:8])}{' ...' if len(kids) > 8 else ''}): "
                    + ", ".join(done), m, profile)
    where = "--all" if a.all else done[0].split()[0].replace("#", "@#")
    print("  {note}" + f"'promote {' '.join(kids[:3])}{' ...' if len(kids) > 3 else ''} {where} --to {gid}' "
          f"puts it back (or 'unpin' each; 'pin' lists them){{/}}")
    return 0


if __name__ == "__main__":
    sys.exit(main_promote())
