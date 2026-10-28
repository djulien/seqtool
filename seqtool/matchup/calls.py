"""Call and response, from the cues you tag (0.24.49).

You mark the first pair or two by hand - cues on the call's notes and the response's hits -
and tag them 'call' ('cue tag call @#3' tags every cue in section 3). seqtool takes it from
there:

  phrases    the tagged cues, split where they pause for more than calls.gap_beats beats;
             with only 'call' tags the phrases take turns: call, response, call ...; with
             'response' tags too, each phrase is what its first cue says
  the cycle  how far a response comes after its call, and a call after the previous one -
             each the median over your pairs, snapped to whole beats (one pair: a call
             every 2 x that far)
  the rest   of the section (and in its repeats that you didn't mark, from the same place in
             them): a call every cycle, its notes the onsets heard in it (calls.onset
             threshold); its response the same timing one offset later - or with
             calls.response = "onsets" the onsets heard there

Events (each with its pair number, 'derived' when seqtool found it):
    call / response                  each note / hit
    call_phrase / response_phrase    each phrase, start to end (its last note + a beat)
    pair                             a call and its response, start to end
A choreography step uses them like any event ("per": "call", "per": "response_phrase"),
'calls' lists them.
"""
from __future__ import annotations

import bisect
import statistics

from ..common import config

ROLES = ("call", "response")
TRIGGERS = ("call", "response", "call_phrase", "response_phrase", "pair")


def _prefs() -> dict:
    return {"gap_beats": 2.0, "onset": 0.5, "response": "copy", **(config.load("music").get("calls") or {})}


def phrases(cues: list[dict], beat: float, gap_beats: float) -> list[dict]:
    """Tagged cues -> [{"role", "notes": [t...]}], in time order."""
    tagged = sorted((c for c in cues if c.get("tag") in ROLES), key=lambda c: float(c["t"]))
    if not tagged:
        return []
    out, cur = [], None
    for c in tagged:
        t = float(c["t"])
        new = cur is None or t - cur["notes"][-1] > gap_beats * beat or \
            (c["tag"] == "response" and cur["tag"] != "response")
        if new:
            cur = {"tag": c["tag"], "notes": [t]}
            out.append(cur)
        else:
            cur["notes"].append(t)
    explicit = any(p["tag"] == "response" for p in out)
    for i, p in enumerate(out):
        p["role"] = p["tag"] if explicit else ROLES[i % 2]
    return out


def derive(music: dict, profile: dict, cues: list[dict], onsets: list[float] | None = None) -> list[dict]:
    """-> [{"time", "end", "kind" (a TRIGGER), "pair", "derived"}], sorted."""
    pr = _prefs()
    an = music["analysis"]
    beats = [b["time"] for b in an["events"]["beats"]]
    if len(beats) < 4:
        return []
    beat = statistics.median(b - a for a, b in zip(beats, beats[1:]))
    ph = phrases(cues, beat, float(pr["gap_beats"]))
    if len(ph) < 2:
        return []
    secs = profile["sections"]

    def sec_of(t):
        return next((s for s in secs if s["start"] <= t < s["end"]), secs[-1])

    def bi(t):                                       # nearest beat index
        i = bisect.bisect_left(beats, t)
        return min((j for j in (i - 1, i) if 0 <= j < len(beats)), key=lambda j: abs(beats[j] - t))

    pairs = []
    i = 0
    while i < len(ph) - 1:
        if ph[i]["role"] == "call" and ph[i + 1]["role"] == "response":
            pairs.append((ph[i], ph[i + 1]))
            i += 2
        else:
            i += 1
    if not pairs:
        return []
    off_b = max(1, round(statistics.median(bi(r["notes"][0]) - bi(c["notes"][0]) for c, r in pairs)))
    starts = [bi(c["notes"][0]) for c, _ in pairs]
    cyc_b = max(off_b + 1, round(statistics.median(b - a for a, b in zip(starts, starts[1:])))) if len(starts) > 1 \
        else 2 * off_b
    if onsets is None:
        from .reactive import onsets as _on
        onsets = _on(music, float(pr["onset"]))
    out = []

    def add(kind, t, end, n, derived):
        out.append({"time": round(t, 3), "end": round(end, 3), "kind": kind, "pair": n, "derived": derived})

    def emit(call_notes, resp_notes, n, derived, cstart, rstart):
        c_end = (call_notes[-1] if call_notes else cstart) + beat
        r_end = (resp_notes[-1] if resp_notes else rstart) + beat
        for kind, ns, end in (("call", call_notes, c_end), ("response", resp_notes, r_end)):
            for j, t in enumerate(ns):                 # a note lasts to the next one (a beat at most)
                add(kind, t, min(t + beat, end, ns[j + 1] if j + 1 < len(ns) else end), n, derived)
        add("call_phrase", cstart, min(c_end, rstart), n, derived)
        add("response_phrase", rstart, r_end, n, derived)
        add("pair", cstart, r_end, n, derived)

    n = 0
    for c, r in pairs:
        n += 1
        emit(c["notes"], r["notes"], n, False, c["notes"][0], r["notes"][0])

    def run_on(sec, first_b, n):
        """Derived pairs in `sec`, the first call at beat index first_b."""
        k = first_b
        while k + off_b < len(beats) and beats[k] < sec["end"] - beat:
            cs, rs = beats[k], beats[k + off_b]
            ce = beats[min(k + off_b, len(beats) - 1)]
            notes = [t for t in onsets if cs - 0.06 <= t < ce - 0.06]
            if notes:
                if pr["response"] == "onsets":
                    re_ = beats[min(k + cyc_b, len(beats) - 1)]
                    resp = [t for t in onsets if rs - 0.06 <= t < min(re_, sec["end"]) - 0.06]
                else:
                    resp = [round(t + (rs - cs), 3) for t in notes if t + (rs - cs) < sec["end"]]
                n += 1
                emit(notes, resp, n, True, cs, rs)
            k += cyc_b
        return n

    marked = {}
    for c, _ in pairs:
        s = sec_of(c["notes"][0])
        marked.setdefault(s["id"], []).append(c)
    ids = {s["id"]: s for s in secs}

    def root(s):
        while s.get("repeat_of") in ids:
            s = ids[s["repeat_of"]]
        return s["id"]
    for sid, calls in marked.items():
        s = ids[sid]
        last = bi(calls[-1]["notes"][0])
        n = run_on(s, last + cyc_b, n)
    for sid, calls in marked.items():
        s = ids[sid]
        lead = bi(calls[0]["notes"][0]) - bi(s["start"])   # where the first call is, in beats into the section
        for o in secs:
            if o["id"] in marked or root(o) != root(s):
                continue
            n = run_on(o, bi(o["start"]) + lead, n)
    out.sort(key=lambda e: (e["time"], TRIGGERS.index(e["kind"])))
    return out
