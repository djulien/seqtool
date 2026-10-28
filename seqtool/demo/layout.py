"""A small generic demo yard: house outline, 4 arches, mega tree, matrix,
spinner, wreath, star, and an uncontrollable moving head. Units: metres."""
from __future__ import annotations

from ..common.envelope import envelope


def prop(id_, shape, params, pos=(0, 0, 0), semantic=None, rot=0.0, controllable=True):
    p = {"id": id_, "name": id_, "shape": {"type": shape, "params": params},
         "transform": {"position": list(map(float, pos)), "rotation_deg": [0.0, float(rot), 0.0]},
         "controllable": controllable, "origin": {"adapter": "demo"}}
    if semantic:
        p["semantic"] = semantic
    return p


def demo_layout(with_semantics: bool = True) -> dict:
    s = (lambda x: x) if with_semantics else (lambda x: None)
    doc = envelope("seqtool.layout", "seqtool-demo", {"tool": "demo"})
    doc["units"] = "m"
    doc["props"] = [
        prop("Roofline", "polyline", {"points": [[0, 4], [5, 7], [10, 4]], "nodes": 300},
             pos=(0, 0, -2), semantic=s("roofline")),
        *[prop(f"Arch{i}", "arc", {"width": 2.0, "height": 1.0, "nodes": 50},
               pos=(1 + 2.2 * (i - 1), 0, 2), semantic=s("arch")) for i in range(1, 5)],
        prop("MegaTree", "cone", {"base_diameter": 2.5, "top_diameter": 0.1, "height": 5.0,
                                  "strings": 16, "nodes_per_string": 100},
             pos=(13, 0, 0), semantic=s("tree")),
        prop("Matrix", "grid", {"width": 2.0, "height": 1.0, "columns": 64, "rows": 32},
             pos=(4, 1.5, -1.9), semantic=s("matrix")),
        prop("Spinner", "radial", {"diameter": 1.5, "hollow": 0.1, "arms": 16, "nodes_per_arm": 30},
             pos=(-2, 2.5, 0), semantic=s("spinner")),
        prop("Wreath", "ring", {"diameter": 0.9, "nodes": 120}, pos=(5, 5, -1.9),
             semantic=s("wreath")),
        prop("Star", "star", {"diameter": 1.0, "points": 5, "ratio": 0.45, "nodes": 150},
             pos=(13, 5.6, 0), semantic=s("star")),
        prop("MovingHead", "points", {"points": [[0, 0, 0]]}, pos=(8, 0, 3),
             semantic=s("moving_head"), controllable=False),
    ]
    doc["groups"] = [{"id": "Arches", "name": "Arches", "render_hint": "per_prop",
                      "members": ["Arch1", "Arch2", "Arch3", "Arch4"]}]
    return doc
