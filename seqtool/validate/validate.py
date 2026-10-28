# seqtool-command: validate | main | stages | matchup -> validation.json (issues + feedback)
"""Generic validator: seqtool.matchup (+ models, profile) -> seqtool.validation.

Two kinds of output:
  issues   - hard errors and quality warnings, as in the design
  feedback - machine-readable adjustments the matchup can consume on the next
             iteration (`seqtool match --feedback validation.json`). This is the
             validator's half of the coordination loop: it sees the whole plan
             at once, which per-target scoring cannot.

xLights-specific checks (XML validity, effect setting strings) belong to the
xLights output adapter and are added there.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from ..common.canonical import content_sha256, read_json, write_json
from ..common.envelope import check_version, envelope, merge_lineage
from ..common.log import good, info, warn
from ..common.vocab import lit as _lit
from ..common.schemas import validate as schema_validate
from ..common.paths import arg as paths_arg

DEFAULTS = {
    "max_changes_per_8s": 4,
    "min_segment_s": 0.75,
    "min_distinct_effects": 3,
    "max_share_single_effect": 0.6,
    "simultaneous_change_fraction": 0.6,
    "low_transition": 0.3,
    "uniform_section_fraction": 0.7,
    "nudge": 0.85,
    "diversity_feedback": False,   # report low diversity, but don't push the planner around
}



# an example of what to type for each kind of problem (shown with the issue)
FIX = {
    "MODEL_NOT_FOUND": "'run' (the plan is older than the layout)",
    "REACT_NO_EVENTS": "'presets' lists other triggers; e.g. 'react {t} beat'",
    "TIMING_OVERLAP": "'run' again; if it persists, send the matchup file",
    "NEGATIVE_DURATION": "'run' again; if it persists, send the matchup file",
    "MODEL_UNUSED": "'explain {t}' says why; 'pin {t} twinkle' forces an effect",
    "TOO_SHORT": "'pref scoring.durations.default.min = 0.5' (a shorter minimum), or 'unpin {t} @{at:.1f}' (pins keep their length)",
    "TOO_LONG": "'pref scoring.passes.variation.enabled = true' (long effects get one-aspect variations), "
                "'pref scoring.durations.default.max = \"16 bars\"', or 'unpin {t} @{at:.1f}'",
    "AUDIO_DURATION_MISMATCH": "'run' (the plan and the analysis come from different audio)",
    "EXCESSIVE_EFFECT_CHANGES": "'pref change_penalty' (higher = fewer changes)",
    "LOW_EFFECT_DIVERSITY": "'reroll {t}', or 'run --candidates 5'",
    "UNIFORM_SECTION": "'reroll @#{sec}' for new choices in that section",
    "SIMULTANEOUS_CHANGES": "'reroll @{at:.1f}' for new choices there",
}

def _merge(prev: dict, new: dict) -> dict:
    """Feedback accumulates multiplicatively across iterations."""
    out = {"targets": {}}
    for src in (prev.get("targets", {}), new.get("targets", {})):
        for t, adj in src.items():
            o = out["targets"].setdefault(t, {})
            if "change_penalty_scale" in adj:
                o["change_penalty_scale"] = o.get("change_penalty_scale", 1.0) * adj["change_penalty_scale"]
            for e, m in adj.get("effect_preference_scale", {}).items():
                d = o.setdefault("effect_preference_scale", {})
                d[e] = d.get(e, 1.0) * m
            for sec, em in adj.get("section_effect_scale", {}).items():
                d = o.setdefault("section_effect_scale", {}).setdefault(sec, {})
                for e, m in em.items():
                    d[e] = d.get(e, 1.0) * m
    wb = sorted(set(prev.get("weak_boundaries", [])) | set(new.get("weak_boundaries", [])))
    if wb:
        out["weak_boundaries"] = wb
    return out


def _limits(matchup: dict, seg: dict, plan: dict):
    """The duration limits the plan was made with (0.20: stored in its settings)."""
    st = matchup.get("settings", {})
    if "durations" not in st:
        return DEFAULTS["min_segment_s"], None              # a plan from before 0.20
    from ..matchup.durations import limits
    return limits(st["durations"], seg["selected"]["effect"], seg["selected"].get("family", ""),
                  plan.get("pass", "main"), float(st.get("beat_s", 0.5)))


def validate_plan(matchup: dict, models: dict, profile: dict, rules: dict | None = None,
                  iteration: int = 0) -> dict:
    r = {**DEFAULTS, **(rules or {})}
    for d, n in ((matchup, "seqtool.matchup"), (models, "seqtool.models"), (profile, "seqtool.music-profile")):
        check_version(d, n)
        schema_validate(d, n)
    from ..common.freshness import consistency
    issues: list[dict] = []
    fb: dict = {"targets": {}}
    for key, up in (("music_profile", profile), ("models", models)):
        if not consistency(matchup, key, up, "validate"):
            issues.append({"severity": "warning", "code": "STALE_INPUT",
                           "message": f"matchup was built from a different {key} file"})
    known = {m["id"]: m for m in models["models"]}
    dur = max(s["end"] for s in profile["sections"])

    def issue(sev, code, msg, **kw):
        fix = FIX.get(code, "").format(t=kw.get("target", "TARGET"), sec=kw.get("section", (kw.get("details") or {}).get("section_index", "N")),
                                       at=(kw.get("time") or {}).get("start", 0))
        issues.append({"severity": sev, "code": code, "message": msg, **({"fix": fix} if fix else {}), **kw})

    changes_at: Counter = Counter()
    active_targets = 0
    reactive_plans = [p for p in matchup["plans"] if p.get("react")]
    for plan in reactive_plans:
        if plan["target"] not in known:
            issue("error", "MODEL_NOT_FOUND", f"plan target {plan['target']} not in models.json", target=plan["target"])
        elif not plan["segments"]:
            issue("info", "REACT_NO_EVENTS", f"{plan['target']} reacts to '{plan['react']}' but no such events "
                  "were found in the music", target=plan["target"])
    # later passes (top/detail/enhance) are sparse by design: only the hard checks apply to them
    for plan in matchup["plans"]:
        if plan.get("react") or plan.get("pass", "main") == "main":
            continue
        if plan["target"] not in known:
            issue("error", "MODEL_NOT_FOUND", f"plan target {plan['target']} not in models.json", target=plan["target"])
        prev_end = 0.0
        for s in plan["segments"]:
            if s["end"] <= s["start"] or s["start"] < prev_end - 1e-6:
                issue("error", "TIMING_OVERLAP", f"{plan['target']} ({plan['pass']}): bad segment at {s['start']:.2f}",
                      target=plan["target"], time={"start": s["start"], "end": s["end"]})
            prev_end = s["end"]
    matchup = {**matchup, "plans": [p for p in matchup["plans"]
                                    if not p.get("react") and p.get("pass", "main") == "main"]}
    for plan in matchup["plans"]:
        t = plan["target"]
        segs = plan["segments"]
        if t not in known:
            issue("error", "MODEL_NOT_FOUND", f"plan target {t} not in models.json", target=t)
            continue
        if not segs:
            issue("warning", "MODEL_UNUSED", f"{t} has no segments", target=t)
            continue
        prev_end = 0.0
        for s in segs:
            if s["end"] <= s["start"]:
                issue("error", "NEGATIVE_DURATION", f"{t}: segment {s['start']:.2f}-{s['end']:.2f}",
                      target=t, time={"start": s["start"], "end": s["end"]})
            if s["start"] < prev_end - 1e-6:
                issue("error", "TIMING_OVERLAP", f"{t}: segment at {s['start']:.2f} overlaps previous",
                      target=t, time={"start": s["start"], "end": s["end"]})
            mn, mx = _limits(matchup, s, plan)
            d = s["end"] - s["start"]
            if mn is not None and d < mn - 0.05 and _lit(s["selected"]["effect"]):
                issue("warning", "TOO_SHORT", f"{t}: {s['selected']['effect']} lasts {d:.2f} s (the minimum is "
                      f"{mn:.1f} s)", target=t, time={"start": s["start"], "end": s["end"]})
            if mx is not None and d > mx + 0.05 and _lit(s["selected"]["effect"]):
                issue("warning", "TOO_LONG", f"{t}: {s['selected']['effect']} lasts {d:.0f} s (the maximum is "
                      f"{mx:.0f} s)" + (" - pinned" if s.get("pinned") else ""), target=t,
                      time={"start": s["start"], "end": s["end"]})
            prev_end = s["end"]
        rest_end = max((b for _, b in plan.get("rests", {}).get("spans", [])), default=0.0)
        if abs(segs[-1]["end"] - dur) > 0.5 and abs(rest_end - dur) > 0.5:
            issue("warning", "AUDIO_DURATION_MISMATCH", f"{t} ends at {segs[-1]['end']:.1f}s, song is {dur:.1f}s",
                  target=t)
        effs = [s["selected"]["effect"] for s in segs]
        lit = [s for s in segs if _lit(s["selected"]["effect"])]
        if lit:
            active_targets += 1
        else:
            issue("warning", "MODEL_UNUSED", f"{t} has no effect for the whole song (transparent throughout)", target=t)
        change_times = [segs[i]["start"] for i in range(1, len(segs)) if effs[i] != effs[i - 1]]
        for ct in change_times:
            changes_at[round(ct, 2)] += 1
        # burst detection: sliding 8 s window
        for i, ct in enumerate(change_times):
            n8 = sum(1 for c in change_times[i:] if c < ct + 8)
            if n8 > r["max_changes_per_8s"]:
                issue("warning", "EXCESSIVE_EFFECT_CHANGES", f"{t} changes effect {n8} times in 8 s",
                      target=t, time={"start": ct, "end": ct + 8},
                      details={"change_count": n8, "recommended_max": r["max_changes_per_8s"]})
                fb["targets"].setdefault(t, {})["change_penalty_scale"] = 1.5
                break
        # diversity: time share of the dominant effect
        share = Counter()
        for s in lit:
            share[s["selected"]["effect"]] += s["end"] - s["start"]
        total = sum(share.values())
        if total:
            top, top_t = share.most_common(1)[0]
            if top_t / total > r["max_share_single_effect"] and len(share) < r["min_distinct_effects"]:
                issue("info", "LOW_EFFECT_DIVERSITY",
                      f"{t} uses {top} for {100 * top_t / total:.0f}% of lit time",
                      target=t, details={"effect": top, "share": top_t / total})
                if r["diversity_feedback"]:
                    fb["targets"].setdefault(t, {}).setdefault("effect_preference_scale", {})[top] = r["nudge"]

    # cross-target coordination: one effect on most props within a section looks flat.
    # Nudge the half of those props whose choice had the smallest margin over an alternative.
    by_sec: dict[int, list[tuple[str, str, float]]] = {}
    for plan in matchup["plans"]:
        for s in plan["segments"]:
            alts = s.get("alternatives") or [{"score": 0.0}]
            by_sec.setdefault(s.get("section_index", 0), []).append(
                (plan["target"], s["selected"]["effect"], s["selected"]["score"] - alts[0]["score"]))
    for sec, rows in sorted(by_sec.items()):
        tgts = {t for t, _, _ in rows}
        counts = Counter(e for _, e, _ in {(t, e, 0) for t, e, _ in rows})
        if len(tgts) < 3 or not counts:
            continue
        eff, k = counts.most_common(1)[0]
        if _lit(eff) and k / len(tgts) >= r["uniform_section_fraction"]:
            users = sorted({(m, t) for t, e, m in rows if e == eff})
            nudged = [t for _, t in users[: (len(users) + 1) // 2]]
            issue("info", "UNIFORM_SECTION", f"section #{sec}: {eff} on {k} of {len(tgts)} targets",
                  details={"section_index": sec, "effect": eff, "nudged": nudged})
            for t in nudged:
                fb["targets"].setdefault(t, {}).setdefault("section_effect_scale", {}) \
                    .setdefault(str(sec), {})[eff] = r["nudge"]

    # cross-target coordination: many targets changing together at a weak boundary
    if active_targets:
        trans_at = {}
        for plan in matchup["plans"]:
            for s in plan["segments"]:
                if "continuity" in s:
                    trans_at[round(s["start"], 2)] = s["continuity"]["transition_strength"]
        for t_, n in sorted(changes_at.items()):
            if n / active_targets >= r["simultaneous_change_fraction"] and \
                    trans_at.get(t_, 1.0) < r["low_transition"]:
                issue("warning", "SIMULTANEOUS_CHANGES",
                      f"{n} of {active_targets} targets change at {t_:.2f}s on a weak musical transition",
                      time={"start": t_, "end": t_}, details={"targets_changing": n})
                fb.setdefault("weak_boundaries", []).append(t_)

    sev = Counter(i["severity"] for i in issues)
    lineage = merge_lineage(matchup)
    doc = envelope("seqtool.validation", "seqtool-validate",
                   {"matchup": {"schema": matchup["schema"], "schema_version": matchup["schema_version"],
                                "content_sha256": content_sha256(matchup)}}, lineage)
    doc["result"] = "error" if sev["error"] else "warning" if sev["warning"] else "ok"
    doc["summary"] = {"errors": sev["error"], "warnings": sev["warning"], "info": sev["info"]}
    doc["issues"] = issues
    has_new = bool(fb["targets"] or fb.get("weak_boundaries"))
    fb = _merge(matchup["settings"].get("applied_feedback", {}), fb)
    fb["iteration"] = iteration
    fb["converged"] = not has_new
    doc["feedback"] = fb
    schema_validate(doc, "seqtool.validation")
    return doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool validate", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--matchup", type=paths_arg, default=None,
                    help="the matchup.json, or a song (its newest); default: the current song's")
    ap.add_argument("--models", type=paths_arg, default=None, help="default: the one the matchup was made from")
    ap.add_argument("--profile", type=paths_arg, default=None, help="default: the one the matchup was made from")
    ap.add_argument("--output", "-o", type=paths_arg, default=None,
                    help="default: next to the matchup, named like it (song.validation.json)")
    ap.add_argument("--baseline", nargs="?", metavar="N", help="song N of your baseline instead (no N: each song in turn; 'baseline' lists them)")
    a = ap.parse_args(argv)
    from ..common.paths import show, sibling
    from ..common import current
    if a.matchup is None:
        s = current.song()
        if not s or not s.get("matchup"):
            raise SystemExit("no plan yet for the current song - 'run' or 'match' makes one (or give --matchup)")
        a.matchup = s["matchup"]
    else:
        a.matchup = current.results_of(a.matchup, "matchup")
    m = read_json(a.matchup)
    src = m.get("source", {})
    a.models = a.models or a.matchup.parent / src.get("models", {}).get("filename", "layout.models.json")
    a.profile = a.profile or a.matchup.parent / src.get("music_profile", {}).get("filename", "")
    a.output = a.output or sibling(a.matchup, "validation")
    doc = validate_plan(m, read_json(a.models), read_json(a.profile),
                        iteration=m["settings"].get("iteration", 0))
    write_json(a.output, doc)
    for i in doc["issues"]:
        (warn if i["severity"] != "info" else info)(f"  {i['severity']:<7} {i['code']:<26} {i['message']}"
                                                    + (f"\n  {'':<7} {'':<26} {{note}}fix: {i['fix']}{{/}}" if i.get("fix") else ""))
    good(f"wrote {show(a.output)}: {doc['result']}")
    return 2 if doc["result"] == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
