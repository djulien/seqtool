# seqtool-command: xlights-import | main | stages | xlights_rgbeffects.xml -> layout.json (one-off; see 'layout')
"""xLights input adapter: xlights_rgbeffects.xml -> generic seqtool.layout.

Reads the XML file format only (no xLights code). Mapping rules, learned from
a real show file:

  * "Boxed" models (matrix, tree, custom, ...) are centred on WorldPos and their
    world size is (render-buffer size in nodes) x Scale. Shapes are therefore
    generated in node units, centred, then scaled.
  * Two-point models (Single Line, Icicles) run from WorldPos to WorldPos+(X2,Y2,Z2);
    Poly Line vertices are WorldPos + PointData x Scale.
  * Custom models use the CustomModel grid: '|' separates depth layers,
    ';' rows, ',' cells; a cell holds the node number (wiring order).
  * Tree "Tree <deg>" gives coverage degrees; parm1 x parm3 strands of
    parm2/parm3 nodes; TreeBottomTopRatio gives the taper.
  * Lines with only a few nodes (DMX single-pixel fixtures, flood strips) are
    marked semantic "flood".
  * Models excluded by preferences/xlights.json (dev/hide layout groups,
    placeholder names, controllers listed in exclude_controllers, shadow models) are kept but marked
    not controllable, with the reason.
  * Groups: nested groups are flattened to models; "Model/Sub" submodel refs map
    to their parent model; empty entries ignored; unknown names reported. Each
    group gets a structure.kind (leaf, umbrella, submodel_view, single, empty)
    and a render_hint from its xLights buffer layout.
  * Sequencer views (and the default one) are kept as generic 'views'.
  * Submodels (type "ranges") are kept with their node ranges; seqtool names
    them "Model/Sub", as xLights does in groups. Their points are the
    parent's points in node order (an approximation: the parent's start
    corner and direction are not modelled).
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from ...common.canonical import file_sha256, write_json
from ...common.config import load as load_prefs
from ...common.envelope import envelope
from ...common.log import good, info, warn
from ...common.schemas import validate
from ...common.paths import arg as paths_arg


def _f(m, k, d=0.0):
    try:
        return float(m.get(k, d))
    except (TypeError, ValueError):
        return d


def _i(m, k, d=1):
    try:
        return max(1, int(float(m.get(k, d))))
    except (TypeError, ValueError):
        return d


def custom_points(spec: str) -> list[list[float]]:
    """CustomModel grid -> node positions in wiring order (x right, y up, z toward viewer)."""
    nodes: dict[int, tuple[float, float, float]] = {}
    for z, layer in enumerate(spec.split("|")):
        for y, row in enumerate(layer.split(";")):
            for x, cell in enumerate(row.split(",")):
                cell = cell.strip()
                if cell.isdigit() and int(cell) > 0:
                    nodes.setdefault(int(cell), (float(x), float(-y), float(-z)))
    return [list(nodes[k]) for k in sorted(nodes)]


def _boxed(m) -> dict:
    return {"position": [_f(m, "WorldPosX"), _f(m, "WorldPosY"), _f(m, "WorldPosZ")],
            "scale": [_f(m, "ScaleX", 1.0) or 1.0, _f(m, "ScaleY", 1.0) or 1.0, _f(m, "ScaleZ", 1.0) or 1.0],
            "rotation_deg": [_f(m, "RotateX"), _f(m, "RotateY"), _f(m, "RotateZ")],
            "anchor": "center"}


def _two_point(m) -> tuple[dict, list[list[float]]]:
    tf = {"position": [_f(m, "WorldPosX"), _f(m, "WorldPosY"), _f(m, "WorldPosZ")]}
    return tf, [[0.0, 0.0, 0.0], [_f(m, "X2"), _f(m, "Y2"), _f(m, "Z2")]]


def map_model(m: ET.Element, prefs: dict) -> tuple[dict | None, dict, str | None]:
    """Return (shape, transform, semantic); shape None = not mappable."""
    da = m.get("DisplayAs", "")
    p1, p2, p3 = _i(m, "parm1"), _i(m, "parm2"), _i(m, "parm3")
    if da.startswith("Tree"):
        strands = p1 * p3
        per = max(1, p2 // max(p3, 1)) if p3 > 1 else p2
        if "Flat" in da or "Ribbon" in da:
            return ({"type": "flat_tree", "params": {"base_width": strands, "height": per, "strings": strands,
                                                     "nodes_per_string": per}}, _boxed(m), "tree")
        deg = float(re.search(r"(\d+)", da).group(1)) if re.search(r"(\d+)", da) else 360.0
        ratio = _f(m, "TreeBottomTopRatio", 6.0) or 6.0
        return ({"type": "cone", "params": {"base_diameter": strands, "top_diameter": strands / ratio,
                                             "height": per, "strings": strands, "nodes_per_string": per,
                                             "degrees": deg}}, _boxed(m), "tree")
    if da in ("Horiz Matrix", "Vert Matrix", "Matrix"):
        strands, per = p1 * p3, max(1, p2 // max(p3, 1))
        cols, rows = (per, strands) if da == "Horiz Matrix" else (strands, per)
        if cols == 1 or rows == 1:   # a single strand: it's a line, not a surface
            n = max(cols, rows)
            pts = [[0.0, float(-i), 0.0] for i in range(n)] if cols == 1 else [[float(i), 0.0, 0.0] for i in range(n)]
            return {"type": "points", "params": {"points": pts}}, _boxed(m), None
        return ({"type": "grid", "params": {"width": cols - 1, "height": rows - 1, "columns": cols, "rows": rows}},
                _boxed(m), "matrix")
    if da in ("Single Line", "Icicles"):
        tf, pts = _two_point(m)
        n = p1 * p2
        sem = "icicles" if da == "Icicles" else ("flood" if n <= prefs["flood_max_nodes"] else None)
        return {"type": "polyline", "params": {"points": pts, "nodes": n}}, tf, sem
    if da == "Poly Line":
        raw = [float(v) for v in m.get("PointData", "").split(",") if v.strip()]
        sc = [_f(m, "ScaleX", 1.0) or 1.0, _f(m, "ScaleY", 1.0) or 1.0, _f(m, "ScaleZ", 1.0) or 1.0]
        pts = [[raw[i] * sc[0], raw[i + 1] * sc[1], raw[i + 2] * sc[2]] for i in range(0, len(raw) - 2, 3)]
        if len(pts) < 2:
            return None, {}, None
        tf = {"position": [_f(m, "WorldPosX"), _f(m, "WorldPosY"), _f(m, "WorldPosZ")]}
        return {"type": "polyline", "params": {"points": pts, "nodes": p1 * p2}}, tf, "outline"
    if da == "Arches":
        return {"type": "arc", "params": {"width": p2, "height": p2 / 2, "nodes": p1 * p2}}, _boxed(m), "arch"
    if da == "Candy Canes":
        return {"type": "arc", "params": {"width": p2 / 3, "height": p2, "nodes": p1 * p2}}, _boxed(m), "candy_cane"
    if da in ("Circle", "Wreath"):
        return {"type": "ring", "params": {"diameter": p1 * p2 / 3.1416, "nodes": p1 * p2}}, _boxed(m), "wreath"
    if da == "Star":
        return ({"type": "star", "params": {"diameter": p1 * p2 / 4, "points": max(p3, 3), "nodes": p1 * p2,
                                             "ratio": 0.4}}, _boxed(m), "star")
    if da == "Spinner":
        return ({"type": "radial", "params": {"diameter": 2 * p2, "arms": p1 * p3, "nodes_per_arm": p2,
                                               "hollow": _f(m, "Hollow", 10) / 100}}, _boxed(m), "spinner")
    if da in ("Cube", "Sphere"):
        return ({"type": "volume", "params": {"width": p1, "height": p2, "depth": p3, "columns": p1,
                                               "rows": p2, "layers": p3}}, _boxed(m), da.lower())
    if da == "Custom" and m.get("CustomModel"):
        pts = custom_points(m.get("CustomModel"))
        if pts:
            depth = _i(m, "Depth", 1)
            return {"type": "points", "params": {"points": pts}}, _boxed(m), ("sculpture" if depth > 1 else None)
    return None, {}, None


def render_buffer(m, shape) -> dict | None:
    """The node grid xLights renders effects on (default buffer). Physical size,
    which only affects how big the prop looks in previews, comes from Scale."""
    da = m.get("DisplayAs", "")
    p1, p2, p3 = _i(m, "parm1"), _i(m, "parm2"), _i(m, "parm3")
    if da == "Custom":
        rb = {"columns": p1, "rows": p2}
        if _i(m, "Depth", 1) > 1:
            rb["layers"] = _i(m, "Depth", 1)
        return rb
    if da.startswith("Tree") or da in ("Vert Matrix", "Matrix"):
        return {"columns": p1 * p3, "rows": max(1, p2 // max(p3, 1)) if p3 > 1 else p2}
    if da == "Horiz Matrix":
        return {"columns": max(1, p2 // max(p3, 1)) if p3 > 1 else p2, "rows": p1 * p3}
    if da in ("Single Line", "Poly Line", "Icicles", "Arches", "Candy Canes", "Circle", "Wreath", "Star"):
        return {"columns": p1 * p2, "rows": 1}
    if da == "Spinner":
        return {"columns": p1 * p3, "rows": p2}
    return None


def _exclusion(m, prefs) -> str | None:
    name, lg, ctrl = m.get("name", ""), m.get("LayoutGroup", ""), m.get("Controller", "")
    if m.get("Active", "1").strip() == "0":                 # 'Active' unticked in xLights (0.20.2)
        return "marked inactive in xLights"
    if name in prefs.get("exclude_models", []):
        return "listed in exclude_models"
    if lg in prefs["exclude_layout_groups"]:
        return f"layout group '{lg}' is excluded"
    if ctrl in prefs["exclude_controllers"]:
        return f"controller '{ctrl}' is excluded"
    for pat in prefs["exclude_name_patterns"]:
        if re.search(pat, name, re.I):
            return f"name matches '{pat}'"
    if prefs.get("shadow_models") == "skip_shadow" and m.get("ShadowModelFor"):
        return f"a shadow model of '{m.get('ShadowModelFor')}', which is sequenced instead"
    if m.get("DisplayAs", "").startswith("Dmx"):
        return "DMX fixture types are not supported yet"
    return None


CHANNELS_PER_NODE = {"RGB Nodes": 3, "RGBW Nodes": 4, "3 Channel RGB": 3, "4 Channel RGBW": 4}


def channel_ranges(elems: dict, counts: dict[str, int]) -> dict[str, tuple[str, int, int]]:
    """name -> (controller, first, last) channel, where StartChannel can be resolved:
    '!Ctrl:N' (controller-relative), '@Model:N' (relative to another model), 'N'."""
    out: dict[str, tuple[str, int, int]] = {}

    def resolve(name, depth=0):
        if name in out or depth > 20:
            return out.get(name)
        m = elems.get(name)
        sc = (m.get("StartChannel") or "").strip() if m is not None else ""
        cpn = CHANNELS_PER_NODE.get(m.get("StringType", "RGB Nodes"), 1 if "Single" in (m.get("StringType") or "") else 3) \
            if m is not None else 3
        start = None
        try:
            if sc.startswith("!") and ":" in sc:
                ctrl, n = sc[1:].rsplit(":", 1)
                start = (ctrl, int(n))
            elif sc.startswith("@") and ":" in sc:
                ref, n = sc[1:].rsplit(":", 1)
                base = resolve(ref, depth + 1)
                if base:
                    start = (base[0], base[1] + int(n) - 1)
            elif sc.startswith(">") and ":" in sc:     # right after another model's last channel
                ref, n = sc[1:].rsplit(":", 1)
                base = resolve(ref, depth + 1)
                if base:
                    start = (base[0], base[2] + int(n))
            elif sc.isdigit():
                start = ("", int(sc))
        except ValueError:
            start = None
        if start is None or counts.get(name, 0) <= 0:
            return None
        out[name] = (start[0], start[1], start[1] + counts[name] * cpn - 1)
        return out[name]

    for n in elems:
        resolve(n)
    return out


NETWORKS_FILE = "xlights_networks.xml"


def read_networks(path: Path) -> list[dict] | None:
    """The controllers of xlights_networks.xml (0.24.32), in file order, each with its absolute
    first channel: xLights numbers the channels of all controllers one after another in the
    order of the file - inactive ones too (they keep their place; an auto-sized one with no
    props holds 1 channel). A controller's size is the sum of its outputs' MaxChannels.
    None when the file isn't there or can't be read."""
    if not path.is_file():
        return None
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return None
    out, start = [], 1
    for c in root.iter("Controller"):
        n = sum(int(x.get("MaxChannels") or 0) for x in c.iter("network"))
        out.append({"name": c.get("Name") or c.get("Id") or "?", "start": start, "channels": n,
                    "active": (c.get("ActiveState") or "Active") != "Inactive",
                    "protocol": c.get("Protocol") or next((x.get("NetworkType") for x in c.iter("network")), "")})
        start += n
    return out


def absolute(rng: tuple[str, int, int], ctrls: list[dict] | None) -> tuple[int, int] | None:
    """A (controller, first, last) range as absolute channels - what an .fseq holds."""
    c, a, b = rng
    if not c:
        return (a, b)
    for x in ctrls or []:
        if x["name"] == c:
            return (x["start"] + a - 1, x["start"] + b - 1)
    return None


def _render_hint(layout: str, prefs: dict) -> str:
    for hint, names in prefs["group_layouts"].items():
        if layout in names:
            return hint
    return "as_one"


def resolve_groups(root, model_names: set[str], prefs: dict) -> list[dict]:
    raw = {}
    for g in root.iter("modelGroup"):
        raw[g.get("name")] = (g, [x.strip() for x in g.get("models", "").split(",") if x.strip()])

    def flatten(name, seen):
        out: list[str] = []
        for x in raw[name][1]:
            base = x.split("/", 1)[0]
            if x in raw and x not in seen:
                out += flatten(x, seen | {x})
            elif base in model_names:
                out.append(base)
        return out

    groups = []
    for name, (g, entries) in raw.items():
        child_groups = [x for x in entries if x in raw]
        subs = [x for x in entries if "/" in x and x.split("/", 1)[0] in model_names]
        direct = [x for x in entries if x in model_names]
        missing = [x for x in entries if x not in raw and x.split("/", 1)[0] not in model_names]
        members = list(dict.fromkeys(flatten(name, {name})))
        if not members:
            kind = "empty"
        elif child_groups:
            kind = "umbrella"
        elif subs and not direct:
            kind = "submodel_view"
        elif len(members) == 1:
            kind = "single"
        elif any(re.search(pat, name) for pat in prefs.get("umbrella_name_patterns", [])):
            kind = "umbrella"                        # 'House-all': a group over the others by name (0.19.9;
        else:                                        # a rule's group_kind still wins)
            kind = "leaf"
        st = {"kind": kind}
        if child_groups:
            st["groups"] = child_groups
        if subs:
            st["submodels"] = subs                   # "Model/Sub" ids, as seqtool names submodels
            st["models"] = direct                    # 0.24.15: the props it lists whole (beside the parts)
        if missing:
            st["missing"] = missing
        groups.append({"id": name, "name": name, "members": members,
                       "render_hint": _render_hint(g.get("layout", ""), prefs),
                       "structure": st,
                       "origin": {"adapter": "xlights", "layout": g.get("layout", "")}})
    return groups


def import_layout(path: Path, pref_dir: Path | None = None) -> dict:
    prefs = load_prefs("xlights", pref_dir)
    root = ET.parse(path).getroot()
    props, report = [], {"uncontrollable": [], "unmapped": [], "missing_group_members": []}
    from . import faces as faces_mod
    raw_faces: dict[str, list[dict]] = {}
    for m in root.iter("model"):
        name = m.get("name")
        if not name:
            continue
        da = m.get("DisplayAs", "")
        shape, tf, semantic = map_model(m, prefs)
        why = _exclusion(m, prefs)
        if shape is None:
            shape, tf = {"type": "points", "params": {"points": [[0.0, 0.0, 0.0]]}}, \
                {"position": [_f(m, "WorldPosX"), _f(m, "WorldPosY"), _f(m, "WorldPosZ")]}
            why = why or f"DisplayAs '{da}' not mapped yet"
            report["unmapped"].append(f"{name} ({da})")
        prop = {"id": name, "name": name, "shape": shape, "transform": tf, "controllable": why is None,
                "origin": {"adapter": "xlights", "DisplayAs": da,
                           **{k: m.get(k) for k in ("parm1", "parm2", "parm3", "StringType", "StartSide", "Dir",
                                                    "LayoutGroup", "Controller", "ShadowModelFor", "Depth")
                              if m.get(k)}}}
        if semantic:
            prop["semantic"] = semantic
        subs = []
        for sm in m.findall("subModel"):
            lines = [sm.get(f"line{i}", "") for i in range(200) if sm.get(f"line{i}") is not None]
            if sm.get("name") and sm.get("type", "ranges") == "ranges" and any(x.strip() for x in lines):
                subs.append({"name": sm.get("name"), "lines": lines, "layout": sm.get("layout", "horizontal")})
        if subs:
            prop["submodels"] = subs                 # node ranges (1-based, xLights wiring order)
        if m.findall("faceInfo"):
            raw_faces[name] = faces_mod.raw_faces(m)
        rb = render_buffer(m, shape)
        if rb:
            prop["render_buffer"] = rb
        if why:
            prop["skip_reason"] = why
            report["uncontrollable"].append(f"{name}: {why}")
        props.append(prop)
    # channel-level relationships: shadow models and colour-order helpers
    elems = {m.get("name"): m for m in root.iter("model") if m.get("name")}
    counts = {}
    for p in props:
        sh = p["shape"]
        if sh["type"] == "points":
            counts[p["id"]] = len(sh["params"]["points"]) if p["controllable"] or p.get("skip_reason") else 0
        else:
            from ...layout.shapes import generate
            try:
                counts[p["id"]] = len(generate(sh["type"], sh.get("params", {})))
            except Exception:
                counts[p["id"]] = 0
    ranges = channel_ranges(elems, counts)
    by_id = {p["id"]: p for p in props}
    if prefs.get("shadow_models", "skip_shadow") == "sequence_shadow":
        for name, m in elems.items():
            if not m.get("ShadowModelFor") or name not in ranges:
                continue
            c, a, b = ranges[name]
            for other, (c2, a2, b2) in ranges.items():
                if other != name and c2 == c and a <= a2 and b2 <= b and by_id[other]["controllable"]:
                    by_id[other]["controllable"] = False
                    by_id[other]["skip_reason"] = (f"its channels are covered by shadow model '{name}', "
                                                    "which is sequenced instead")
                    report["uncontrollable"].append(f"{other}: {by_id[other]['skip_reason']}")
    # models whose start channel follows a shadow model ('>Shadow:1', '@Shadow:1'): shadows too,
    # if you say so (0.20.3, the user's rule: ask first) - xlights.shadow_followers {name: true|false}
    shadows = {n for n, m in elems.items() if m.get("ShadowModelFor")}
    after: dict[str, str] = {}
    grew = True
    while grew:
        grew = False
        for n, m in elems.items():
            sc = (m.get("StartChannel") or "").strip()
            if n in shadows or n in after or sc[:1] not in (">", "@") or ":" not in sc:
                continue
            ref = sc[1:].rsplit(":", 1)[0]
            if ref in shadows or ref in after:
                after[n] = after.get(ref, ref)
                grew = True
    decided = prefs.get("shadow_followers") or {}
    report["shadow_followers"] = []
    for n, root_shadow in sorted(after.items()):
        if n not in by_id:
            continue
        sc = (elems[n].get("StartChannel") or "").strip()
        if decided.get(n) is True:
            if prefs.get("shadow_models", "skip_shadow") == "skip_shadow" and by_id[n]["controllable"]:
                by_id[n]["controllable"] = False
                by_id[n]["skip_reason"] = (f"its start channel follows shadow model '{root_shadow}' ({sc}): "
                                           "treated as a shadow model too (xlights.shadow_followers)")
                report["uncontrollable"].append(f"{n}: {by_id[n]['skip_reason']}")
        elif n not in decided:
            report["shadow_followers"].append({"model": n, "shadow": root_shadow, "start": sc})
    overlaps = []
    live = sorted((r, n) for n, r in ranges.items() if by_id[n]["controllable"])
    for i, ((c, a, b), n) in enumerate(live):
        for (c2, a2, b2), n2 in live[i + 1:]:
            if c2 != c or a2 > b:
                continue
            overlaps.append(f"{n} and {n2} share channels on {c or 'absolute'} {max(a, a2)}-{min(b, b2)}")
    report["channel_overlaps"] = overlaps
    # connected sets of props sharing channels (for one question per set)
    parent: dict[str, str] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            x = parent[x]
        return x
    for i, ((c, a, b), n) in enumerate(live):
        for (c2, a2, b2), n2 in live[i + 1:]:
            if c2 == c and a2 <= b:
                parent[find(n2)] = find(n)
    sets: dict[str, list[str]] = {}
    for n in parent:
        sets.setdefault(find(n), []).append(n)
    report["channel_overlap_sets"] = sorted(sorted(v) for v in sets.values() if len(v) > 1)
    for p in props:
        if p["id"] in ranges:
            c, a, b = ranges[p["id"]]
            p["origin"]["channels"] = f"{c}:{a}-{b}" if c else f"{a}-{b}"
    ctrls = read_networks(path.parent / NETWORKS_FILE)   # 0.24.32: absolute channels, for fseqdump
    if ctrls:
        for p in props:
            ab = absolute(ranges[p["id"]], ctrls) if p["id"] in ranges else None
            if ab:
                p["origin"]["absolute"] = f"{ab[0]}-{ab[1]}"
        report["controllers"] = len(ctrls)
        report["channels_total"] = sum(x["channels"] for x in ctrls)
    # singing faces (0.19): the format is learned from the faces in this layout
    fmt = faces_mod.learn_format([f for fs in raw_faces.values() for f in fs])
    for p in props:
        if p["id"] in raw_faces:
            p["faces"] = [faces_mod.to_generic(f, fmt) for f in raw_faces[p["id"]]]
    report["faces"] = sum(len(v) for v in raw_faces.values())
    names = {p["id"] for p in props}
    groups = resolve_groups(root, names, prefs)
    for g in groups:
        for x in g["structure"].get("missing", []):
            report["missing_group_members"].append(f"{g['name']}: {x}")
    views = {}
    vroot = root.find("views")
    for v in (vroot if vroot is not None else []):
        if v.get("name"):
            views[v.get("name")] = [x.strip() for x in v.get("models", "").split(",") if x.strip()]
    default_view = None
    sroot = root.find("settings")
    for s in (sroot if sroot is not None else []):
        if s.tag == "defaultSeqView":
            default_view = s.get("value")
    sha = file_sha256(path)
    from ...common.canonical import content_sha256
    doc = envelope("seqtool.layout", "seqtool-xlights-import", {"filename": path.name, "sha256": sha},
                   {"layout": sha, "xlights_prefs": content_sha256(prefs)})
    doc["units"] = "xlights"
    doc["props"], doc["groups"] = props, groups
    if fmt.get("types"):
        doc["adapter"] = {"xlights": {"face_format": fmt}}      # opaque to the core, read by the face writer
    if ctrls:
        doc.setdefault("adapter", {}).setdefault("xlights", {})["controllers"] = ctrls
    if views:
        doc["views"] = views
        if default_view in views:
            doc["default_view"] = default_view
    report["models"] = len(props)
    report["controllable"] = sum(p["controllable"] for p in props)
    report["groups"] = len(groups)
    report["group_kinds"] = {k: sum(g["structure"]["kind"] == k for g in groups)
                             for k in ("leaf", "umbrella", "submodel_view", "single", "empty")}
    doc["import_report"] = report
    validate(doc, "seqtool.layout")
    return doc


def review_overlaps(lay: dict, pref_dir: Path | None = None) -> bool:
    """For each set of props sharing controller channels: if the user already
    accepted it, just note it; otherwise warn, and on a terminal ask whether to
    keep all of them or exclude some. Answers are remembered. Returns True when
    exclude_models changed (the layout must be re-imported)."""
    from ...common import config
    from ...common.prompt import ask, interactive
    sets = lay.get("import_report", {}).get("channel_overlap_sets", [])
    accepted = set(config.answer("accepted_channel_overlaps", []))
    changed = False
    for names in sets:
        key = ",".join(names)
        if key in accepted:
            info(f"  channel overlap accepted earlier: {', '.join(names)}")
            continue
        warn(f"  {', '.join(names)} share controller channels")
        if not interactive():
            warn("  (both/all will be sequenced; run interactively or set exclude_models in "
                 f"{config.user_dir()}/xlights.json)")
            continue
        ans = ask("  Keep all of them (different props), or type the name(s) to exclude, comma separated",
                  "keep")
        if ans.lower() in ("keep", "k", "y", "yes"):
            accepted.add(key)
            config.remember("accepted_channel_overlaps", sorted(accepted))
        else:
            excl = [x.strip() for x in ans.split(",") if x.strip() in names]
            if not excl:
                info(f"  '{ans}' matches none of {', '.join(names)}; keeping all (not remembered)")
            if excl:
                cur = config.load("xlights", pref_dir).get("exclude_models", [])
                config.update("xlights", {"exclude_models": sorted(set(cur) | set(excl))}, pref_dir)
                info(f"  excluded {', '.join(excl)} (saved to {config.user_dir()}/xlights.json)")
                changed = True
    return changed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool xlights-import", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rgbeffects", type=paths_arg, help="xlights_rgbeffects.xml from the show folder")
    ap.add_argument("--output", "-o", type=paths_arg, default=None,
                    help="default: xlights_rgbeffects-seqtool/xlights_rgbeffects.layout.json, in a subfolder next to the input")
    ap.add_argument("--preferences", type=paths_arg, default=None)
    a = ap.parse_args(argv)
    from ...common.paths import seqtool_name
    from ...layout.store import find_rgbeffects
    a.rgbeffects = find_rgbeffects(a.rgbeffects)
    a.output = a.output or seqtool_name(a.rgbeffects, "layout")
    doc = import_layout(a.rgbeffects, a.preferences)
    if review_overlaps(doc, a.preferences):
        doc = import_layout(a.rgbeffects, a.preferences)
    write_json(a.output, doc)
    rep = doc["import_report"]
    info(f"  {rep['models']} models ({rep['controllable']} usable), {rep['groups']} groups {rep['group_kinds']}")
    for u in rep["uncontrollable"]:
        info(f"  skipped: {u}")
    for u in rep["missing_group_members"]:
        warn(f"  group member not found: {u}")
    good(f"wrote {a.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
