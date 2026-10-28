# seqtool-command: prop-wizard | main | setup | no xLights layout? describe your props by answering questions: prop-wizard my-yard.json
"""seqtool prop-wizard my-yard.json - a yard described by answering questions.

For a show WITHOUT an xLights layout (another sequencer, or props not drawn
in xLights yet): it asks for one prop at a time - its name, what it looks
like (line, arch, wreath, matrix, tree, spinner, star ...), its size, how
many lights and where it stands - and writes (or extends) a seqtool layout
file. Then:  run --audio SONG --layout my-yard.json

With xLights you don't need it: 'layout SHOWFOLDER' reads your
xlights_rgbeffects.xml directly (props, groups, faces, positions).

    prop-wizard my-yard.json                  new file, or add props to it
    prop-wizard                               add props to the stored layout (asks first
                                              when it comes from xLights: the next 'layout'
                                              asks whether to keep them)
    prop-wizard my-yard.json --script FILE    the answers from a file, one per line
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from ..common.canonical import read_json, write_json
from ..common.envelope import envelope
from ..common.schemas import validate
from .shapes import SHAPES
from ..common.paths import arg as paths_arg

MENU = [  # (label, shape, semantic)
    ("Straight line / roofline / fence", "line", "roofline"),
    ("Multi-segment outline (polyline)", "polyline", "outline"),
    ("Arch", "arc", "arch"),
    ("Circle / wreath / ring", "ring", "wreath"),
    ("Matrix / pixel panel (grid)", "grid", "matrix"),
    ("Mega tree / cone tree", "cone", "tree"),
    ("Flat tree (triangle)", "flat_tree", "tree"),
    ("Spinner / sunburst (spokes)", "radial", "spinner"),
    ("Star (outline)", "star", "star"),
    ("3-D cube / volume", "volume", "cube"),
]


class Asker:
    def __init__(self, scripted: list[str] | None = None):
        self.scripted = scripted

    def __call__(self, prompt: str, default=None) -> str:
        shown = f"{prompt}" + (f" [{default}]" if default is not None else "") + ": "
        if self.scripted is not None:
            ans = self.scripted.pop(0) if self.scripted else ""
            print(shown + ans, file=sys.stderr)
        else:
            from ..common.prompt import ask
            ans = ask(shown.rstrip(": ").rstrip(), "", show_default=False)
        ans = ans.strip()
        return str(default) if ans == "" and default is not None else ans


def _num(s: str, default):
    try:
        return int(s) if isinstance(default, int) and re.fullmatch(r"-?\d+", s) else float(s)
    except ValueError:
        return default


def ask_prop(ask: Asker, existing_ids: set[str]) -> dict | None:
    name = ask("Prop name (blank to finish)")
    if not name:
        return None
    for i, (label, _, _) in enumerate(MENU, 1):
        print(f"  {i:2d}. {label}", file=sys.stderr)
    choice = _num(ask("Shape number", 1), 1)
    _, shape, semantic = MENU[max(1, min(len(MENU), int(choice))) - 1]
    params = {}
    for key, (default, helptext) in SHAPES[shape].items():
        if key == "points":
            raw = ask("Vertices as x,y;x,y;... (e.g. 0,0;3,0;3,1)", "0,0;3,0")
            params[key] = [[float(v) for v in pt.split(",")] for pt in raw.split(";") if pt]
        else:
            params[key] = _num(ask(f"  {helptext}", default), default)
    pos = ask("Position x,y,z (same units as layout)", "0,0,0")
    rot = ask("Rotation about vertical axis, degrees", 0)
    pid = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
    while pid in existing_ids:
        pid += "_"
    return {"id": pid, "name": name, "shape": {"type": shape, "params": params},
            "transform": {"position": [float(v) for v in pos.split(",")][:3] + [0.0] * (3 - len(pos.split(","))),
                          "rotation_deg": [0.0, float(rot), 0.0]},
            "semantic": semantic, "controllable": True, "origin": {"adapter": "wizard"}}


def add_to_store(scripted: list[str] | None = None) -> int:
    """Props asked for one by one, added to the stored layout (origin 'wizard'), which is
    analysed again (0.20.2)."""
    from . import store
    from ..models.analyze import analyze as analyze_models
    d = store.folder()
    doc = read_json(d / "layout.json")
    ask = Asker(scripted)
    if doc.get("units") == "xlights":
        print("positions are in xLights' own coordinates (as in its Layout tab: X, Y, Z)", file=sys.stderr)
    ids = {p["id"] for p in doc["props"]}
    n = 0
    while (prop := ask_prop(ask, ids)) is not None:
        doc["props"].append(prop)
        ids.add(prop["id"])
        n += 1
        grp = ask("Add to group (name, blank for none)", "")
        if grp:
            g = next((g for g in doc["groups"] if g["name"] == grp), None)
            if g is None:
                g = {"id": re.sub(r"[^A-Za-z0-9_.-]+", "_", grp), "name": grp, "members": [],
                     "render_hint": "per_prop", "origin": {"adapter": "wizard"}}
                doc["groups"].append(g)
            g["members"].append(prop["id"])
    if n:
        validate(doc, "seqtool.layout")
        write_json(d / "layout.json", doc)
        write_json(d / "layout.models.json", analyze_models(doc, "layout.json"))
    return n


def run(path: Path, scripted: list[str] | None = None) -> dict:
    ask = Asker(scripted)
    if path.exists():
        doc = read_json(path)
    else:
        doc = envelope("seqtool.layout", "seqtool-prop-wizard", {"tool": "prop-wizard"})
        doc["units"] = ask("Units (m, ft, in)", "m")
        doc["props"], doc["groups"] = [], []
    ids = {p["id"] for p in doc["props"]}
    while (prop := ask_prop(ask, ids)) is not None:
        doc["props"].append(prop)
        ids.add(prop["id"])
        grp = ask("Add to group (name, blank for none)", "")
        if grp:
            g = next((g for g in doc["groups"] if g["name"] == grp), None)
            if g is None:
                g = {"id": re.sub(r"[^A-Za-z0-9_.-]+", "_", grp), "name": grp, "members": [],
                     "render_hint": "per_prop"}
                doc["groups"].append(g)
            g["members"].append(prop["id"])
    validate(doc, "seqtool.layout")
    write_json(path, doc)
    print(f"wrote {path}: {len(doc['props'])} props, {len(doc['groups'])} groups", file=sys.stderr)
    return doc


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="seqtool prop-wizard", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("layout", type=paths_arg, nargs="?", help="a seqtool layout .json to make or extend "
                    "(default: the stored layout)")
    ap.add_argument("--script", type=paths_arg, help="file of answers, one per line")
    a = ap.parse_args(argv)
    from . import store
    from ..common.prompt import ask as _ask
    src = store.source_info()
    xl = bool(src) and str(src.get("path", "")).lower().endswith(".xml")
    if a.layout is None:
        if not src:
            raise SystemExit("no layout stored yet - give a file to make: 'prop-wizard my-yard.json' "
                             "(or, with xLights, 'layout ~/xLights/show')")
        if xl and _ask(f"the stored layout comes from xLights ({src['path']}). Props you add here aren't in "
                       "xLights: the next 'layout' asks whether to keep them, and xLights won't know them (an "
                       "export writes no rows for them). Add props anyway? [y/N]", "n",
                       show_default=False).lower() not in ("y", "yes"):
            print("nothing added - add props in xLights, then 'layout' again")
            return 0
        scripted = a.script.read_text().splitlines() if a.script else None
        n = add_to_store(scripted)
        print(f"{n} prop(s) added to the stored layout - 'models' lists them, 'run' uses them")
        return 0
    if xl and not Path(a.layout).exists() and Path(a.layout).suffix.lower() == ".json" and \
            _ask(f"an xLights layout is stored ({src['path']}) and 'run' uses it; {a.layout} will be a separate "
                 f"layout, used only with 'run --layout {a.layout}' - continue? [y/N]", "n",
                 show_default=False).lower() not in ("y", "yes"):
        print("nothing written - 'prop-wizard' (no file) adds props to the stored layout instead")
        return 0
    if Path(a.layout).suffix.lower() == ".xml" or Path(a.layout).is_dir():
        raise SystemExit(f"prop-wizard writes a seqtool layout (.json) by asking about each prop - for an xLights "
                         f"layout use 'layout {a.layout}' instead, which reads it as it is "
                         "(e.g. 'layout ~/xLights/show')")
    scripted = a.script.read_text().splitlines() if a.script else None
    run(a.layout, scripted)
    return 0
