"""The show critic: one score for a whole plan, used to pick the best of several
seeds (run --candidates N). It judges what per-prop scoring can't see:

    fit      how well the chosen effects fit (duration-weighted mean static score,
             main-pass plans, lit segments)
    variety  per target, 1 - the largest share of its lit time one effect takes
             (averaged over targets)
    repeats  how faithfully repeated sections repeat their first occurrence
             (an exact column = 1, most targets = 0.5)
    issues   validator warnings (errors count 3)

score = fit x w.fit + variety x w.variety + repeats x w.repeats - issues x w.issues
Weights: scoring.json 'critic'. Pinned segments count like any other.
"""
from __future__ import annotations

from ..common.vocab import lit

DEFAULT = {"fit": 1.0, "variety": 0.3, "repeats": 0.3, "issues": 0.02}


def critique(matchup: dict, validation: dict | None, profile: dict, weights: dict | None = None) -> dict:
    w = {**DEFAULT, **(weights or {})}
    w.pop("candidates", None)
    main = [p for p in matchup["plans"] if p.get("pass", "main") == "main" and not p.get("react")]
    num = den = 0.0
    var = []
    for p in main:
        share: dict[str, float] = {}
        for g in p["segments"]:
            e = g["selected"]["effect"]
            if not lit(e):
                continue
            d = g["end"] - g["start"]
            num += g["score_breakdown"]["static"] * d
            den += d
            share[e] = share.get(e, 0.0) + d
        if share:
            var.append(1 - max(share.values()) / sum(share.values()))
    fit = num / den if den else 0.0
    variety = sum(var) / len(var) if var else 0.0
    from ..demo.run import section_matches
    reps = [s for s in profile["sections"] if s.get("repeat_of")]
    if reps:
        sm = section_matches(profile, matchup)
        repeats = sum(1.0 if sm.get(s["index"], "").startswith("=") else
                      0.5 if sm.get(s["index"], "").startswith("~") else 0.0 for s in reps) / len(reps)
    else:
        repeats = 1.0
    summ = (validation or {}).get("summary", {})
    issues = summ.get("warnings", 0) + 3 * summ.get("errors", 0)
    score = fit * w["fit"] + variety * w["variety"] + repeats * w["repeats"] - issues * w["issues"]
    return {"score": round(score, 4), "fit": round(fit, 3), "variety": round(variety, 3),
            "repeats": round(repeats, 3), "issues": issues}


def line(seed: int, c: dict, mark: str = " ") -> str:
    return (f"  {mark} seed {seed:<8} {c['score']:.3f}  = fit {c['fit']:.2f}, variety {c['variety']:.2f}, "
            f"repeats {c['repeats']:.2f}, {c['issues']} issue(s)")
