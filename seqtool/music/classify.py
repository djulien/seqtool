# seqtool-command: classify-music | main | stages | music.json -> music-profile.json
"""Music classifier: seqtool.music -> seqtool.music-profile (deterministic rules).

Sections: built from analyzer boundaries, given sequential integer `index`
values (1..N) plus frame/beat index ranges so any section can be dereferenced
back into music.json. Repetition is detected by comparing section feature
vectors; labels come from repetition + relative energy + position, with
honest (modest) confidences. Every rule here is meant to be replaced.
"""
from __future__ import annotations

import argparse
import sys
from bisect import bisect_left
from pathlib import Path

import numpy as np

from ..common.canonical import content_sha256, read_json, write_json
from ..common.envelope import check_version, envelope, merge_lineage
from ..common.log import good, info
from ..common.schemas import validate
from ..common.paths import arg as paths_arg

FEATS = ("energy_norm", "beat_strength", "brightness_norm", "bass_norm", "mid_norm", "treble_norm",
         "onset_norm")


def _clip(x):
    return float(min(1.0, max(0.0, x)))


def styles_and_character(music: dict) -> tuple[dict, dict]:
    s = music["analysis"]["summary"]
    bpm = s["tempo"]["bpm"]
    loud = s["energy"]["p95_dbfs"]
    dr = s["dynamic_range_db"]
    beat = s.get("beat_strength_mean", 0.3)
    sp = s.get("spectral", {})
    bass, treb = sp.get("bass_share_mean", 0.3), sp.get("treble_share_mean", 0.2)
    bright = _clip((sp.get("centroid_hz_mean", 1500) - 800) / 2500)
    vocal = s.get("vocal", {}).get("mean")
    energy = _clip((loud + 30) / 22)             # -30 dBFS -> 0, -8 dBFS -> 1
    fast = _clip((bpm - 80) / 60)
    steady = _clip(1 - (dr - 6) / 18)            # small dynamic range = steady/compressed
    v = 0.5 if vocal is None else vocal
    styles = {
        "electronic": _clip(0.35 * beat + 0.25 * steady + 0.2 * _clip(bass * 2) + 0.2 * fast - 0.15 * v),
        "rock": _clip(0.3 * energy + 0.3 * beat + 0.2 * bright + 0.2 * _clip(1 - bass * 2)),
        "pop": _clip(0.3 * beat + 0.25 * energy + 0.25 * v + 0.2 * (1 - abs(bpm - 115) / 60)),
        "orchestral": _clip(0.45 * _clip((dr - 10) / 15) + 0.35 * (1 - beat) + 0.2 * (1 - bass)),
        "ballad": _clip(0.4 * _clip((95 - bpm) / 30) + 0.35 * (1 - energy) + 0.25 * (1 - beat)),
        "ambient": _clip(0.5 * (1 - beat) + 0.3 * (1 - energy) + 0.2 * steady),
        "traditional_christmas": _clip(0.4 * _clip(treb * 3) * (1 - beat) + 0.1),
    }
    styles["unknown"] = _clip(0.6 - max(styles.values()))
    character = {
        "energy": energy,
        "danceability": _clip(beat * (1 - abs(bpm - 118) / 70)),
        "dramatic": _clip((dr - 8) / 16),
        "peaceful": _clip((1 - energy) * (1 - beat)),
        "rhythmic": _clip(beat),
    }
    return styles, character


_ENTRIES: dict = {}


def vocal_entries(music: dict, gap_bars: float = 2.0) -> list[float]:
    """Times where singing starts after at least gap_bars bars without it: from the vocal
    stem (if analysed) and from imported lyrics (line starts after a pause). Cached per
    analysis (sections tune asks many times)."""
    key = (id(music), gap_bars, music.get("source", {}).get("sha256"))
    if key not in _ENTRIES:
        if len(_ENTRIES) > 64:
            _ENTRIES.clear()
        _ENTRIES[key] = _vocal_entries(music, gap_bars)
    return _ENTRIES[key]


def _vocal_entries(music: dict, gap_bars: float) -> list[float]:
    an = music["analysis"]
    bar = 240.0 / (an["summary"]["tempo"]["bpm"] or 120.0)
    out: list[float] = []
    from . import vocals
    a = vocals.analyse(music)
    if a is not None:
        quiet = 0
        for i, k in enumerate(a["classes"]):
            if k == "i":
                quiet += 1
            else:
                if quiet * a["fi"] >= gap_bars * bar:
                    out.append(i * a["fi"])
                quiet = 0
    try:
        from .lyrics import for_music
        lines = (for_music(music) or {}).get("lines", [])
    except Exception:  # noqa: BLE001
        lines = []
    starts = [ln["start"] for ln in lines]
    for prev, t in zip([None] + starts[:-1], starts):
        if prev is None or t - prev >= gap_bars * bar:
            out.append(float(t))
    return sorted(out)


def lyric_block_starts(music: dict) -> list[tuple[float, float]]:
    """[(time, strength)] where a repeated passage of lyrics begins (see lyric_structure)."""
    from .lyric_structure import evidence
    return [(t, st) for t, st, why in evidence(music) if why == "lyrics repeat"]


def candidates(music: dict, method: str = "combined", novelty_weight: float = 0.8,
               vocal_entry: float = 0.0, lyrics: float = 1.0) -> list[dict]:
    """Boundary candidates {time, strength}. novelty: the analyzer's checkerboard/energy
    boundaries. laplacian: label changes of the spectral clustering, snapped to the
    nearest bar line when one is within half a bar. combined: both; where they agree
    (within half a bar) the stronger strength is kept."""
    an = music["analysis"]
    bpm = an["summary"]["tempo"]["bpm"] or 120.0
    half_bar = 2 * 60.0 / bpm
    nov = [dict(b) for b in an.get("boundaries", [])]
    lap = [dict(b) for b in an.get("segmentation", {}).get("laplacian", {}).get("boundaries", [])]
    downs = [d["time"] for d in an["events"].get("downbeats", [])]
    for b in lap:
        if downs:
            near = min(downs, key=lambda d: abs(d - b["time"]))
            if abs(near - b["time"]) <= half_bar:
                b["time"] = near
    out = _merge_methods(nov, lap, method, novelty_weight, half_bar)

    def add(t, strength, why):                # evidence at time t: a candidate on the nearest bar line
        if not downs or strength <= 0:
            return
        d = min(downs, key=lambda x: abs(x - t))
        if abs(d - t) > half_bar:
            return
        near = [b for b in out if abs(b["time"] - d) <= half_bar]
        if near:                              # agrees with one already there: it moves to the bar line
            for b in near:
                if strength > b.get("strength", 0.5):
                    b["strength"], b["time"] = strength, d
                if why.startswith("lyrics"):
                    b["lyrics"] = why
        else:
            out.append({"time": d, "strength": strength, "only": why, **({"lyrics": why} if why.startswith("lyrics") else {})})
    if vocal_entry > 0:
        for e in vocal_entries(music):
            add(e, vocal_entry, "vocal entry")
    if lyrics > 0:
        from .lyric_structure import evidence
        for t, st, why in evidence(music):
            add(t, min(1.0, st * lyrics), why)
    return out


def _merge_methods(nov, lap, method, novelty_weight, half_bar):
    if method == "novelty" or not lap:
        return nov
    if method == "laplacian":
        return lap
    w = float(novelty_weight) or 1e-6
    merged = [dict(b, strength=w * b.get("strength", 0.5), only="novelty") for b in nov]
    for b in lap:
        same = [m for m in merged if abs(m["time"] - b["time"]) <= half_bar]
        if same:                                          # both methods agree: full credit to the stronger
            for m in same:
                m["strength"] = max(m.get("strength", 0.5) / w if m.pop("only", None) else m["strength"],
                                    b.get("strength", 0.5))
        else:
            merged.append(b)
    return merged


def choose_boundaries(music: dict, min_bars: float, min_strength: float, method: str = "combined",
                      novelty_weight: float = 0.8, vocal_entry: float = 0.0, lyrics: float = 1.0,
                      lyric_min_bars: float | None = None) -> list[float]:
    """Strongest candidate boundaries first, keeping sections at least min_bars long
    (the first and last may be half that). Boundaries the lyrics show (a repeated
    passage beginning or ending, the singing stopping) only need lyric_min_bars between
    them and the others: short passages the words mark off, such as a spoken lead-in."""
    an = music["analysis"]
    dur = music["audio"]["duration"]
    bpm = an["summary"]["tempo"]["bpm"] or 120.0
    q = 0.25 * 60.0 / bpm                                        # a quarter-beat of tolerance
    gap = min_bars * 4 * 60.0 / bpm - q
    lgap = min(min_bars, lyric_min_bars if lyric_min_bars is not None else min_bars) * 4 * 60.0 / bpm - q
    chosen: list[tuple[float, bool]] = []
    for b in sorted(candidates(music, method, novelty_weight, vocal_entry, lyrics), key=lambda b: (-b.get("strength", 0.5), b["time"])):
        t, ly = b["time"], bool(b.get("lyrics"))
        if b.get("strength", 0.5) < min_strength or t < gap / 2 or dur - t < gap / 2:
            continue
        if all(abs(t - c) >= (lgap if ly and cl else gap) for c, cl in chosen):
            chosen.append((t, ly))
    return sorted(t for t, _ in chosen)


def boundary_trace(music: dict, rules: dict) -> list[str]:
    """--debug for 'sections' (0.19.5): every candidate boundary, its strength and evidence,
    and whether it was kept - or why not - exactly as choose_boundaries decides."""
    an = music["analysis"]
    dur = music["audio"]["duration"]
    bpm = an["summary"]["tempo"]["bpm"] or 120.0
    method, nw = rules.get("method", "combined"), rules.get("novelty_weight", 0.8)
    ve = float(rules.get("vocal_entry", 0.0) or 0.0)
    ly = float(rules.get("lyrics", 1.0) if rules.get("lyrics") is not None else 1.0)
    min_bars, min_strength = rules.get("min_bars", 8), rules.get("min_strength", 0.0)
    q = 0.25 * 60.0 / bpm
    gap = min_bars * 4 * 60.0 / bpm - q
    lgap = min(min_bars, rules.get("lyric_min_bars", 2)) * 4 * 60.0 / bpm - q
    downs = [d["time"] for d in an["events"].get("downbeats", [])]
    L = [f"method {method}, novelty_weight {nw}, vocal_entry {ve}, lyrics {ly}, min_bars {min_bars} "
         f"({gap:.1f} s), lyric_min_bars {rules.get('lyric_min_bars', 2)} ({lgap:.1f} s), min_strength {min_strength}, "
         f"tempo {bpm:.1f}", "",
         "candidates, strongest first (as they are chosen):",
         f"{'time':>8} {'bar':>4} {'strength':>8}  {'evidence':<28} result"]
    chosen: list[tuple[float, bool]] = []
    for b in sorted(candidates(music, method, nw, ve, ly), key=lambda b: (-b.get("strength", 0.5), b["time"])):
        t, lyr, st = b["time"], bool(b.get("lyrics")), b.get("strength", 0.5)
        bar = 1 + min(range(len(downs)), key=lambda i: abs(downs[i] - t)) if downs else 0
        ev = b.get("only") or ("+".join(k for k in ("novelty", "laplacian") if b.get(k)) or method)
        if b.get("lyrics") and b.get("lyrics") != ev:
            ev += f" + {b['lyrics']}"
        if st < min_strength:
            why = f"dropped: weaker than min_strength {min_strength}"
        elif t < gap / 2 or dur - t < gap / 2:
            why = "dropped: too near the start or end"
        else:
            clash = [c for c, cl in chosen if abs(t - c) < (lgap if lyr and cl else gap)]
            if clash:
                why = f"dropped: only {abs(t - clash[0]):.1f} s from the boundary kept at {clash[0]:.1f}"
            else:
                chosen.append((t, lyr))
                why = "KEPT"
        L.append(f"{t:8.2f} {bar:>4} {st:8.2f}  {ev[:28]:<28} {why}")
    return L


def sections(music: dict, rules: dict | None = None, edits: dict | None = None) -> list[dict]:
    an = music["analysis"]
    dur = music["audio"]["duration"]
    dt, n = an["frame_interval"], an["frames"]["count"]
    fields = {k: np.asarray(v) for k, v in an["frames"]["fields"].items()}
    rules = rules or {"min_bars": 8, "min_strength": 0.0}
    edits = edits or {}
    method = rules.get("method", "combined")
    nw = rules.get("novelty_weight", 0.8)
    ve = float(rules.get("vocal_entry", 0.0) or 0.0)
    ly = float(rules.get("lyrics", 1.0) if rules.get("lyrics") is not None else 1.0)
    detected = {b["time"]: b.get("strength", 0.5) for b in candidates(music, method, nw, ve, ly)}
    if edits.get("boundaries") is not None:                    # the user's own boundaries win
        inner = sorted(t for t in edits["boundaries"] if 0 < t < dur)
        bstr = {t: max([v for d, v in detected.items() if abs(d - t) < 0.5] + [0.8]) for t in inner}
    else:
        inner = choose_boundaries(music, rules.get("min_bars", 8), rules.get("min_strength", 0.0), method, nw, ve, ly,
                                  rules.get("lyric_min_bars", 2))
        bstr = {t: detected[t] for t in inner}
    cuts = [0.0] + inner + [dur]
    beat_t = [b["time"] for b in an["events"]["beats"]]
    secs = []
    for i, (a, b) in enumerate(zip(cuts[:-1], cuts[1:]), start=1):
        i0, i1 = int(round(a / dt)), max(int(round(b / dt)), int(round(a / dt)) + 1)
        i1 = min(i1, n)
        vec = {k: float(fields[k][i0:i1].mean()) for k in FEATS if k in fields}
        if "vocal" in fields:
            vec["vocal"] = float(fields["vocal"][i0:i1].mean())
        secs.append({"index": i, "id": f"S{i:02d}", "start": a, "end": b,
                     "frame_range": [i0, i1],
                     "beat_range": [bisect_left(beat_t, a), bisect_left(beat_t, b)],
                     "_vec": vec, "_bstr": bstr.get(a, 1.0 if i == 1 else 0.5)})
    # Laplacian labels: the majority kind of material in each section (if analysed)
    lapd = an.get("segmentation", {}).get("laplacian")
    if lapd and an["events"]["beats"]:
        from .laplacian import segment_labels_for
        bts = np.array([b["time"] for b in an["events"]["beats"]])
        labs = np.array(lapd["beat_labels"][: len(bts)])
        for s, lab in zip(secs, segment_labels_for(cuts, bts[: len(labs)], labs)):
            s["_lap"] = lab
    # repetition: cosine similarity of z-scored section vectors
    keys = [k for k in FEATS if k in secs[0]["_vec"]]
    X = np.array([[s["_vec"][k] for k in keys] for s in secs])
    if len(secs) > 2:
        Z = (X - X.mean(axis=0)) / (X.std(axis=0) + 1e-6)
        Z /= np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9
        S = Z @ Z.T
    else:
        S = np.eye(len(secs))
    for j, s in enumerate(secs):
        for i in range(j):
            same_material = s.get("_lap", -1) >= 0 and s.get("_lap") == secs[i].get("_lap")
            if (S[i, j] > 0.85 or (same_material and S[i, j] > 0.6)) and \
                    abs(s["_vec"]["energy_norm"] - secs[i]["_vec"]["energy_norm"]) < 0.2:
                root = secs[i].get("repeat_of", secs[i]["id"])
                s["repeat_of"] = root
                break
    # labels
    energies = np.array([s["_vec"]["energy_norm"] for s in secs])
    med = float(np.median(energies))
    clusters: dict[str, list[dict]] = {}
    for s in secs:
        clusters.setdefault(s.get("repeat_of", s["id"]), []).append(s)
    rep = {k: v for k, v in clusters.items() if len(v) > 1}
    chorus_root = max(rep, key=lambda k: np.mean([x["_vec"]["energy_norm"] for x in rep[k]]), default=None)
    for idx, s in enumerate(secs):
        e = s["_vec"]["energy_norm"]
        root = s.get("repeat_of", s["id"])
        conf = 0.45
        if idx == 0 and e <= med and len(secs) > 2:
            typ, conf = "intro", 0.6
        elif idx == len(secs) - 1 and e <= med and len(secs) > 2:
            typ, conf = "outro", 0.6
        elif root == chorus_root:
            typ, conf = "chorus", 0.65
        elif root in rep:
            typ, conf = ("verse", 0.55) if e < energies.max() - 0.1 else ("chorus", 0.5)
        elif e >= np.percentile(energies, 80):
            typ = "chorus" if chorus_root is None else "drop"
        elif idx + 1 < len(secs) and secs[idx + 1].get("repeat_of", secs[idx + 1]["id"]) == chorus_root \
                and e < secs[idx + 1]["_vec"]["energy_norm"]:
            typ, conf = "pre_chorus", 0.45
        elif e < med - 0.15:
            typ = "breakdown"
        else:
            typ = "bridge" if 0 < idx < len(secs) - 1 else "verse"
        s["type"], s["confidence"] = typ, conf
    if ly > 0:                                                  # the words know chorus from verse
        from .lyric_structure import section_words, types as lyric_types
        bar = 4 * 60.0 / (an["summary"]["tempo"]["bpm"] or 120.0)
        words = section_words(music, secs)
        if words:
            for idx, (s, lt) in enumerate(zip(secs, lyric_types(secs, words, bar))):
                if lt is None or (lt[0] != "chorus" and ((idx == 0 and s["type"] == "intro") or
                                                         (idx == len(secs) - 1 and s["type"] == "outro"))):
                    continue                                    # an intro or outro, unless it is the chorus
                if lt[0] == "breakdown" and s["type"] in ("drop", "solo", "build", "breakdown"):
                    continue                                    # few words: the sound tells which kind
                s["type"], s["confidence"], s["type_why"] = lt[0], 0.7, "the words: " + lt[1]
    # repeat_index and transitions
    seen: dict[str, int] = {}
    evals = [s["_vec"]["energy_norm"] for s in secs]
    for idx, s in enumerate(secs):
        root = s.get("repeat_of", s["id"])
        s["repeat_index"] = seen.get(root, 0)
        seen[root] = s["repeat_index"] + 1
        jump = abs(evals[idx] - (evals[idx - 1] if idx else 0.0))
        changed = idx > 0 and (s["type"] != secs[idx - 1]["type"] or
                               root != secs[idx - 1].get("repeat_of", secs[idx - 1]["id"]))
        s["transition"] = {"incoming_strength": 1.0 if idx == 0 else
                           _clip(0.4 * s["_bstr"] + 0.8 * jump + (0.3 if changed else 0.0))}
        s["energy"] = _clip(s["_vec"]["energy_norm"])
        s["musical_features"] = {k: _clip(v) for k, v in s["_vec"].items() if k != "energy_norm"}
        if "_lap" in s:
            s["material"] = s.pop("_lap")
        del s["_vec"], s["_bstr"]
    for idx, s in enumerate(secs):
        if idx + 1 < len(secs):
            s["transition"]["outgoing_strength"] = secs[idx + 1]["transition"]["incoming_strength"]
    for s in secs:                                              # the user's own section types win
        for t, typ in edits.get("types", {}).items():
            if abs(float(t) - s["start"]) < 0.06:
                s["type"], s["confidence"] = typ, 1.0
                s.pop("type_why", None)
                s["edited"] = True
    return secs


def lyrics_key(music: dict) -> str | None:
    """A checksum of the song's lyric lines (sections use them), or None without lyrics."""
    try:
        from .lyrics import for_music
        doc = for_music(music)
    except Exception:  # noqa: BLE001
        return None
    if not doc or not doc.get("lines"):
        return None
    return content_sha256({"lines": [[ln["start"], ln["text"]] for ln in doc["lines"]]})


def section_rules(pref_dir=None) -> dict:
    from ..common.config import music_prefs
    return dict(music_prefs(pref_dir).get("sections", {"min_bars": 8, "min_strength": 0.0}))


def section_edits_for(music: dict) -> dict:
    from ..common import songs
    sha = music.get("lineage", {}).get("audio")
    return songs.section_edits(sha) if sha else {}


def classify(music: dict, music_name: str | None = None, pref_dir=None) -> dict:
    check_version(music, "seqtool.music")
    validate(music, "seqtool.music")
    rules, edits = section_rules(pref_dir), section_edits_for(music)
    from ..common.freshness import check_inputs
    check_inputs("classify-music", music=(music, None))
    styles, character = styles_and_character(music)
    ref = {"schema": music["schema"], "schema_version": music["schema_version"],
           "content_sha256": content_sha256(music)}
    if music_name:
        ref["filename"] = music_name
    doc = envelope("seqtool.music-profile", "seqtool-classify-music",
                   {"music": ref, "sections": {"rules": rules, "edits": content_sha256(edits) if edits else None,
                                               "lyrics": lyrics_key(music)}},
                   merge_lineage(music))
    doc["profile"] = {"styles": styles, "character": character,
                      "tempo_bpm": music["analysis"]["summary"]["tempo"]["bpm"]}
    doc["sections"] = sections(music, rules, edits)
    validate(doc, "seqtool.music-profile")
    return doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool classify-music", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("music", type=paths_arg, nargs="?", default=None,
                    help="the song, or its music.json (default: the current song)")
    ap.add_argument("--output", "-o", type=paths_arg, default=None,
                    help="default: next to the music.json, named like it (song.music-profile.json)")
    ap.add_argument("--baseline", nargs="?", metavar="N", help="song N of your baseline instead (no N: each song in turn; 'baseline' lists them)")
    a = ap.parse_args(argv)
    from ..common import current
    from ..common.paths import show, sibling
    a.music = current.music_of(a.music)
    info(f"music: {show(a.music)}")
    a.output = a.output or sibling(a.music, "music-profile")
    current.remember(music=a.music)
    doc = classify(read_json(a.music), a.music.name)
    write_json(a.output, doc)
    top = sorted(doc["profile"]["styles"].items(), key=lambda kv: -kv[1])[:3]
    info("  styles: " + ", ".join(f"{k} {v:.2f}" for k, v in top))
    from .sections_cmd import HINT, table
    for line in table(doc):
        info(line)
    info(HINT.format(min_bars=section_rules().get("min_bars", 8)))
    good(f"wrote {show(a.output)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
