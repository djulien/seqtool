# seqtool-command: xlights-export | main | stages | matchup -> .xsq for xLights
"""xLights output adapter: matchup plan -> .xsq

    seqtool xlights-export [--matchup FILE | --out DIR] [--audio FILE] [-o song.xsq]
    seqtool xlights-export --checks [--prop P] [--group G] [--submodel S] [--audio SONG]

Uses what the kit wizard learned for your xLights version (stored effect
names, default settings, which setting each parameter moves, palette format)
and the training file as a template. Adds timing tracks (seqtool-sections,
seqtool-bars, seqtool-beats, and seqtool-lyrics when there are lyrics), snaps every
time to the sequence frame interval, then reads the result back and checks it.

--checks writes the verification sequence instead: one labelled slot per export
feature to look at in xLights (Fill, glide steps, VU Meter, a submodel row, a top
group row, dark over a group), on props from your stored layout.
"""
from __future__ import annotations

import argparse
import copy
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from ...common.canonical import read_json
from ...common.log import good, info, warn
from ...common.paths import show
from ...common.vocab import canon, lit
from . import encoding as enc_mod
from . import xsq
from ...music.rhythm import beat_numbers
from ...common.paths import arg as paths_arg

FALLBACK_HEAD = ("version", "author", "author-email", "author-website", "song", "artist", "album",
                 "MusicURL", "comment", "sequenceTiming", "sequenceType", "mediaFile",
                 "sequenceDuration", "imageDir")


GLIDE_STEP = 0.1          # seconds per step when a keyframe glide is written as steps
GLIDE_MAX = 12            # at most this many steps per glide piece



_PICS: dict = {}


def picture_path(name: str, notes: list) -> str:
    """A picture's file as xLights needs it (a full path): as given when it is one; else found in
    the show folder (or below it) by name. Said when it isn't there."""
    if name in _PICS:
        return _PICS[name]
    from ...common.showfiles import bring_in, repin
    new = bring_in(str(name), "picture")                  # 0.24.47: outside the show folder -> a copy in it
    if new != str(name):
        repin(str(name), new)
        _PICS[name] = new
        return new
    p = Path(str(name)).expanduser()
    if p.is_absolute():
        if not p.exists():
            n = f"picture {name}: not found - xLights shows nothing for it"
            if n not in notes:
                notes.append(n)
        return str(p)
    if name in _PICS:
        return _PICS[name]
    from ...layout import store
    src = store.source_info()
    show_dir = Path(src["path"]).parent if src else Path.cwd()
    hit = show_dir / name if (show_dir / name).exists() else next(iter(sorted(show_dir.rglob(Path(name).name))), None)
    if hit is None:
        n = (f"picture {name}: not in the show folder {show_dir} - put it there (or give its full path); "
             "xLights shows nothing for it until then")
        if n not in notes:
            notes.append(n)
        hit = show_dir / name
    _PICS[name] = str(Path(hit).resolve())
    return _PICS[name]

def _at(pts, t: float) -> float:
    """A curve's value at t (0..1), straight between its points."""
    if t <= pts[0][0]:
        return pts[0][1]
    for (t0, y0), (t1, y1) in zip(pts, pts[1:]):
        if t <= t1:
            return y0 if t1 <= t0 else y0 + (y1 - y0) * (t - t0) / (t1 - t0)
    return pts[-1][1]


def _ms(t: float, frame_ms: int) -> int:
    return int(round(t * 1000 / frame_ms)) * frame_ms


def _frame_ms(timing: str | None) -> int:
    try:
        return int(str(timing).split()[0])
    except (ValueError, IndexError, AttributeError):
        return 50


def _skeleton(enc: enc_mod.Encoding) -> ET.Element:
    if enc.reference and enc.reference.exists():
        root = ET.parse(enc.reference).getroot()
    else:
        root = ET.Element("xsequence", {"BaseChannel": "0", "ChanCtrlBasic": "0", "ChanCtrlColor": "0",
                                        "FixedPointTiming": "1", "ModelBlending": "true"})
        head = ET.SubElement(root, "head")
        for t in FALLBACK_HEAD:
            ET.SubElement(head, t)
        for t in ("nextid", "Jukebox", "ColorPalettes", "EffectDB", "DataLayers", "DisplayElements",
                  "ElementEffects", "lastView", "TimingTags"):
            ET.SubElement(root, t)
    return root


def build(matchup: dict, music: dict, profile: dict, models: dict, audio: Path | None,
          enc: enc_mod.Encoding, view_order: list[str] | None = None,
          timing: list[str] | None = None, lyrics: dict | None = None,
          phonemes: bool = True) -> tuple[ET.ElementTree, list[str]]:
    notes: list[str] = []
    root = _skeleton(enc)
    head = root.find("head")
    frame = _frame_ms(enc.timing or (head.findtext("sequenceTiming") if head is not None else None))
    dur = music["audio"]["duration"]

    def set_head(tag, val):
        el = head.find(tag)
        if el is None:
            el = ET.SubElement(head, tag)
        el.text = val
    set_head("version", enc.version)
    set_head("sequenceType", "Media" if audio else "Animation")
    set_head("mediaFile", str(audio.resolve()) if audio else "")
    set_head("sequenceDuration", f"{_ms(dur, frame) / 1000:.3f}".rstrip("0").rstrip("."))
    set_head("sequenceTiming", f"{frame} ms")
    st = matchup.get("settings", {})
    ovr = ", ".join(f"{k}={v}" for k, v in sorted(st.get("seed_overrides", {}).items()))
    set_head("comment", f"generated by seqtool from {matchup['source']['music'].get('filename', 'audio')}, "
                        f"seed {st.get('seed')}" + (f" (overrides {ovr})" if ovr else ""))

    views = ""
    old_disp = root.find("DisplayElements")
    if old_disp is not None:
        for e in old_disp.findall("Element"):
            if e.get("type") == "timing" and e.get("views"):
                views = e.get("views")
                break
    for tag in ("ColorPalettes", "EffectDB", "DisplayElements", "ElementEffects"):
        old = root.find(tag)
        if old is None:
            old = ET.SubElement(root, tag)
        for c in list(old):
            old.remove(c)
    pal_el, db_el = root.find("ColorPalettes"), root.find("EffectDB")
    disp_el, eff_el = root.find("DisplayElements"), root.find("ElementEffects")
    pals: list[str] = []
    db: list[str] = []

    def idx(lst, el, text):
        if text not in lst:
            lst.append(text)
            ET.SubElement(el, el.tag[:-1] if el.tag.endswith("s") else "Effect").text = text
        return lst.index(text)

    # -- timing tracks
    secs = profile["sections"]
    beats = music["analysis"]["events"]["beats"]
    downs = music["analysis"]["events"].get("downbeats", [])
    tracks = {
        "seqtool-sections": [(s["start"], s["end"], f"#{s['index']} {s.get('type', '')}".strip()) for s in secs],
        "seqtool-bars": [(d["time"], (downs[i + 1]["time"] if i + 1 < len(downs) else dur), str(i + 1))
                         for i, d in enumerate(downs)],
        "seqtool-beats": [(b["time"], (beats[i + 1]["time"] if i + 1 < len(beats) else dur), str(n))
                          for i, (b, n) in enumerate(zip(beats, beat_numbers(beats, downs)))],
    }
    from ...music.lyrics import for_music
    lyr = lyrics if lyrics is not None else for_music(music)
    if lyr and lyr.get("lines"):
        from ...matchup.engine import voice_track
        from ...music.voices import lines_for, names as voice_names
        d = None
        # 0.24.0: one track for all the words, and one per voice ({BOB} ... in the lyrics) holding that
        # voice's words and ALL's - a face with a voice follows its own
        for voice in [None] + voice_names(lyr):
            lines = lyr["lines"] if voice is None else lines_for(lyr, voice)
            if not lines:
                continue
            tname = voice_track(voice, lyr)
            words = [w for ln in lines for w in ln.get("words", [])]
            tracks[tname] = [[(ln["start"], ln["end"], ln["text"]) for ln in lines]] + \
                ([[(w["start"], w["end"], w["text"]) for w in words]] if words else [])
            if words and phonemes and "lyrics" in (timing if timing is not None else ["lyrics"]):
                # third layer: mouth shapes for singing faces (0.19.1)
                from ...music.phonemes import Dictionary, describe, for_words
                d = d or Dictionary()
                if d.tables or d.words:
                    marks, rep = for_words(words, d, frame / 1000)
                    if marks:
                        tracks[tname].append(marks)
                    if voice is None:
                        notes.extend("__phon__" + x for x in describe(rep, d))
                elif voice is None:                     # guessing every word from its spelling is not worth it
                    notes.append("__phon__{warn}no phoneme layer:{/} no pronouncing dictionary - 'lyrics phonemes' "
                                 "offers to download CMUdict ('pref faces.phonemes.dictionaries' names others)")
    wanted = ["sections", "bars", "beats", "lyrics"] if timing is None else timing
    tracks = {k: v for k, v in tracks.items() if k.replace("seqtool-", "").split("-")[0] in wanted}
    for name, marks in tracks.items():
        attrs = {"collapsed": "0", "type": "timing", "name": name, "visible": "1", "active": "0"}   # 0.24.22: not all selected on opening
        if views:
            attrs["views"] = views
        ET.SubElement(disp_el, "Element", attrs)
        el = ET.SubElement(eff_el, "Element", {"type": "timing", "name": name})
        for layer_marks in (marks if marks and isinstance(marks[0], list) else [marks]):   # lyrics: phrases, words
            layer = ET.SubElement(el, "EffectLayer")
            last_end = 0
            for a, b, label in layer_marks:
                s_ms, e_ms = max(_ms(a, frame), last_end), _ms(b, frame)
                if e_ms <= s_ms:
                    continue
                ET.SubElement(layer, "Effect", {"label": label, "startTime": str(s_ms), "endTime": str(e_ms)})
                last_end = e_ms

    # -- models / groups
    known = {m["id"]: m for m in models["models"]}
    plans = [p for p in matchup["plans"] if p["segments"]]
    order = {n: i for i, n in enumerate(view_order or [])}
    plans.sort(key=lambda p: (order.get(p["target"], 10 ** 6), matchup["plans"].index(p)))
    pal_map = {k: v["colors"] for k, v in matchup["palettes"].items()}
    next_id = 1
    unsupported: dict[str, int] = {}
    pmap = enc_mod.param_map()
    bpm = music["analysis"]["summary"]["tempo"]["bpm"] or 120.0
    beat_s = 60.0 / bpm
    by_target: dict[str, list[dict]] = {}
    for p in plans:
        by_target.setdefault(p["target"], []).append(p)
    # element rows: submodel targets live inside their parent's row; xLights lets lower rows
    # win where rows overlap, so top-pass groups go first and detail groups last
    rows: dict[str, dict] = {}
    for name, tplans in by_target.items():
        kind = known.get(name, {}).get("kind", "model")
        if kind == "submodel":
            parent = known[name].get("parent") or name.split("/", 1)[0]
            rows.setdefault(parent, {"own": [], "subs": {}, "rank": 1})["subs"][name.split("/", 1)[1]] = tplans
        else:
            r = rows.setdefault(name, {"own": [], "subs": {}, "rank": 1})
            r["own"] = tplans
            passes = {p.get("pass", "main") for p in tplans}
            r["rank"] = 0 if passes == {"top"} else 2 if passes <= {"detail", "pin", "face", "base", "borrowed", "place", "choreo"} else 1   # pin / face / moment rows: over their group
    row_order = sorted(rows, key=lambda n: (rows[n]["rank"], [list(by_target).index(x) for x in by_target
                                                               if x == n or x.startswith(n + "/")][0]))
    sub_tag = (enc.submodel or {}).get("tag", "SubModelEffectLayer")
    sub_attrs = (enc.submodel or {}).get("attrs", {})
    sub_disp = (enc.submodel or {}).get("display", [])
    if any(r["subs"] for r in rows.values()) and not enc.submodel:
        notes.append("submodel rows written in the usual xLights form (not learned yet - xlights-kit --update)")
    fallback: dict[tuple, int] = {}
    dark_missing = [0]
    area_missing = [0]

    def glides(segments):
        """Glides over an effect ({"ramp": [a, b]}, {"curve": [[t, y], ...]}; keyframes, choreographies):
        a setting the kit can give a value curve keeps it - one effect (0.24.48); a curve it can only
        write as ramps is split at its points; the rest step from a to b in short effects, one per
        GLIDE_STEP seconds (at least one frame each)."""
        from .encoding import curve_points
        for seg in segments:
            gen = canon(seg["selected"]["effect"])
            pars = dict(seg.get("parameters", {}))
            curv = {k: curve_points(v, seg["start"], seg["end"]) for k, v in pars.items() if curve_points(v) is not None}
            for k, pts in curv.items():                   # each part of a pin's glide: its own share of it
                if isinstance(pars[k], dict) and pars[k].get("over"):
                    pars[k] = {"curve": [list(x) for x in pts]} if len(pts) > 2 else {"ramp": [pts[0][1], pts[-1][1]]}
            seg = {**seg, "parameters": pars}
            if not curv:
                yield seg
                continue
            ok = {k for k in curv if enc.can_curve(gen, k, pmap)}
            multi = enc.curves is not None and enc.curves.custom is not None
            if all(k in ok and (len(curv[k]) == 2 or multi) for k in curv):
                yield seg
                continue
            dur = seg["end"] - seg["start"]
            cuts = sorted({t for k in ok for t, _ in curv[k]} | {0.0, 1.0}) if ok and not (set(curv) - ok) else None
            if cuts is None:
                n = max(1, min(GLIDE_MAX, int(round(dur / max(GLIDE_STEP, frame / 1000)))))
                cuts = [i / n for i in range(n + 1)]
            for a, b in zip(cuts, cuts[1:]):
                if b - a < 1e-6:
                    continue
                vals = {}
                for k, pts in curv.items():
                    ya, yb = _at(pts, a), _at(pts, b)
                    vals[k] = {"ramp": [round(ya, 4), round(yb, 4)]} if k in ok else round(_at(pts, (a + b) / 2), 4)
                yield {**seg, "start": seg["start"] + dur * a, "end": seg["start"] + dur * b,
                       "parameters": {**pars, **vals}}

    def write(layer_el, p, last_end):
        nonlocal next_id
        for seg in glides(p["segments"]):
            xl = seg.get("xlights")
            if xl:                                     # borrowed from an .xsq: written as it was there (0.20.4)
                s_ms, e_ms = max(_ms(seg["start"], frame), last_end), _ms(seg["end"], frame)
                if e_ms <= s_ms:
                    continue
                ref = idx(db, db_el, xl.get("settings", ""))
                pal = idx(pals, pal_el, xl.get("palette", "") or enc.palette(seg.get("palette_colors") or ["#FFFFFF"]))
                ET.SubElement(layer_el, "Effect", {
                    "ref": str(ref), "name": xl["name"], "id": str(next_id), "startTime": str(s_ms),
                    "endTime": str(e_ms), "palette": str(pal)})
                next_id += 1
                last_end = e_ms
                continue
            gen = canon(seg["selected"]["effect"])
            if gen in ("transparent", "choreo"):          # choreo: its parts are plans of their own (0.24.47)
                continue
            if gen == "dark" and not enc.supports("dark"):   # Off not learned yet: nothing is written
                dark_missing[0] += 1
                continue
            if not enc.supports(gen) and gen in ("picture",):   # 0.24.46: yours - no stand-in for it
                unsupported[gen] = unsupported.get(gen, 0) + 1
                continue
            if not enc.supports(gen):                   # not learned yet: the best alternative that is
                alt = next((x["effect"] for x in seg.get("alternatives", [])
                            if lit(x["effect"]) and enc.supports(x["effect"])), None)
                if alt is None:
                    unsupported[gen] = unsupported.get(gen, 0) + 1
                    continue
                fallback[(gen, alt)] = fallback.get((gen, alt), 0) + 1
                gen = alt
                params = {}
            else:
                params = seg.get("parameters", {})
            if gen == "picture" and params.get("file"):  # 0.24.46: a file in the show folder -> its full path
                params = {**params, "file": picture_path(params["file"], notes)}
            stored, settings = enc.effect(gen, params, seg["end"] - seg["start"], beat_s, pmap,
                                          yours=set(seg.get("yours") or ()))
            if params.get("area") and enc.area(params["area"]) is None:
                area_missing[0] += 1
            s_ms, e_ms = max(_ms(seg["start"], frame), last_end), _ms(seg["end"], frame)
            if e_ms <= s_ms:
                continue
            ref = idx(db, db_el, settings)
            colors = seg.get("palette_colors") or pal_map.get(seg.get("palette", "base"), ["#FFFFFF"])
            pal = idx(pals, pal_el, enc.palette(colors))
            ET.SubElement(layer_el, "Effect", {
                "ref": str(ref), "name": stored, "id": str(next_id), "startTime": str(s_ms),
                "endTime": str(e_ms), "palette": str(pal)})
            next_id += 1
            last_end = e_ms
        return last_end

    for name in row_order:
        r = rows[name]
        origin = known.get(name, {}).get("origin", {})
        if origin.get("adapter") != "xlights":
            notes.append(f"{name} is not an xLights model (layout not imported from xLights)")
        d = ET.SubElement(disp_el, "Element", {"collapsed": "0", "type": "model", "name": name, "visible": "1"})
        for sname in r["subs"]:
            for tag, attrs in sub_disp[:1]:
                ET.SubElement(d, tag, {**attrs, "name": sname})
        el = ET.SubElement(eff_el, "Element", {"type": "model", "name": name})
        tplans = r["own"]
        n_layers = max([p.get("layer", 0) for p in tplans] + [0]) + 1
        # xLights draws the first EffectLayer on top, so generic layer 0 (normal)
        # goes last and higher generic layers (enhance, react --over) go above it
        layers = [ET.SubElement(el, "EffectLayer") for _ in range(n_layers)][::-1]
        for lay_i in sorted({p.get("layer", 0) for p in tplans}):  # plans sharing a layer: one time order (0.21.4)
            segs = sorted((g for p in tplans if p.get("layer", 0) == lay_i for g in p["segments"]),
                          key=lambda g: g["start"])
            write(layers[lay_i], {"segments": segs}, 0)
        for sname, splans in r["subs"].items():
            for p in sorted(splans, key=lambda p: p.get("layer", 0)):
                sl = ET.SubElement(el, sub_tag, {**sub_attrs, "name": sname})
                write(sl, p, 0)
    for (gen, alt), n in sorted(fallback.items()):
        notes.append(f"{n} '{gen}' segment(s) shown as '{alt}' (the next best choice): '{gen}' is not learned "
                     "yet - xlights-kit --update")
    for n_ in enc.notes:
        if n_ not in notes:
            notes.append(n_)
    for gen, n in sorted(unsupported.items()):
        notes.append(f"{n} '{gen}' segment(s) skipped: not learned by the kit")
    if area_missing[0]:
        notes.append(f"{area_missing[0]} effect(s) with an area (a face's place on the prop) cover the whole prop: "
                     "the kit hasn't learned the sub-buffer yet - 'xlights-kit --update' (three short steps)")
    if dark_missing[0]:
        notes.append(f"{dark_missing[0]} 'dark' segment(s) left empty (transparent): xLights' Off effect is not "
                     "learned yet - 'xlights-kit --update'")
    if tracks:
        notes.append("__views__:" + views)
    ET.indent(root, space="  ")
    return ET.ElementTree(root), notes



def check(path: Path, enc: enc_mod.Encoding, models: dict, duration: float, borrowed: set | None = None) -> list[str]:
    """Read the written file back and check what xLights will rely on."""
    problems = []
    try:
        x = xsq.read(path)
    except ET.ParseError as e:
        return [f"not valid XML: {e}"]
    names = {e["stored_name"] for e in enc.effects.values()} | set(borrowed or ())   # borrowed: xLights' own names
    dark_name = enc.effects.get("dark", {}).get("stored_name")
    known = {m["id"] for m in models["models"]}
    for e in x.effects:
        if e.element_type != "model":
            continue
        if e.name not in names:
            problems.append(f"{e.element}: unknown effect name {e.name}")
        if not e.settings and e.name != dark_name:          # xLights' Off effect has nothing to set
            problems.append(f"{e.element}: effect at {e.start:.2f}s has no settings")
        if e.end > duration + 0.06:
            problems.append(f"{e.element}: effect ends after the song ({e.end:.2f}s)")
        if e.element not in known:
            problems.append(f"{e.element}: not a model or group in the layout")
    per: dict[tuple, list] = {}
    for e in x.effects:
        per.setdefault((e.element, e.layer), []).append((e.start, e.end))
    for (el, layer), spans in per.items():
        spans.sort()
        for (a1, b1), (a2, b2) in zip(spans, spans[1:]):
            if a2 < b1 - 1e-6:
                problems.append(f"{el} layer {layer + 1}: overlapping effects at {a2:.2f}s")
    return problems


def export(matchup_path: Path, out: Path | None = None, audio: Path | None = None,
           version: str | None = None, timing: list[str] | None = None) -> Path | None:
    folder = matchup_path.parent
    m = read_json(matchup_path)
    src = m["source"]
    music = read_json(folder / src["music"]["filename"])
    profile = read_json(folder / src["music_profile"]["filename"])
    models = read_json(folder / src["models"]["filename"])
    from . import kit
    if version is None:
        kit.offer("export")
    enc = enc_mod.find(version)
    if enc is None:
        warn("nothing learned yet for any xLights version - run {do}seqtool xlights-kit{/} first")
        return None
    status, msg = enc.compatibility()
    if status == "retrain":
        warn(msg)
        return None
    if status == "older":
        info(f"  training data: {msg}")
    if audio is None:
        fn = music["source"].get("filename")
        for d in (folder, folder.parent, Path.cwd()):       # results are in <song>-seqtool/ (0.19.9)
            if fn and (d / fn).exists():
                audio = d / fn
                break
    if audio is None:                                       # the song as 'run' / 'analyze-music' was given it (0.21.4)
        try:
            from ...common import config, current
            sha = (music.get("lineage") or {}).get("audio")
            la = config.answer("last_audio")
            if la and Path(la).exists() and (not sha or Path(la).name == fn):
                audio = Path(la)
            elif fn and sha:                                # a folder songs were used from, same audio
                audio = current.relocate(Path(la or ".").with_name(fn), sha)
        except Exception:  # noqa: BLE001
            audio = None
    if audio is None:
        warn("audio file not found next to the results; the sequence will have no media "
             "(e.g. 'xlights-export --audio song.mp3')")
    layout = folder / "layout.json"
    view = None
    if layout.exists():
        lay = read_json(layout)
        view = lay.get("views", {}).get(lay.get("default_view", ""), None)
    if timing is None:
        from ...common.config import load as load_pref
        timing = load_pref("xlights").get("timing_tracks", ["sections", "bars", "beats", "lyrics"])
    tree, notes = build(m, music, profile, models, audio, enc, view, timing)
    stem = (src["music"].get("filename") or "song").replace(".music.json", "")
    out = out or folder / f"{stem}.xsq"
    tree.write(out, encoding="UTF-8", xml_declaration=True)
    problems = check(out, enc, models, music["audio"]["duration"],
                     {g["xlights"]["name"] for p in m["plans"] for g in p["segments"] if g.get("xlights")})
    views = next((n[len("__views__:"):] for n in notes if n.startswith("__views__:")), None)
    notes = [n for n in notes if not n.startswith("__views__:")]
    for n in [n for n in notes if n.startswith("__phon__")]:
        info(f"  {n[len('__phon__'):]}")
    notes = [n for n in notes if not n.startswith("__phon__")]
    for n in notes + [f"kit: {p}" for p in enc.problems()]:
        info(f"  note: {n}")
    for p in problems[:20]:
        warn(f"  {p}")
    n_eff = sum(1 for e in xsq.read(out).effects if e.element_type == "model")
    (good if not problems else warn)(
        f"wrote {show(out)}: {n_eff} effects for xLights {enc.version}"
        + ("" if not problems else f", {len(problems)} problem(s)"))
    if views is not None:
        names = ", ".join(t for t in xsq.read(out).timing_tracks if t.startswith("seqtool-"))
        if views:
            info(f"  timing tracks {names} added to your views: {views.replace(',', ', ')}")
            info("  {note}(if they don't show, add them in xLights: View > Display Elements){/}")
        else:
            info(f"  {{do}}reminder: in xLights, add the timing tracks {names} to your Master View "
                 "(View > Display Elements){/} - they are not shown until you do")
    sha = (m.get("lineage") or {}).get("audio")
    if sha:                                            # 0.24.50: the song's score, beside its sequence
        try:
            from ...matchup.score_cmd import write as write_score
            f = write_score(sha, profile, out.with_name(f"{Path(out).stem}.score.txt"))
            info(f"  {{note}}the song's score (its terms and directions): {show(f)}{{/}}")
        except Exception as e:  # noqa: BLE001
            info(f"  {{note}}(the song's score wasn't written: {e}){{/}}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool xlights-export", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--matchup", type=paths_arg, help="matchup file (default: newest in --out)")
    g.add_argument("--out", type=paths_arg, help="results folder (default: seqtool-out or seqtool-demo)")
    ap.add_argument("--audio", type=paths_arg)
    ap.add_argument("--xlights-version", help="use the kit learned for this version")
    ap.add_argument("-o", "--output", type=paths_arg)
    ap.add_argument("--timing", default=None,
                    help="timing tracks to add: comma list of sections,bars,beats,lyrics, or 'none' "
                         "(default: xlights.timing_tracks preference)")
    ap.add_argument("--checks", action="store_true",
                    help="write the verification sequence (seqtool-checks.xsq) for your stored layout")
    ap.add_argument("--prop", help="--checks: the prop to use (default: the biggest in the top group)")
    ap.add_argument("--group", help="--checks: the group to use (default: the top group)")
    ap.add_argument("--submodel", help="--checks: the submodel to use, as Model/Sub (default: one of the prop's)")
    from ...music.phonemes import add_arg, use_arg
    add_arg(ap)
    a = ap.parse_args(argv)
    use_arg(a.dictionary)
    if a.checks:
        from .checks import write
        return 0 if write(a.output, a.audio, a.xlights_version, a.prop, a.group, a.submodel) else 1
    from ...matchup.explain import find_matchup
    path = a.matchup or find_matchup(a.out)
    if path is None:
        raise SystemExit("no matchup found - run 'seqtool run' first")
    timing = None if a.timing is None else ([] if a.timing == "none" else [t.strip() for t in a.timing.split(",")])
    return 0 if export(path, a.output, a.audio, a.xlights_version, timing) else 1


if __name__ == "__main__":
    sys.exit(main())
