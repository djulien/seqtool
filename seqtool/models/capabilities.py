"""Class baseline capabilities, modulated by measured features (30%)."""
from __future__ import annotations

BASE = {
    "LINEAR":     dict(linear_motion=.95, horizontal_motion=.85, vertical_motion=.1, radial_motion=.05,
                       rotational_motion=.05, expanding_motion=.3, chase=.95, color_wash=.8, twinkle=.85,
                       sparkle=.8, particles=.6, text=.05),
    "ARC":        dict(linear_motion=.9, horizontal_motion=.8, vertical_motion=.3, radial_motion=.1,
                       rotational_motion=.25, expanding_motion=.4, chase=.95, color_wash=.8, twinkle=.85,
                       sparkle=.8, particles=.6, text=.05),
    "RING":       dict(linear_motion=.5, horizontal_motion=.4, vertical_motion=.3, radial_motion=.2,
                       rotational_motion=.9, expanding_motion=.3, chase=.95, color_wash=.8, twinkle=.95,
                       sparkle=.9, particles=.3, text=.0),
    "RADIAL":     dict(linear_motion=.3, horizontal_motion=.3, vertical_motion=.3, radial_motion=.97,
                       rotational_motion=.95, expanding_motion=.9, chase=.7, color_wash=.8, twinkle=.85,
                       sparkle=.85, particles=.5, text=.05),
    "ORNAMENT":   dict(linear_motion=.3, horizontal_motion=.3, vertical_motion=.3, radial_motion=.75,
                       rotational_motion=.6, expanding_motion=.6, chase=.7, color_wash=.85, twinkle=.95,
                       sparkle=.95, particles=.2, text=.0),
    "SURFACE_2D": dict(linear_motion=.7, horizontal_motion=.95, vertical_motion=.95, radial_motion=.7,
                       rotational_motion=.75, expanding_motion=.85, chase=.6, color_wash=.95, twinkle=.85,
                       sparkle=.85, particles=.95, text=.95),
    "CONE":       dict(linear_motion=.6, horizontal_motion=.8, vertical_motion=.95, radial_motion=.55,
                       rotational_motion=.95, expanding_motion=.8, chase=.75, color_wash=.95, twinkle=.9,
                       sparkle=.85, particles=.85, text=.2),
    "VOLUME":     dict(linear_motion=.6, horizontal_motion=.85, vertical_motion=.85, radial_motion=.6,
                       rotational_motion=.7, expanding_motion=.85, chase=.5, color_wash=.95, twinkle=.8,
                       sparkle=.8, particles=.8, text=.3),
    "FIGURE":     dict(linear_motion=.35, horizontal_motion=.6, vertical_motion=.6, radial_motion=.2,
                       rotational_motion=.2, expanding_motion=.4, chase=.35, color_wash=.95, twinkle=.85,
                       sparkle=.85, particles=.35, text=.0),
    "FLOOD":      dict(linear_motion=.0, horizontal_motion=.0, vertical_motion=.0, radial_motion=.0,
                       rotational_motion=.0, expanding_motion=.0, chase=.0, color_wash=1.0, twinkle=.1,
                       sparkle=.3, particles=.0, text=.0),
    "IRREGULAR":  dict(linear_motion=.4, horizontal_motion=.5, vertical_motion=.5, radial_motion=.3,
                       rotational_motion=.3, expanding_motion=.4, chase=.5, color_wash=.85, twinkle=.85,
                       sparkle=.8, particles=.4, text=.1),
}
SUPPORTED = set(BASE)


def derive(cls: str, f: dict) -> dict:
    base = BASE.get(cls, BASE["IRREGULAR"])
    est = {
        "linear_motion": max(f.get("linearity", 0), 1 - f.get("curvature", 1)) if f.get("path_count", 9) <= 2 else None,
        "radial_motion": f.get("radialness"),
        "rotational_motion": max(f.get("closed_loop", 0), f.get("radialness", 0), f.get("radial_symmetry", 0) * 0.8),
        "horizontal_motion": min(1.0, 2 * f.get("horizontal_extent", 0.5)),
        "vertical_motion": min(1.0, 2 * (1 - f.get("horizontal_extent", 0.5))),
    }
    out = {}
    for k, v in base.items():
        e = est.get(k)
        out[k] = round(v if e is None else 0.7 * v + 0.3 * e, 4)
    return out
