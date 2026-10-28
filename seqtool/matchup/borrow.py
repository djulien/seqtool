# seqtool-command: xsq-borrow | list_main | refine | what an existing xLights sequence holds, by section and row: xsq-borrow Song.xsq
# seqtool-command: borrow | main | refine | keep effects from an existing sequence as they are: borrow Arches @#3 | borrow @#3 | borrow Arches --all
# seqtool-command: unborrow | unborrow_main | refine | give borrowed effects back to seqtool: unborrow Arches @#3 | unborrow --all
# seqtool-command: open-xsq | open_main | stages | start from an existing sequence, as it is: open-xsq Song.xsq [--audio SONG] [--fill]
"""Borrowing from an existing xLights sequence (0.20.4, the user's design).

    xsq-borrow Song.xsq              what it holds, by section and row (with ids such as #3.2);
                                     it becomes the sequence 'borrow' takes from
    borrow Arches @#3                Arches' effects in section 3, exactly as the .xsq has them
    borrow #3.2                      the same, by its id in the listing
    borrow @#3                       every row in section 3
    borrow Arches --all              Arches for the whole song
    borrow @1:12-1:16                every row in that span (a moment, as a whole)
    borrow --map "Arch Group=Arches" a name in the .xsq that is called otherwise in your layout
    borrow                           what is borrowed for this song
    unborrow Arches @#3 | unborrow Arches | unborrow --all

A borrowed effect keeps xLights' own effect name, settings and colours (nothing is
translated); it goes on the row of the same name, above that row's other effects
and above the row's groups - like a pin - and seqtool plans everything else around
it as usual. 'explain' says "borrowed from Song.xsq"; the GUI marks borrowed
segments. The .xsq should be made for this song (same audio, same timing).
Borrowed effects are kept per song (songs.json); after a change the last 'run'
is repeated.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from ..common import config, songs
from ..common.log import good, info, warn


def _song():
    from ..common import current
    from ..common.canonical import read_json
    s = current.song()
    if not s or not s.get("music"):
        raise SystemExit("no song with results yet - 'run --audio SONG' first, then borrow from its .xsq")
    music = read_json(s["music"])
    prof = read_json(s["profile"]) if s.get("profile") else None
    if prof is None:
        raise SystemExit("no sections for this song yet - 'run' first")
    return s, music, prof


def _rec(music: dict) -> tuple[str, dict]:
    sha = music["lineage"]["audio"]
    return sha, dict(songs.get(sha).get("borrowed") or {})


def _names() -> set[str]:
    try:
        from ..layout import store
        cur = store.current()
        return {m["id"] for m in cur[1]["models"]} if cur else set()
    except Exception:  # noqa: BLE001
        return set()


def _map() -> dict:
    return dict(config.answer("borrow_names") or {})


def _target(element: str, known: set[str], mp: dict) -> str | None:
    if element in mp:
        return mp[element]
    if element in known or not known:
        return element
    low = {k.lower(): k for k in known}
    return low.get(element.lower())


def _clock(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def rows_by_section(seq, prof: dict) -> list[tuple[dict, list[tuple[str, list]]]]:
    """[(section, [(element, [effects overlapping it])])] in the order of the .xsq's rows."""
    order = list(dict.fromkeys(e.element for e in seq.effects if e.element_type in ("model", "submodel")))
    out = []
    for s in prof["sections"]:
        rows = []
        for el in order:
            effs = [e for e in seq.effects if e.element == el and min(e.end, s["end"]) - max(e.start, s["start"]) >= 0.25]
            if effs:
                rows.append((el, effs))
        out.append((s, rows))
    return out


def _brief(e) -> str:
    keys = [k for k in e.settings if any(w in k for w in ("Direction", "Speed", "Style", "Type"))][:2]
    extra = ", ".join(f"{k.split('_')[-1]} {e.settings[k]}" for k in keys)
    return e.name + (f" ({extra})" if extra else "")


def list_main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool xsq-borrow", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xsq", help="the xLights sequence (.xsq) of this song")
    a = ap.parse_args(argv)
    from ..adapters.xlights import xsq as xsq_mod
    from ..common.paths import expand
    f = expand(a.xsq, "file")
    if not f.is_file():
        raise SystemExit(f"not found: {f} - e.g. 'xsq-borrow ~/xLights/show/MySong.xsq'")
    s, music, prof = _song()
    seq = xsq_mod.read(f)
    sha, rec = _rec(music)
    rec["xsq"] = str(f.resolve())
    songs.update(sha, music["source"].get("filename"), borrowed=rec)
    known, mp = _names(), _map()
    unknown = sorted({e.element for e in seq.effects if e.element_type == "model" and not _target(e.element, known, mp)})
    print(f"{{head}}{f.name}{{/}}: {len(seq.effects)} effects on {len({e.element for e in seq.effects})} rows "
          f"(xLights {seq.version or '?'}); by section of {music['source'].get('filename')}:")
    for sec, rows in rows_by_section(seq, prof):
        print(f"{{head}}#{sec['index']} {sec.get('type', '?')}{{/}} {_clock(sec['start'])}-{_clock(sec['end'])}")
        for k, (el, effs) in enumerate(rows, 1):
            names = list(dict.fromkeys(_brief(e) for e in effs))
            tgt = _target(el, known, mp)
            mark = "" if tgt == el else f" -> {tgt}" if tgt else "  {warn}(not in your layout){/}"
            print(f"  {{note}}#{sec['index']}.{k:<3}{{/}} {el:<24}{mark} " + ", ".join(names[:3])
                  + (f" +{len(names) - 3}" if len(names) > 3 else ""))
    if unknown:
        warn(f"{len(unknown)} row(s) aren't in your layout: {', '.join(unknown[:6])}"
             + (" ..." if len(unknown) > 6 else "") + f" - e.g. 'borrow --map \"{unknown[0]}=YOUR NAME\"'")
    print("{note}keep some as they are:{/} {do}borrow ROW @#N{/}, {do}borrow #N.K{/}, {do}borrow @#N{/} (every row), "
          "{do}borrow ROW --all{/}, {do}borrow @1:12-1:16{/}")
    return 0


def _span(text: str, prof: dict) -> tuple[float, float, str]:
    t = text.lstrip("@")
    m = re.fullmatch(r"#(\d+)", t)
    if m:
        sec = next((x for x in prof["sections"] if x["index"] == int(m.group(1))), None)
        if sec is None:
            raise SystemExit(f"no section #{m.group(1)} - 'sections' lists them")
        return sec["start"], sec["end"], f"#{sec['index']} {sec.get('type', '')}".strip()
    m = re.fullmatch(r"([\d:.]+)-([\d:.]+)", t)
    if m:
        from .explain import parse_time
        a, b = parse_time(m.group(1), prof), parse_time(m.group(2), prof)
        if b <= a:
            raise SystemExit(f"'{text}': the end comes before the start - e.g. 'borrow @1:12-1:16'")
        return a, b, f"{_clock(a)}-{_clock(b)}"
    from .explain import parse_time
    at = parse_time(t, prof)
    sec = next((x for x in prof["sections"] if x["start"] <= at < x["end"]), prof["sections"][-1])
    return sec["start"], sec["end"], f"#{sec['index']} {sec.get('type', '')}".strip()


def take(seq, element: str, a: float, b: float) -> list[dict]:
    """The element's effects in [a, b), clipped to it, as xLights has them."""
    from ..adapters.xlights.xsq import enabled_colors
    out = []
    for e in seq.effects:
        if e.element != element or e.end <= a or e.start >= b:
            continue
        s, t = max(a, e.start), min(b, e.end)
        if t - s < 0.05:
            continue
        out.append({"name": e.name, "start": round(s, 3), "end": round(t, 3), "layer": e.layer,
                    "settings": e.settings_raw, "palette": e.palette_raw,
                    "colors": enabled_colors(e.palette)})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool borrow", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", nargs="*", help="ROW, @#N, @TIME-TIME, #N.K, or ROW @#N")
    ap.add_argument("--all", action="store_true", help="the whole song for that row")
    ap.add_argument("--map", metavar="XSQNAME=YOURNAME", help="a row of the .xsq that has another name in your layout")
    ap.add_argument("--xsq", help="borrow from this .xsq (default: the one 'xsq-borrow' listed last)")
    a = ap.parse_args(argv)
    if a.map:
        if "=" not in a.map:
            raise SystemExit("borrow --map \"NAME IN THE XSQ=YOUR NAME\"")
        old, new = (x.strip() for x in a.map.split("=", 1))
        mp = _map()
        mp[old] = new
        config.remember("borrow_names", mp)
        good(f"'{old}' in a sequence is now '{new}' in your layout")
        return 0
    s, music, prof = _song()
    sha, rec = _rec(music)
    if not a.what and not a.all:
        items = rec.get("items", [])
        if not items:
            print("nothing borrowed for this song - 'xsq-borrow Song.xsq' lists what a sequence holds")
            return 0
        print(f"borrowed from {Path(rec.get('xsq', '?')).name}:")
        for it in items:
            print(f"  {it['target']:<24} {_clock(it['start'])}-{_clock(it['end'])}  "
                  + ", ".join(dict.fromkeys(e["name"] for e in it["effects"])) + f"  ({it['where']})")
        print("{note}'unborrow ROW @#N' or 'unborrow --all' gives them back to seqtool{/}")
        return 0
    from ..adapters.xlights import xsq as xsq_mod
    src = a.xsq or rec.get("xsq")
    if not src:
        raise SystemExit("which sequence? 'xsq-borrow Song.xsq' first (it lists what it holds), or '--xsq FILE'")
    from ..common.paths import expand
    f = expand(src, "file")
    if not f.is_file():
        raise SystemExit(f"{f} isn't there any more - 'xsq-borrow NEW.xsq'")
    seq = xsq_mod.read(f)
    rows = list(dict.fromkeys(e.element for e in seq.effects if e.element_type in ("model", "submodel")))
    known, mp = _names(), _map()
    words = list(a.what)
    picks: list[tuple[str, float, float, str]] = []
    ids = [w for w in words if re.fullmatch(r"#\d+\.\d+", w)]
    spans = [w for w in words if w.startswith("@")]
    names = [w for w in words if w not in ids and w not in spans]
    for i in ids:
        sn, k = (int(x) for x in i[1:].split("."))
        sec = next((x for x in prof["sections"] if x["index"] == sn), None)
        srows = next((r for x, r in rows_by_section(seq, prof) if x["index"] == sn), None)
        if sec is None or not srows or not 1 <= k <= len(srows):
            raise SystemExit(f"no row {i} - 'xsq-borrow {f.name}' lists them")
        picks.append((srows[k - 1][0], sec["start"], sec["end"], f"#{sn} {sec.get('type', '')}".strip()))
    if names:
        for nm in names:
            el = next((r for r in rows if r == nm), None) or next((r for r in rows if r.lower() == nm.lower()), None) \
                or next((r for r in rows if _target(r, known, mp) == nm), None)
            if el is None:
                from ..common.suggest import suggest
                raise SystemExit(f"no row '{nm}' in {f.name}" + suggest(nm, rows) + f" - 'xsq-borrow {f.name}' lists them")
            if a.all or not spans:
                if not a.all:
                    raise SystemExit(f"which part? e.g. 'borrow {nm} @#3' or 'borrow {nm} --all'")
                picks.append((el, 0.0, music["audio"]["duration"], "whole song"))
            for sp in spans:
                x0, x1, where = _span(sp, prof)
                picks.append((el, x0, x1, where))
    elif spans:
        for sp in spans:
            x0, x1, where = _span(sp, prof)
            picks += [(r, x0, x1, where) for r in rows if take(seq, r, x0, x1)]
    if not picks:
        raise SystemExit("nothing to borrow - e.g. 'borrow Arches @#3' ('xsq-borrow FILE' lists the rows)")
    items = list(rec.get("items", []))
    added, skipped = 0, []
    for el, x0, x1, where in picks:
        tgt = _target(el, known, mp)
        if not tgt:
            skipped.append(el)
            continue
        effs = take(seq, el, x0, x1)
        if not effs:
            continue
        items = [it for it in items if not (it["target"] == tgt and it["start"] < x1 and it["end"] > x0)]
        items.append({"element": el, "target": tgt, "start": round(x0, 3), "end": round(x1, 3), "where": where,
                      "xsq": f.name, "effects": effs})
        added += 1
    rec.update({"xsq": str(f.resolve()), "items": sorted(items, key=lambda it: (it["start"], it["target"]))})
    songs.update(sha, music["source"].get("filename"), borrowed=rec)
    if skipped:
        warn(f"not in your layout, so not borrowed: {', '.join(sorted(set(skipped))[:6])} - "
             f"'borrow --map \"{skipped[0]}=YOUR NAME\"'")
    good(f"borrowed {added} row/span(s) from {f.name}; planning again around them ...")
    _rerun()
    return 0


def unborrow_main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool unborrow", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", nargs="*")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    s, music, prof = _song()
    sha, rec = _rec(music)
    items = rec.get("items", [])
    if a.all:
        keep = []
    else:
        spans = [w for w in a.what if w.startswith("@")]
        names = [w.lower() for w in a.what if not w.startswith("@")]
        if not names and not spans:
            raise SystemExit("unborrow ROW [@#N] | unborrow @#N | unborrow --all")
        rng = [_span(sp, prof)[:2] for sp in spans]
        keep = [it for it in items if not ((not names or it["target"].lower() in names)
                                           and (not rng or any(it["start"] < b and it["end"] > x for x, b in rng)))]
    gone = len(items) - len(keep)
    rec["items"] = keep
    songs.update(sha, music["source"].get("filename"), borrowed=rec)
    good(f"{gone} borrowed row/span(s) given back to seqtool")
    if gone:
        _rerun()
    return 0


def _rerun() -> None:
    try:
        from .reroll import rerun
        rerun()
        info("  done - 'explain ROW @TIME' says where an effect is borrowed; 'borrow' lists them")
    except SystemExit as e:
        info(f"  (not planned again: {e.code}) - 'run' to plan with them")


def apply(plans: list[dict], models: dict, borrowed: dict | None, notes: list) -> list[dict]:
    """The borrowed effects as plans of pass 'borrowed', above everything on their rows."""
    from .passes import carve, merge_spans
    items = (borrowed or {}).get("items") or []
    if not items:
        return plans
    by_id = {m["id"]: m for m in models["models"]}
    per: dict[str, list] = {}
    for it in items:
        if it["target"] not in by_id:
            notes.append(f"borrowed {it['target']} ({it['where']}): not in this layout - 'unborrow {it['target']}'")
            continue
        for e in it["effects"]:
            per.setdefault(it["target"], []).append({
                "start": e["start"], "end": e["end"], "section": it["where"],
                "selected": {"effect": e["name"], "family": "borrowed", "score": 1.0},
                "parameters": {}, "palette_colors": e.get("colors") or None, "borrowed": True,
                "xlights": {"name": e["name"], "settings": e["settings"], "palette": e["palette"]},
                "score_breakdown": {"final": 1.0},
                "reasons": [f"borrowed from {it.get('xsq', 'the .xsq')}: {e['name']} as it is there ({it['where']})"]})
    out = list(plans)
    for tid, segs in per.items():
        segs.sort(key=lambda g: g["start"])
        spans = merge_spans([(g["start"], g["end"]) for g in segs])
        for p in out:                                   # the row's own effects give way there
            if p["target"] == tid and not p.get("borrowed_plan"):
                p["segments"] = carve(p["segments"], spans)
        clean = []
        for g in segs:                                  # one layer: overlapping effects (other xLights layers) cut
            if clean and g["start"] < clean[-1]["end"]:
                g = {**g, "start": clean[-1]["end"]}
                if g["end"] - g["start"] < 0.05:
                    continue
            if not g.get("palette_colors"):
                g.pop("palette_colors", None)
            clean.append(g)
        own = [p for p in out if p["target"] == tid]
        layer = 1 + max(p.get("layer", 0) for p in own) if own else 0
        out.append({"target": tid, "target_kind": by_id[tid]["kind"], "layer": layer, "pass": "borrowed",
                    "borrowed_plan": True, "segments": clean})
    return out


if __name__ == "__main__":
    sys.exit(main())


def _media(f: Path, seq_xml) -> Path | None:
    """The .xsq's audio: its mediaFile as written, the same name beside the .xsq, or in a
    folder songs were used from."""
    txt = (seq_xml.findtext("head/mediaFile") or "").strip()
    if not txt:
        return None
    p = Path(txt.replace("\\", "/"))
    for cand in (p, f.parent / p.name, f.parent.parent / p.name):
        if cand.is_file():
            return cand
    from ..common import current
    return current.relocate(Path.cwd() / p.name)


def open_main(argv=None) -> int:
    """seqtool open-xsq Song.xsq [--audio SONG] [--fill]

    Start from an existing xLights sequence, as it is (0.21.7, the user's design): its audio
    is analysed (sections, beats - for pins, reactions and the GUI), every row of the .xsq is
    borrowed for the whole song, and seqtool adds no effects of its own. Pin, promote, react
    and borrow / unborrow as usual; 'xlights-export' writes it again.

        open-xsq Song.xsq                 the audio is the one the .xsq names (or beside it)
        open-xsq Song.xsq --audio s.mp3   when it can't be found
        open-xsq --fill                   let seqtool plan the rows the .xsq leaves empty
        open-xsq --as-is                  back to the .xsq alone
    """
    import xml.etree.ElementTree as ET
    ap = argparse.ArgumentParser(prog="seqtool open-xsq", description=open_main.__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xsq", nargs="?")
    ap.add_argument("--audio", help="the song's audio, when the .xsq's can't be found")
    ap.add_argument("--fill", action="store_true", help="seqtool plans the rows (and times) the .xsq leaves empty")
    ap.add_argument("--as-is", action="store_true", help="the .xsq alone again (no effects of seqtool's own)")
    a = ap.parse_args(argv)
    from ..common.paths import expand, show
    if a.fill or a.as_is:
        if a.xsq is None:
            s, music, prof = _song()
            sha, rec = _rec(music)
            if not rec.get("items"):
                raise SystemExit("no .xsq opened for this song - 'open-xsq Song.xsq'")
            rec["only"] = bool(a.as_is)
            songs.update(sha, music["source"].get("filename"), borrowed=rec)
            good("seqtool now plans the rows the .xsq leaves empty" if a.fill else "back to the .xsq as it is")
            _rerun()
            return 0
    if not a.xsq:
        raise SystemExit("open-xsq Song.xsq  (e.g. 'open-xsq ~/xLights/show/MySong.xsq')")
    f = expand(a.xsq, "file")
    if not f.is_file():
        raise SystemExit(f"not found: {f} - e.g. 'open-xsq ~/xLights/show/MySong.xsq'")
    audio = expand(a.audio, "file") if a.audio else _media(f, ET.parse(f).getroot())
    if audio is None or not Path(audio).is_file():
        raise SystemExit(f"{f.name} names no audio that can be found here - e.g. 'open-xsq {show(f, typed=True)} "
                         "--audio ~/Music/song.mp3'")
    info(f"{f.name}: its audio is {show(audio)}; analysing it (sections, beats) ...")
    from ..__main__ import discover
    import importlib
    mod, func, _, _ = discover()["run"]
    getattr(importlib.import_module(mod), func)(["--audio", str(audio)])
    from ..adapters.xlights import xsq as xsq_mod
    s, music, prof = _song()
    seq = xsq_mod.read(f)
    sha, rec = _rec(music)
    known, mp = _names(), _map()
    rows = list(dict.fromkeys(e.element for e in seq.effects if e.element_type in ("model", "submodel")))
    end = music["audio"]["duration"]
    items, skipped = [], []
    for el in rows:
        tgt = _target(el, known, mp)
        if not tgt:
            skipped.append(el)
            continue
        effs = take(seq, el, 0.0, end)
        if effs:
            items.append({"element": el, "target": tgt, "start": 0.0, "end": round(end, 3), "where": "whole song",
                          "xsq": f.name, "effects": effs})
    rec.update({"xsq": str(f.resolve()), "items": items, "only": not a.fill})
    songs.update(sha, music["source"].get("filename"), borrowed=rec)
    if skipped:
        warn(f"{len(skipped)} row(s) aren't in your layout: {', '.join(skipped[:6])}"
             + (" ..." if len(skipped) > 6 else "") + f" - 'borrow --map \"{skipped[0]}=YOUR NAME\"', then open it again")
    good(f"opened {f.name} as it is: {len(items)} row(s), {sum(len(i['effects']) for i in items)} effects"
         + ("; seqtool plans the empty rows too" if a.fill else ""))
    tracks = sorted({e.element for e in seq.effects if e.element_type == "timing"})
    lyr = [t for t in tracks if any(e.element == t and e.element_type == "timing" and re.search(r"[A-Za-z]{2}", e.label or "")
                                    for e in seq.effects)]
    if lyr and not (songs.get(sha).get("lyrics") or {}).get("lines"):
        info(f"  '{lyr[0]}' has words: 'lyrics from-xsq' takes the lyrics from it (step 4)")
    if tracks:
        info(f"  {len(tracks)} timing track(s): {', '.join(tracks[:5])}{' ...' if len(tracks) > 5 else ''} - rows in the GUI; "
             "click a mark to split or move a section there ('sections from-timing TRACK @#N')")
    mine = songs.get(sha)
    n_p, n_r = len(mine.get("pins") or []), len(mine.get("react") or [])
    if n_p or n_r:
        info(f"  kept your {n_p} pin(s) and {n_r} reaction(s) for this song on top of it - 'unpin --all' / "
             "'react ROW off --song' remove them")
    _rerun()
    info("  'open-xsq --fill' lets seqtool plan the rows it leaves empty; 'xlights-export' writes the sequence")
    return 0
