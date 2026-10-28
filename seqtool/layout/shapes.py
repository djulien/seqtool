"""Generic parametric prop shapes -> approximate node point clouds.

This is the toolchain's answer to "we don't have xLights' node coordinates":
every producer (xLights importer, the interactive prop wizard, a future
photo-based estimator) describes a prop as one of these generic shapes, and
this single module turns that into points. Node ORDER follows the physical
string where that's meaningful (lines, arcs, rings, spokes), which the
geometry analyzer uses for path/loop/curvature features.

Units are arbitrary but consistent within a layout (layout.units).
Local frame: x = right, y = up, z = toward viewer; shapes sit on y=0 or
are centred at the origin as noted.
"""
from __future__ import annotations

import math

import numpy as np

SHAPES: dict[str, dict] = {
    # name: {param: (default, help)}
    "line": {"length": (3.0, "length"), "nodes": (50, "node count")},
    "polyline": {"points": (None, "vertex list [[x,y,z],...]"), "nodes": (100, "node count")},
    "arc": {"width": (2.0, "base width"), "height": (1.0, "peak height"), "nodes": (50, "node count")},
    "ring": {"diameter": (1.0, "diameter"), "degrees": (360.0, "arc coverage in degrees"),
             "nodes": (100, "node count")},
    "grid": {"width": (2.0, "width"), "height": (1.0, "height"), "columns": (32, "columns"),
             "rows": (16, "rows")},
    "cone": {"base_diameter": (2.0, "base diameter"), "top_diameter": (0.1, "top diameter"),
             "height": (4.0, "height"), "strings": (16, "vertical strings"),
             "nodes_per_string": (50, "nodes per string"), "degrees": (360.0, "coverage (180 = flat-back)")},
    "flat_tree": {"base_width": (2.0, "base width"), "height": (3.0, "height"),
                  "strings": (16, "strings"), "nodes_per_string": (50, "nodes per string")},
    "radial": {"diameter": (1.5, "outer diameter"), "hollow": (0.1, "inner diameter / outer (0..1)"),
               "arms": (12, "arms/spokes"), "nodes_per_arm": (25, "nodes per arm"),
               "degrees": (360.0, "coverage")},
    "star": {"diameter": (1.0, "outer diameter"), "ratio": (0.4, "inner/outer radius"),
             "points": (5, "star points"), "nodes": (100, "node count"), "layers": (1, "concentric outlines")},
    "volume": {"width": (1.0, "width"), "height": (1.0, "height"), "depth": (1.0, "depth"),
               "columns": (10, "x count"), "rows": (10, "y count"), "layers": (10, "z count")},
    "points": {"points": (None, "explicit node coordinates [[x,y,z],...]")},
}


def _resample_path(verts: np.ndarray, n: int) -> np.ndarray:
    seg = np.linalg.norm(np.diff(verts, axis=0), axis=1)
    cum = np.concatenate([[0], np.cumsum(seg)])
    if cum[-1] == 0 or n < 2:
        return np.repeat(verts[:1], max(n, 1), axis=0)
    t = np.linspace(0, cum[-1], n)
    return np.stack([np.interp(t, cum, verts[:, k]) for k in range(3)], axis=1)


def _p(params: dict, shape: str, key: str):
    v = params.get(key)
    return SHAPES[shape][key][0] if v is None else v


def generate(shape: str, params: dict) -> np.ndarray:
    """Return an (N, 3) float array of node positions in local coordinates."""
    g = lambda k: _p(params, shape, k)  # noqa: E731
    if shape == "line":
        n, L = int(g("nodes")), float(g("length"))
        return np.stack([np.linspace(0, L, n), np.zeros(n), np.zeros(n)], axis=1)
    if shape == "polyline":
        verts = np.asarray(g("points"), dtype=float)
        if verts.shape[1] == 2:
            verts = np.hstack([verts, np.zeros((len(verts), 1))])
        return _resample_path(verts, int(g("nodes")))
    if shape == "arc":
        n, w, h = int(g("nodes")), float(g("width")), float(g("height"))
        a = np.linspace(math.pi, 0, n)
        return np.stack([w / 2 * (1 + np.cos(a)), h * np.sin(a), np.zeros(n)], axis=1)
    if shape == "ring":
        n, r = int(g("nodes")), float(g("diameter")) / 2
        deg = float(g("degrees"))
        a = np.radians(90 - np.linspace(0, deg, n, endpoint=deg < 360))
        return np.stack([r * np.cos(a), r * np.sin(a), np.zeros(n)], axis=1)
    if shape == "grid":
        c, r = int(g("columns")), int(g("rows"))
        xs, ys = np.linspace(0, g("width"), c), np.linspace(g("height"), 0, r)
        pts = [(x, ys[j] if i % 2 == 0 else ys[r - 1 - j], 0.0)  # serpentine column wiring
               for i, x in enumerate(xs) for j in range(r)]
        return np.asarray(pts, dtype=float)
    if shape in ("cone", "flat_tree"):
        s, k = int(g("strings")), int(g("nodes_per_string"))
        h = float(g("height"))
        if shape == "flat_tree":
            rb, rt, deg, flat = float(g("base_width")) / 2, 0.0, 180.0, True
        else:
            rb, rt = float(g("base_diameter")) / 2, float(g("top_diameter")) / 2
            deg, flat = float(g("degrees")), False
        pts = []
        for i in range(s):
            frac = i / s if deg >= 360 else i / max(s - 1, 1)
            a = math.radians(-deg / 2 + deg * frac) if deg < 360 else 2 * math.pi * frac
            for j in range(k):
                t = j / max(k - 1, 1)              # 0 = top, 1 = bottom (strings hang down)
                rad = rt + (rb - rt) * t
                y = h * (1 - t)
                if flat:
                    pts.append((rad * (2 * frac - 1), y, 0.0))
                else:
                    pts.append((rad * math.sin(a), y, rad * math.cos(a)))
        return np.asarray(pts, dtype=float)
    if shape == "radial":
        arms, k = int(g("arms")), int(g("nodes_per_arm"))
        R = float(g("diameter")) / 2
        r0 = R * float(g("hollow"))
        deg = float(g("degrees"))
        pts = []
        for i in range(arms):
            a = math.radians(90 - deg * i / (arms if deg >= 360 else max(arms - 1, 1)))
            for j in range(k):
                rr = r0 + (R - r0) * j / max(k - 1, 1)
                pts.append((rr * math.cos(a), rr * math.sin(a), 0.0))
        return np.asarray(pts, dtype=float)
    if shape == "star":
        P, R = int(g("points")), float(g("diameter")) / 2
        ratio, n, layers = float(g("ratio")), int(g("nodes")), int(g("layers"))
        out = []
        for L in range(layers):
            scale = 1 - L / max(layers, 1) * 0.6
            verts = []
            for i in range(2 * P + 1):
                rr = R * scale * (1 if i % 2 == 0 else ratio)
                a = math.pi / 2 + math.pi * i / P
                verts.append((rr * math.cos(a), rr * math.sin(a), 0.0))
            out.append(_resample_path(np.asarray(verts), max(n // layers, 3)))
        return np.vstack(out)
    if shape == "volume":
        xs = np.linspace(0, g("width"), int(g("columns")))
        ys = np.linspace(0, g("height"), int(g("rows")))
        zs = np.linspace(0, g("depth"), int(g("layers")))
        return np.asarray([(x, y, z) for z in zs for x in xs for y in ys], dtype=float)
    if shape == "points":
        p = np.asarray(g("points"), dtype=float)
        return np.hstack([p, np.zeros((len(p), 1))]) if p.shape[1] == 2 else p
    raise ValueError(f"unknown shape {shape!r}")


def transform(points: np.ndarray, tf: dict | None) -> np.ndarray:
    """Optionally centre (anchor="center"), then scale -> rotate (X, then Y,
    then Z, degrees) -> translate."""
    if not tf:
        return points
    p = points
    if tf.get("anchor") == "center" and len(p):
        p = p - (p.min(axis=0) + p.max(axis=0)) / 2
    p = p * np.asarray(tf.get("scale", [1, 1, 1]), dtype=float)
    rx, ry, rz = np.radians(tf.get("rotation_deg", [0, 0, 0]))
    Rx = np.array([[1, 0, 0], [0, math.cos(rx), -math.sin(rx)], [0, math.sin(rx), math.cos(rx)]])
    Ry = np.array([[math.cos(ry), 0, math.sin(ry)], [0, 1, 0], [-math.sin(ry), 0, math.cos(ry)]])
    Rz = np.array([[math.cos(rz), -math.sin(rz), 0], [math.sin(rz), math.cos(rz), 0], [0, 0, 1]])
    p = p @ (Rz @ Ry @ Rx).T
    return p + np.asarray(tf.get("position", [0, 0, 0]), dtype=float)


def prop_points(prop: dict) -> np.ndarray:
    return transform(generate(prop["shape"]["type"], prop["shape"].get("params", {})),
                     prop.get("transform"))
