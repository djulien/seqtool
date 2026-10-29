"""Geometry feature extraction from an (N,3) node point cloud.

All features are deterministic. Large props are subsampled with a fixed stride
for the O(N^2) neighbour features. Node ORDER is assumed to follow the wiring
path (true for every shape generator and for xLights' own node order), which
gives path count, closed-loop and curvature cheaply.
"""
from __future__ import annotations

import math

import numpy as np

MAX_NN_POINTS = 1500


def _clip(x: float) -> float:
    return float(min(1.0, max(0.0, x)))


def _nn_dist(P: np.ndarray) -> np.ndarray:
    """Nearest-neighbour distance per point (brute force, chunked)."""
    out = np.empty(len(P))
    for i in range(0, len(P), 512):
        d = np.linalg.norm(P[i:i + 512, None, :] - P[None, :, :], axis=2)
        d[np.arange(d.shape[0]), np.arange(i, i + d.shape[0])] = np.inf
        out[i:i + 512] = d.min(axis=1)
    return out


def _subsample(P: np.ndarray) -> np.ndarray:
    if len(P) <= MAX_NN_POINTS:
        return P
    return P[:: math.ceil(len(P) / MAX_NN_POINTS)]


def _mirror_match(Q: np.ndarray, M: np.ndarray, tol: float) -> float:
    """Share of the mirrored points M that land on a point of Q. Estimated on at most 400
    of them (0.20.2: a big layout took a minute; the share hardly moves)."""
    if len(M) > 400:
        M = M[:: math.ceil(len(M) / 400)]
    d = np.empty(len(M))
    for i in range(0, len(M), 512):
        d[i:i + 512] = np.linalg.norm(M[i:i + 512, None, :] - Q[None, :, :], axis=2).min(axis=1)
    return float((d <= tol).mean())


def features(P: np.ndarray) -> dict:
    P = np.asarray(P, dtype=float)
    n = len(P)
    f: dict = {"node_count": int(n)}
    if n < 2:
        f.update(dimensions=0, bounds={"width": 0.0, "height": 0.0, "depth": 0.0}, density=0.0)
        return f
    lo, hi = P.min(axis=0), P.max(axis=0)
    w, h, d = (hi - lo).tolist()
    f["bounds"] = {"width": w, "height": h, "depth": d}
    big = max(w, h, d) or 1.0
    f["aspect_ratio"] = (w / h) if h > 1e-9 else 1e6 if w > 0 else 1.0
    f["horizontal_extent"] = _clip(w / (w + h)) if w + h > 0 else 0.5
    f["depth_ratio"] = _clip(d / max(w, h, 1e-9))

    # --- PCA dimensionality
    C = P - P.mean(axis=0)
    ev = np.sort(np.linalg.eigvalsh(C.T @ C / n))[::-1]
    ev = np.maximum(ev, 0)
    l1 = ev[0] or 1e-12
    f["linearity"] = _clip((ev[0] - ev[1]) / l1)
    f["planarity"] = _clip((ev[1] - ev[2]) / l1)
    f["scattering"] = _clip(ev[2] / l1)
    f["dimensions"] = 1 if ev[1] / l1 < 0.003 else (2 if ev[2] / l1 < 0.01 else 3)

    # --- path topology from node order
    steps = np.linalg.norm(np.diff(P, axis=0), axis=1)
    m = float(np.median(steps[steps > 0])) if np.any(steps > 0) else 1e-9
    f["node_spacing"] = m
    breaks = np.where(steps > 3 * m)[0]
    f["path_count"] = int(len(breaks) + 1)
    bounds_idx = np.concatenate([[0], breaks + 1, [n]])
    turn_abs = turn_signed = 0.0
    longest = 0
    vert = []
    for a, b in zip(bounds_idx[:-1], bounds_idx[1:]):
        seg = P[a:b]
        longest = max(longest, len(seg))
        if len(seg) >= 3:
            e = seg[-1] - seg[0]
            if np.linalg.norm(e) > 0:
                vert.append(abs(e[1]) / np.linalg.norm(e) > 0.85)
        if len(seg) < 3:
            continue
        v = np.diff(seg, axis=0)
        v = v[np.linalg.norm(v, axis=1) > 0]
        if len(v) < 2:
            continue
        v2 = v[:, :2] if f["depth_ratio"] < 0.2 else v
        nv = np.linalg.norm(v2, axis=1)
        v2 = v2[nv > 0]
        if len(v2) < 2:
            continue
        u = v2 / np.linalg.norm(v2, axis=1, keepdims=True)
        cos = np.clip((u[:-1] * u[1:]).sum(axis=1), -1, 1)
        ang = np.arccos(cos)
        turn_abs += float(ang.sum())
        if v2.shape[1] == 2:
            cross = u[:-1, 0] * u[1:, 1] - u[:-1, 1] * u[1:, 0]
            turn_signed += float((np.sign(cross) * ang).sum())
    f["curvature"] = _clip(turn_abs / (2 * math.pi * f["path_count"]))
    f["path_verticality"] = float(np.mean(vert)) if vert else 0.0
    end_gap = float(np.linalg.norm(P[-1] - P[0]))
    f["closed_loop"] = _clip(1 - (end_gap - m) / (5 * m)) if f["path_count"] == 1 else 0.0

    # --- 2-D analysis in the best-fit plane (PCA), so props lying flat or rotated
    #     (floor tiles, angled panels) are analysed face-on. For an upright prop
    #     facing the viewer this is the ordinary x/y plane.
    evals, evecs = np.linalg.eigh(C.T @ C / n)
    order = np.argsort(evals)[::-1]
    axes = evecs[:, order[:2]]
    if f["dimensions"] >= 2 and abs(evecs[:, order[2]][2]) > 0.9:
        axes = np.eye(3)[:, :2]                      # facing the viewer: keep world x/y
    xyP = C @ axes
    c = (xyP.min(axis=0) + xyP.max(axis=0)) / 2
    rP = np.linalg.norm(xyP - c, axis=1)
    rmax = float(rP.max()) or 1e-9
    f["center_density"] = float((rP < 0.3 * rmax).mean())
    f["perimeter_density"] = float((rP > 0.8 * rmax).mean())
    f["radius_cv"] = float(rP.std() / (rP.mean() or 1e-9))
    far = rP > 0.2 * rmax
    ang = np.degrees(np.arctan2(*(xyP[far] - c).T[::-1])) % 360
    coverage = len(np.unique((ang // 10).astype(int))) / 36 if len(ang) else 0.0
    f["angular_coverage"] = coverage
    # local wiring direction vs radius vector (spokes -> 1, rings -> 0); path breaks masked
    dirs = np.zeros_like(xyP)
    fwd = np.diff(xyP, axis=0)
    good_step = np.linalg.norm(np.diff(P, axis=0), axis=1) <= 3 * m
    dirs[:-1][good_step] += fwd[good_step]
    dirs[1:][good_step] += fwd[good_step]
    rv = xyP - c
    nd, nr = np.linalg.norm(dirs, axis=1), np.linalg.norm(rv, axis=1)
    ok = (nd > 0) & (nr > 0.2 * rmax)
    align = float(np.abs((dirs[ok] * rv[ok]).sum(axis=1) / (nd[ok] * nr[ok])).mean()) if ok.any() else 0.0
    f["radial_alignment"] = align
    f["radialness"] = _clip((align - 0.64) / 0.36) * min(1.0, coverage / 0.3)
    # taper: top-band width vs bottom-band width (trees, cones, triangles)
    y = P[:, 1]
    if h > 0:
        top, bot = P[y >= hi[1] - 0.2 * h], P[y <= lo[1] + 0.2 * h]
        tw = float(np.ptp(top[:, [0, 2]], axis=0).max()) if len(top) else 0.0
        bw = float(np.ptp(bot[:, [0, 2]], axis=0).max()) if len(bot) else 0.0
        f["taper"] = _clip(tw / bw) if bw > 0 else 1.0
    else:
        f["taper"] = 1.0
    Q = _subsample(P)
    xy = _subsample(xyP)

    # --- density: occupied cells in the 2-D bounding box at ~2x node spacing
    nn = _nn_dist(Q)
    span = xy.max(axis=0) - xy.min(axis=0)
    pos = nn[nn > 0]                                   # 0.24.58: nodes on top of each other don't make the
    cell = 2 * float(np.median(pos)) if len(pos) else 0.0   # grid microscopic (an int overflow on Windows)
    cell = max(cell, float(span.max()) / 2000.0, 1e-9)
    gx, gy = (int(min(4000, max(1, math.ceil(float(v) / cell)))) for v in span)
    ij = np.floor((xy - xy.min(axis=0)) / cell).astype(np.int64)
    ij = np.minimum(ij, [gx - 1, gy - 1])
    f["density"] = _clip(len({(int(a), int(b)) for a, b in ij}) / float(gx * gy))

    # --- symmetry (mirror / rotation about centre) at tolerance ~1.5 spacing
    tol = cell + 1e-9
    f["horizontal_symmetry"] = _mirror_match(xy, np.c_[2 * c[0] - xy[:, 0], xy[:, 1]], tol)
    f["vertical_symmetry"] = _mirror_match(xy, np.c_[xy[:, 0], 2 * c[1] - xy[:, 1]], tol)
    best = 0.0
    for k in (3, 4, 5, 6, 8, 12):
        a = 2 * math.pi / k
        R = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        best = max(best, _mirror_match(xy, (xy - c) @ R.T + c, tol))
    f["radial_symmetry"] = best
    return f


def classify(f: dict, semantic: str | None) -> tuple[str, str, str]:
    """Return (geometry_class, source, geometric_guess)."""
    if f.get("dimensions", 0) == 0:
        guess = "POINT"
    elif f["path_count"] >= 6 and f["taper"] < 0.5 and f["curvature"] < 0.1 \
            and f.get("path_verticality", 0) >= 0.6:
        guess = "CONE"
    elif f["dimensions"] == 3 and f["depth_ratio"] > 0.4 and f["path_count"] > 4:
        guess = "VOLUME"
    elif f["path_count"] == 1 and f["closed_loop"] > 0.7 and f["radius_cv"] < 0.15:
        guess = "RING"
    elif f["radialness"] > 0.55 and (f["path_count"] >= 4 or f["radial_symmetry"] > 0.8):
        guess = "RADIAL"
    elif f["density"] > 0.45 and f["dimensions"] >= 2 and f["linearity"] < 0.9:
        guess = "SURFACE_2D"
    elif f["linearity"] > 0.97 and f["path_count"] <= 2:
        guess = "LINEAR"
    elif f["path_count"] <= 2 and f["curvature"] > 0.25 and f["closed_loop"] < 0.5 and f["density"] < 0.4:
        guess = "ARC"
    elif f["closed_loop"] > 0.7 and f["radial_symmetry"] > 0.5:
        guess = "ORNAMENT"
    elif f["density"] > 0.45 and f["dimensions"] >= 2:
        guess = "SURFACE_2D"
    elif f["path_count"] <= 3 and f["curvature"] < 0.25:
        guess = "LINEAR"
    else:
        guess = "IRREGULAR"
    sem_map = {"tree": "CONE", "arch": "ARC", "matrix": "SURFACE_2D", "spinner": "RADIAL",
               "star": "ORNAMENT", "snowflake": "ORNAMENT", "wreath": "RING", "circle": "RING",
               "roofline": "LINEAR", "outline": "LINEAR", "icicles": "LINEAR", "candy_cane": "ARC",
               "cube": "VOLUME", "sphere": "VOLUME", "face": "SEMANTIC", "character": "SEMANTIC",
               "flood": "FLOOD", "moving_head": "MECHANICAL", "figure": "FIGURE"}
    if semantic == "sculpture":
        # a 3-D custom prop: trust strong geometric structure, else treat as a figure
        return (guess, "geometry", guess) if guess in ("RADIAL", "RING", "LINEAR", "ARC", "CONE") \
            else ("FIGURE", "semantic", guess)
    if semantic and semantic in sem_map:
        return sem_map[semantic], "semantic", guess
    return guess, "geometry", guess
