# seqtool-command: submodel | main | setup | submodels seqtool makes in your layout: submodel angles Spinner1 --write (clock positions)
"""seqtool submodel angles TARGET [--count 12] [--width DEG] [--write [--yes]] | submodel angles TARGET --remove

Clock-position submodels for round props (0.24.49): for each prop in TARGET (a prop or a
group - its round props), one submodel per position - 'seqtool-12oclock', 'seqtool-1oclock' ...
holding the prop's lights in that direction from its centre (within --width degrees, default
360/count), listed from the centre out, so an effect along it runs hub to tip. A choreography
step plays on one with "target": "/seqtool-10oclock" (that submodel of each prop it plays on);
a pin or react: 'Spinner1/seqtool-10oclock'.

    submodel angles "Spinners"            what would be made (nothing is written)
    submodel angles "Spinners" --write    into xlights_rgbeffects.xml (xLights closed; a copy of
                                                 the file is kept first in seqtool-backups/); the stored
                                                 layout is read again
    submodel angles Spinner1 --count 16 --width 20 --write
    submodel angles Spinner1 --remove --write   take seqtool's angle submodels out again

How a submodel is written is learned from the submodels already in your file (one of the
'ranges' kind - the same attributes, the name and one line of node ranges changed); a prop's
lights come from its node positions in the layout (custom models). 12 o'clock is up.
"""
from __future__ import annotations

import argparse
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import quoteattr

from ...common.log import good, info, warn

PREFIX = "seqtool-"


def clock_name(k: int, count: int) -> str:
    h = k * 12 / count
    h = 12 if abs(h) < 1e-9 else h
    return f"{PREFIX}{h:g}oclock".replace(".", "_")


def sectors(points: list, count: int, width: float) -> list[list[int]]:
    """Node numbers (1-based) per clock position, each from the centre out."""
    if not points:
        return []
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    pol = []
    for i, p in enumerate(points):
        dx, dy = p[0] - cx, p[1] - cy
        pol.append((i + 1, math.hypot(dx, dy), math.degrees(math.atan2(dx, dy)) % 360))
    rmax = max(r for _, r, _ in pol) or 1.0
    out = []
    for k in range(count):
        c = k * 360 / count
        hit = [(r, n) for n, r, ang in pol
               if r < 0.08 * rmax or min(abs(ang - c), 360 - abs(ang - c)) <= width / 2]
        out.append([n for _, n in sorted(hit)])
    return out


def ranges(nodes: list[int]) -> str:
    """[1, 2, 3, 9, 8] -> '1-3,9,8' (only rising runs are joined - the order is kept)."""
    out, i = [], 0
    while i < len(nodes):
        j = i
        while j + 1 < len(nodes) and nodes[j + 1] == nodes[j] + 1:
            j += 1
        out.append(str(nodes[i]) if j == i else f"{nodes[i]}-{nodes[j]}")
        i = j + 1
    return ",".join(out)


def template(root: ET.Element) -> dict | None:
    """The attributes of a 'ranges' submodel in the file, in their order (the first found)."""
    for sm in root.iter("subModel"):
        if sm.get("type") == "ranges" and any(k.startswith("line") for k in sm.attrib):
            return dict(sm.attrib)
    return None


def snippet(tmpl: dict, name: str, nodes: list[int]) -> str:
    attrs, done = [], False
    for k, v in tmpl.items():
        if k == "name":
            v = name
        elif re.fullmatch(r"line\d+", k):
            if done:
                continue
            k, v, done = "line0", ranges(nodes), True
        attrs.append(f"{k}={quoteattr(v)}")
    return "<subModel " + " ".join(attrs) + "/>"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool submodel", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("angles",))
    ap.add_argument("target", nargs="+", help="a prop or a group")
    ap.add_argument("--count", type=int, default=12, help="how many positions round the clock (default 12)")
    ap.add_argument("--width", type=float, default=None, help="degrees each one takes in (default 360/count)")
    ap.add_argument("--write", action="store_true", help="write them into xlights_rgbeffects.xml")
    ap.add_argument("--remove", action="store_true", help="take seqtool's angle submodels out")
    ap.add_argument("--yes", action="store_true", help="--write: don't ask whether xLights is closed")
    a = ap.parse_args(argv)
    from ...common.canonical import read_json
    from ...layout import store
    from ...faces.cmd import _confirm, _reread, _rgbeffects
    from . import write_faces as wf
    name = " ".join(a.target)
    lay = read_json(store.folder() / "layout.json")
    ms = read_json(store.folder() / "layout.models.json")["models"]
    by = {m["id"].lower(): m for m in ms}
    t = by.get(name.lower())
    if t is None:
        from ...common.suggest import suggest
        raise SystemExit(f"submodel angles: no prop or group '{name}'" + suggest(name, [m["id"] for m in ms]))
    def leaves(m, seen=()):
        if m["kind"] != "group":
            return [m]
        out = []
        for x in m.get("members", []):
            mm = by.get(x.lower())
            if mm and mm["id"] not in seen:
                out += leaves(mm, seen + (m["id"],))
        return out
    props = [m for m in leaves(t) if m["kind"] == "model"]
    if t["kind"] == "group":
        props = [m for m in props if m.get("geometry_class") in ("RADIAL", "RING", "STAR")]
    if not props:
        raise SystemExit(f"submodel angles: {name} has no round props (spinners, wreaths, stars)")
    shapes = {p["id"]: p for p in lay.get("props", [])}
    count = max(2, a.count)
    width = a.width or 360 / count
    path = _rgbeffects()
    text = wf.load(path)
    tmpl = template(ET.fromstring(text.encode("utf-8")))
    if tmpl is None and not a.remove:
        raise SystemExit(f"{path.name} has no submodel to learn the form from - make any submodel (Node Ranges) "
                         "on a prop in xLights first, then 'layout' and this again")
    plan = []
    for p in sorted({m["id"]: m for m in props}.values(), key=lambda m: m["id"]):
        pts = ((shapes.get(p["id"]) or {}).get("shape") or {}).get("params", {}).get("points") or []
        if not pts and not a.remove:
            warn(f"  {p['id']}: no node positions in the layout (not a custom model) - left out")
            continue
        secs = sectors(pts, count, width) if not a.remove else []
        sn = [snippet(tmpl, clock_name(k, count), nodes) for k, nodes in enumerate(secs) if nodes]
        plan.append((p["id"], sn, [len(x) for x in secs]))
        if not a.write:
            info(f"  {p['id']}: " + ("remove its seqtool- submodels" if a.remove else
                 ", ".join(f"{clock_name(k, count)[len(PREFIX):]} {len(x)}" for k, x in enumerate(secs)) + " lights"))
    if not a.write:
        info("{note}nothing written - add --write (with xLights closed) to put them into "
             f"{path.name}{{/}}")
        return 0
    new = text
    for pid, sn, _ in plan:
        try:
            new, _ = wf.put_children(new, pid, "subModel", sn, PREFIX)
        except LookupError as e:
            warn(f"  {pid}: {e}")
    if new == text:
        info("nothing to change")
        return 0
    _confirm(("take seqtool's angle submodels out of " if a.remove else f"put {count} angle submodels on "
              f"{len(plan)} prop(s) into ") + str(path.name), a.yes)
    try:
        copy = wf.save(path, new)
    except ValueError as e:
        raise SystemExit(str(e))
    good(("removed seqtool's angle submodels" if a.remove else f"{len(plan)} prop(s) have {count} angle submodels")
         + f" in {path.name}; the old file is kept as {copy.name} (in seqtool-backups)")
    _reread(path)
    if not a.remove:
        info(f"  {{note}}a choreography step: \"target\": \"/{clock_name(count * 10 // 12, count)}\"; "
             f"a pin: 'pin {plan[0][0]}/{clock_name(count * 10 // 12, count)} @#3 pulse'{{/}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
