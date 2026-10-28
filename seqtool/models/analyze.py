# seqtool-command: analyze-models | main | stages | layout.json -> models.json
"""Model analyzer: seqtool.layout -> seqtool.models (geometry features + capabilities).

Groups are analysed two ways depending on render_hint:
  as_one   - the union of member points is analysed as one canvas
  per_prop - the effect repeats on each member, so capabilities are the
             members' mean; 'progression' measures how well the members line up
             as a sequence (Arch1 -> Arch4 style chases across props)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import re

import numpy as np

from ..common.canonical import content_sha256, read_json, write_json
from ..common.envelope import check_version, envelope, merge_lineage
from ..common.log import info, warn
from ..common.schemas import validate
from ..layout.shapes import prop_points
from . import capabilities, geometry
from ..common.paths import arg as paths_arg

UNSUPPORTED_CLASSES = {"SEMANTIC", "MECHANICAL", "POINT"}


def _norm_bounds(b: dict, extent: float) -> dict:
    return {k: round(v / extent, 4) for k, v in b.items()}


def _record(id_, name, kind, f, cls, src, guess, caps, extent, members=None, origin=None,
            semantic=None, shape_type=None, controllable=True):
    geom = {k: v for k, v in f.items() if k != "node_count"}
    if "bounds" in geom:
        geom["bounds_norm"] = _norm_bounds(geom["bounds"], extent)
        geom["scale_norm"] = round(max(geom["bounds"].values()) / extent, 4)
    rec = {"id": id_, "name": name, "kind": kind}
    if members is not None:
        rec["members"] = members
    if shape_type:
        rec["shape_type"] = shape_type
    if semantic:
        rec["semantic"] = semantic
    rec["node_count"] = f.get("node_count", 0)
    ok = controllable and cls not in UNSUPPORTED_CLASSES
    rec["supported_for_generation"] = ok
    if not ok:
        rec["unsupported_reason"] = ("marked not controllable" if not controllable
                                     else f"class {cls} not supported in MVP")
    rec.update(geometry_class=cls, class_source=src, geometry_guess=guess, geometry=geom,
               capabilities=caps if ok else {})
    if origin:
        rec["origin"] = origin
    return rec


def node_indices(lines: list[str], n: int) -> list[int]:
    """xLights submodel ranges ("1-25,30,40-35") -> 0-based point indices (valid, unique, in order)."""
    out: list[int] = []
    for line in lines:
        for part in (line or "").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                if "-" in part:
                    a, b = (int(x) for x in part.split("-", 1))
                    rng = range(a, b + 1) if a <= b else range(a, b - 1, -1)
                else:
                    rng = [int(part)]
            except ValueError:
                continue
            out += [i - 1 for i in rng if 1 <= i <= n]
    return list(dict.fromkeys(out))


LEVEL = re.compile(r"^\s*(\d+)\s*[.\-_ )]")


def name_level(name: str) -> int | None:
    """xLights users often number groups to force their order ('1.ALL', '5.Spinner-spokes'):
    a smaller number is a higher-level group. None when the name has no such prefix."""
    m = LEVEL.match(name)
    return int(m.group(1)) if m else None


def guess_role(kind: str, info: dict) -> tuple[str, str]:
    """(role, reason) for a group of this kind, from the facts guess_roles() recorded."""
    lvl = f", level {info['level']}" if info.get("level") is not None else ""
    if "usable" not in info and info.get("role"):        # a guess from 0.16.0 without the facts: keep it
        return info["role"].replace("off", "unused"), info.get("reason", "")
    if not info.get("usable", True):
        return "unused", info.get("why_unusable") or "no props seqtool can sequence in it"
    if info.get("duplicate_of"):
        if info.get("duplicate_note"):
            return "unused", f"the same sequenced props as {info['duplicate_of']} ({info['duplicate_note']})"
        return "unused", f"same props as {info['duplicate_of']}"
    cov = info.get("coverage", 0.0)
    n, k = info.get("props"), info.get("subgroups", 0)
    what = ("its props" if n is None else f"{n} prop{'' if n == 1 else 's'}") + \
        (f" in {k} group{'' if k == 1 else 's'}" if k else "")              # None: analysed before 0.20.5
    pc = "under 1%" if 0 < cov < 0.005 else f"{cov:.0%}"
    if kind in ("umbrella", "leaf") and round(cov, 2) >= 0.9:     # as shown: "90%"
        return "top", f"the whole yard ({what}, {pc} of the lights{lvl}): takes over the intro and outro"
    if kind == "umbrella":
        return "top", (f"over {what} ({pc} of the lights{lvl}): widest top group takes over whole sections; "
                       "otherwise it covers props not under a unit")
    if kind == "submodel_view":                       # 0.20.5, the user's rule: a prop whose parts a group plays
        return "unit", (f"parts (submodels) of {'its props' if n is None else str(n) + ' prop' + ('s' if n != 1 else '')}: sequenced as one, in place of the "
                        "props themselves ('detail' would add accents on top of the props instead)")
    if kind == "leaf":
        return "unit", f"{what}: sequenced as one, in place of the props themselves{lvl}"
    if kind == "single":
        return "unused", "one prop: sequenced as the prop itself"
    return "unused", "no props in it"


def member_reasons(reasons: list[str]) -> str:
    """The members' own reasons, summed up for their group (0.20.1: in general words, with
    the names that matter - not one member's reason word for word)."""
    import re as _re
    from collections import Counter
    cat: dict[str, set] = {}
    for r in reasons:
        m = _re.search(r"shadow model '([^']+)'", r)
        if m:
            cat.setdefault("shadow", set()).add(m.group(1))
            continue
        m = _re.search(r"shadow model of '([^']+)'", r)
        if m:
            cat.setdefault("shadow_of", set()).add(m.group(1))
            continue
        if "inactive" in r:
            cat.setdefault("inactive", set()).add("inactive")
            continue
        m = _re.search(r"layout group '([^']+)'", r)
        if m:
            cat.setdefault("layout_group", set()).add(m.group(1))
            continue
        m = _re.search(r"controller '([^']+)'", r)
        if m:
            cat.setdefault("controller", set()).add(m.group(1))
            continue
        m = _re.search(r"name matches '([^']+)'", r)
        if m:
            cat.setdefault("name", set()).add(m.group(1))
            continue
        m = _re.match(r"class (\w+)", r)
        if m:
            cat.setdefault("class", set()).add(m.group(1))
            continue
        cat.setdefault("other", set()).add(r)
    q = lambda xs: ", ".join(sorted(xs)[:3]) + (" ..." if len(xs) > 3 else "")      # noqa: E731
    say = {"shadow": lambda xs: f"its props share their channels with shadow model(s) {q(xs)}, sequenced instead",
           "shadow_of": lambda xs: f"its props are shadow models of {q(xs)}, sequenced instead",
           "inactive": lambda xs: "its props are marked inactive in xLights",
           "layout_group": lambda xs: f"its props are in an excluded layout group ({q(xs)})",
           "controller": lambda xs: f"its props are on an excluded controller ({q(xs)})",
           "name": lambda xs: f"its props' names match an excluded pattern ({q(xs)})",
           "class": lambda xs: f"its props are {q(xs)} props, not sequenced yet",
           "other": lambda xs: "its props aren't sequenced: " + q(xs)}
    n = Counter({k: sum(1 for r in reasons for x in v if x in r) for k, v in cat.items()})
    parts = [say[k](cat[k]) for k, _ in n.most_common()]
    return parts[0] + (f" (and {len(parts) - 1} other reason{'s' if len(parts) > 2 else ''}: 'models --unused')"
                       if len(parts) > 1 else "")


def guess_roles(models: list[dict]) -> None:
    """Add role_guess to every group: the facts (coverage of the yard's lights, an
    earlier group with exactly the same props, the level from a numbered name) and
    the role they suggest. Used when preferences say 'auto' for the group's kind
    (the default for umbrella and submodel groups); a role you set, or one a name
    rule sets, always wins ('groups' reviews them). Of groups with the same props the
    one with the lowest level number is used (then the largest, then by name)."""
    usable = {m["id"]: m.get("node_count", 0) for m in models if m["kind"] == "model" and m.get("supported_for_generation")}
    by_id = {m["id"]: m for m in models}

    def why_unusable(g: dict) -> str:
        """A short reason a group has nothing to sequence (the user's wording, 0.19.8)."""
        mem = g.get("members", [])
        if not mem:
            return "no props added to it"
        ok = [x for x in mem if x in usable]
        if ok:                                         # its props are fine: the group's own shape isn't
            if len(ok) == 1:
                return "one prop: sequenced as the prop itself"
            r = g.get("unsupported_reason", "")
            return (f"a {r.split()[1]} group isn't sequenced as one yet; its props are, each on its own"
                    if r.startswith("class ") else f"{r}; its props are sequenced on their own")
        kinds = [by_id[x]["kind"] if x in by_id else "missing" for x in mem]
        if all(k == "group" for k in kinds):
            return "only groups in it, used on their own" if len(mem) > 1 else f"only the group {mem[0]}, used on its own"
        if all(k == "missing" for k in kinds):
            return "its props are excluded (layout groups seqtool leaves out)"
        if all(k in ("group", "submodel") for k in kinds):
            return "only parts of props (submodels) and groups in it"
        reasons = [by_id[x].get("unsupported_reason", "") for x in mem
                   if x in by_id and by_id[x]["kind"] == "model" and not by_id[x].get("supported_for_generation")]
        if reasons:
            return member_reasons(reasons)
        if not g.get("supported_for_generation", True) and g.get("unsupported_reason"):
            return g["unsupported_reason"].replace(" in MVP", " yet")
        return "its props aren't sequenced"
    total = sum(usable.values()) or 1
    groups = [g for g in models if g["kind"] == "group"]
    order = sorted(groups, key=lambda g: (name_level(g["id"]) if name_level(g["id"]) is not None else 999,
                                          -g.get("node_count", 0), g["id"]))
    seen: dict[frozenset, str] = {}
    for g in order:
        mem = frozenset(x for x in g.get("members", []) if x in usable)
        info = {"usable": bool(mem) and bool(g.get("supported_for_generation")),
                "coverage": round(sum(usable[x] for x in mem) / total, 4), "level": name_level(g["id"]),
                "props": len(mem), "subgroups": len(g.get("child_groups", []))}
        if not info["usable"]:
            info["why_unusable"] = why_unusable(g)
        if mem and mem in seen and g.get("group_kind") in ("umbrella", "leaf"):
            info["duplicate_of"] = seen[mem]
            other = next((x for x in groups if x["id"] == seen[mem]), {})
            om, gm = set(other.get("members", [])), set(g.get("members", []))
            extra, mine = sorted(om - gm), sorted(gm - om)           # the same sequenced props, not the same props
            if extra or mine:
                info["duplicate_note"] = ", ".join(
                    ([f"{seen[mem]} also holds {len(extra)} prop(s) that aren't sequenced ({', '.join(extra[:3])}"
                      + (" ..." if len(extra) > 3 else "") + ")"] if extra else [])
                    + ([f"this one also holds {len(mine)} that aren't ({', '.join(mine[:3])}"
                        + (" ..." if len(mine) > 3 else "") + ")"] if mine else []))
        elif mem and g.get("group_kind") in ("umbrella", "leaf"):
            seen[mem] = g["id"]
        role, why = guess_role(g.get("group_kind", "leaf"), info)
        g["role_guess"] = {"role": role, "reason": why, **info}


ANALYSIS_VERSION = 2          # 0.24.36: groups' render_classes (as one / per prop); older analyses are made again


def outdated(models: dict) -> list[str]:
    """Why a stored prop analysis must be made again with this seqtool (empty: it is fine)."""
    v = int(models.get("analysis_version", 1))
    return [] if v >= ANALYSIS_VERSION else ["the prop analysis is from an older seqtool"]


def analyze(layout: dict, layout_name: str | None = None) -> dict:
    check_version(layout, "seqtool.layout")
    validate(layout, "seqtool.layout")
    pts: dict[str, np.ndarray] = {}
    for p in layout["props"]:
        try:
            pts[p["id"]] = prop_points(p)
        except Exception as e:  # bad params shouldn't kill the whole layout
            warn(f"prop {p['id']}: cannot build points ({e})")
            pts[p["id"]] = np.zeros((0, 3))
    allp = np.vstack([v for v in pts.values() if len(v)]) if any(len(v) for v in pts.values()) else np.zeros((1, 3))
    extent = float((allp.max(axis=0) - allp.min(axis=0)).max()) or 1.0
    lo, span = allp.min(axis=0), np.maximum(allp.max(axis=0) - allp.min(axis=0), 1e-9)

    def yard(P) -> dict | None:
        """Where it is in the yard, 0..1 left to right and bottom to top (0.20: sweeps and
        call and response in the base pass order props by it)."""
        if not len(P):
            return None
        c = (P.mean(axis=0) - lo) / span
        return {"x": round(float(c[0]), 4), "y": round(float(c[1]), 4)}

    models, recs = [], {}
    for p in layout["props"]:
        f = geometry.features(pts[p["id"]])
        cls, src, guess = geometry.classify(f, p.get("semantic"))
        caps = capabilities.derive(cls, f)
        r = _record(p["id"], p["name"], "model", f, cls, src, guess, caps, extent,
                    origin=p.get("origin"), semantic=p.get("semantic"),
                    shape_type=p["shape"]["type"], controllable=p.get("controllable", True))
        if p.get("render_buffer"):
            r["render_buffer"] = p["render_buffer"]
        if yard(pts[p["id"]]):
            r["yard"] = yard(pts[p["id"]])
        if p.get("faces"):                          # singing faces (0.19): their names and kinds
            r["faces"] = [{"name": f["name"], "kind": f.get("kind")} for f in p["faces"]]
        if p.get("skip_reason") and not r["supported_for_generation"]:
            r["unsupported_reason"] = p["skip_reason"]
        recs[p["id"]] = r
        models.append(r)

    sub_pts: dict[str, np.ndarray] = {}
    for p in layout["props"]:
        parent = recs[p["id"]]
        P = pts[p["id"]]
        for sm in p.get("submodels", []):
            idx = node_indices(sm.get("lines", []), len(P))
            if not idx:
                continue
            sid = f"{p['id']}/{sm['name']}"
            Q = P[idx]
            sub_pts[sid] = Q
            f = geometry.features(Q)
            cls, src, guess = geometry.classify(f, None)
            caps = capabilities.derive(cls, f)
            r = _record(sid, sm["name"], "submodel", f, cls, src, guess, caps, extent,
                        controllable=parent["supported_for_generation"])
            r["parent"] = p["id"]
            r["rows"] = len([x for x in sm.get("lines", []) if x.strip()])
            if not parent["supported_for_generation"]:
                r["unsupported_reason"] = f"parent {p['id']}: {parent.get('unsupported_reason', 'not usable')}"
            models.append(r)
            recs[sid] = r

    for g in layout["groups"]:
        detail = [x for x in g.get("structure", {}).get("submodels", []) if x in sub_pts]
        if detail and g.get("structure", {}).get("kind") == "submodel_view":
            union = np.vstack([sub_pts[x] for x in detail])
            f = geometry.features(union)
            cls, src, guess = geometry.classify(f, None)
            caps = capabilities.derive(cls, f)
            if len(detail) >= 3:
                cent = np.array([sub_pts[x].mean(axis=0) for x in detail])
                caps["progression"] = round(geometry.features(cent)["linearity"], 4)
            r = _record(g["id"], g["name"], "group", f, cls, src, guess, caps, extent,
                        members=g["members"], origin=g.get("origin"))
            r["render_hint"] = g.get("render_hint", "per_prop")
            r["group_kind"] = "submodel_view"
            r["detail_members"] = detail
            if g.get("structure", {}).get("groups"):
                r["child_groups"] = list(g["structure"]["groups"])
            models.append(r)
            continue
        mem = [m for m in g["members"] if m in pts and len(pts[m])]
        if not mem:
            if g.get("structure", {}).get("kind") != "empty":
                warn(f"group {g['id']}: no usable members")
            continue
        union = np.vstack([pts[m] for m in mem])
        f = geometry.features(union)
        hint = g.get("render_hint", "per_prop")
        mrecs = [recs[m] for m in mem if recs[m]["supported_for_generation"]]
        member_classes: dict[str, int] = {}
        for r_ in mrecs:
            member_classes[r_["geometry_class"]] = member_classes.get(r_["geometry_class"], 0) + 1
        whole_cls = geometry.classify(f, None)[0]
        if hint == "per_prop" and mrecs:
            classes = sorted({r["geometry_class"] for r in mrecs})
            cls = classes[0] if len(classes) == 1 else "IRREGULAR"
            keys = sorted({k for r in mrecs for k in r["capabilities"]})
            caps = {k: round(float(np.mean([r["capabilities"].get(k, 0) for r in mrecs])), 4) for k in keys}
            src, guess = "members", cls
        else:
            cls, src, guess = geometry.classify(f, None)
            caps = capabilities.derive(cls, f)
        if len(mem) >= 3:  # do member centroids form a sequence?
            cent = np.array([pts[m].mean(axis=0) for m in mem])
            caps["progression"] = round(geometry.features(cent)["linearity"], 4)
        r = _record(g["id"], g["name"], "group", f, cls, src, guess, caps, extent,
                    members=g["members"], origin=g.get("origin"))
        r["render_hint"] = hint
        if mrecs:                                     # 0.24.36: as one picture, or on each prop
            r["render_classes"] = {"group": whole_cls, "per_model": member_classes}
        kind = g.get("structure", {}).get("kind")
        if kind is None:
            kind = "single" if len(set(mem)) == 1 else "leaf"
        r["group_kind"] = kind
        if g.get("structure", {}).get("groups"):
            r["child_groups"] = list(g["structure"]["groups"])
        models.append(r)

    guess_roles(models)
    lineage = merge_lineage(layout)
    doc = envelope("seqtool.models", "seqtool-analyze-models",
                   {"layout": {"schema": layout["schema"], "schema_version": layout["schema_version"],
                               "content_sha256": content_sha256(layout),
                               **({"filename": layout_name} if layout_name else {})}},
                   lineage)
    doc["extent"] = extent
    doc["units"] = layout["units"]
    doc["models"] = models
    doc["analysis_version"] = ANALYSIS_VERSION
    validate(doc, "seqtool.models")
    return doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool analyze-models", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("layout", type=paths_arg)
    ap.add_argument("--output", "-o", type=paths_arg, default=None,
                    help="default: <layout>-seqtool/<layout>.models.json, in a subfolder next to the input")
    a = ap.parse_args(argv)
    from ..common.paths import seqtool_name
    a.output = a.output or seqtool_name(a.layout, "models")
    doc = analyze(read_json(a.layout), a.layout.name)
    write_json(a.output, doc)
    for m in doc["models"]:
        flag = "" if m["supported_for_generation"] else f"  (skipped: {m['unsupported_reason']})"
        info(f"  {m['kind']:<5} {m['id']:<16} {m['geometry_class']:<11} "
             f"[{m['class_source']}, geometry says {m['geometry_guess']}]{flag}")
    info(f"wrote {a.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


def containing_groups(doc_models: list[dict], prop: str) -> list[tuple[dict, int, bool]]:
    """The groups a prop is in, closest first (0.20.7, the user's rule): [(group, distance,
    by_parts)]. Distance 0: the prop (or one of its parts) is listed in the group itself;
    1: in a group listed in it; and so on. by_parts: only its submodels are in the group."""
    groups = [m for m in doc_models if m["kind"] == "group"]
    by = {g["id"]: g for g in groups}
    pid = prop.split("/", 1)[0]

    def under(g, seen=()):                          # every prop a group reaches through its child groups
        out = set()
        for c in g.get("child_groups", []):
            if c in by and c not in seen:
                out |= set(x.split("/", 1)[0] for x in by[c].get("members", [])) | under(by[c], seen + (c,))
        return out
    dist: dict[str, int] = {}
    parts: dict[str, bool] = {}
    if prop in by:                                  # a group (0.21.1): the groups listing it come first
        for g in groups:
            if prop in g.get("child_groups", []):
                dist[g["id"]], parts[g["id"]] = 0, False
    for g in groups:
        mem = {x.split("/", 1)[0] for x in g.get("members", [])}
        if prop in by:
            break
        if pid in mem and pid not in under(g):
            dist[g["id"]] = 0
            parts[g["id"]] = any(x.split("/", 1)[0] == pid and "/" in x for x in g.get("detail_members", []))
    frontier = set(dist)
    d = 0
    while frontier:
        d += 1
        nxt = set()
        for g in groups:
            if g["id"] not in dist and frontier & set(g.get("child_groups", [])):
                dist[g["id"]] = d
                parts[g["id"]] = False
                nxt.add(g["id"])
        frontier = nxt
    for g in groups:                                # in it, but the chain isn't known (flattened layouts)
        if g["id"] not in dist and prop not in by and pid in {x.split("/", 1)[0] for x in g.get("members", [])}:
            dist[g["id"]] = d + 1
            parts[g["id"]] = False
    return sorted(((by[k], v, parts[k]) for k, v in dist.items()),
                  key=lambda t: (t[1], len(t[0].get("members", [])), t[0]["id"]))
