"""How well does section detection match the sections you fixed by hand - and which
detection settings would match them best?  ('sections score', 'sections tune')

Your fixes ('sections merge/split/move/type/import') are kept per song in songs.json.
For every song you fixed, detection is run again WITHOUT your fixes and compared:

  boundaries   a detected boundary counts as right when one of yours is within the
               tolerance (one bar, at least 1 s); precision = right / detected,
               recall = right / yours, F1 combines both
  types        for each section you typed yourself: does detection give that section
               the same type? (custom names compare by what they map to:
               music.section_types). Measured on YOUR boundaries, so a wrong boundary
               doesn't also count as a wrong type.

'sections tune' tries combinations of the detection settings (sections.method,
min_bars, min_strength, novelty_weight) on all those songs and shows the best;
it asks before saving them as your defaults.
"""
from __future__ import annotations

import itertools
from glob import glob
from pathlib import Path

from ..common import config, songs
from ..common.canonical import read_json
from ..common.paths import legacy_name, seqtool_folder, show

GRID = {"method": ["combined", "novelty", "laplacian"], "min_bars": [4, 6, 8, 12, 16],
        "min_strength": [0.0, 0.1, 0.2, 0.3], "novelty_weight": [0.5, 0.8, 1.0], "vocal_entry": [0.0, 0.6, 0.8], "lyrics": [0.0, 1.0],
        "lyric_min_bars": [2, 8]}


def _music_for(audio: Path) -> Path | None:
    for f in (seqtool_folder(audio) / f"{audio.stem}.music.json", legacy_name(audio, "music")):
        if f.exists():
            return f
    return None


def _known_audio() -> list[Path]:
    """Songs seqtool has seen: in baselines, the last song, and folders of fixes recorded with their analysis."""
    audios: list[Path] = []
    for bf in sorted((config.user_dir() / "baselines").glob("*.json")):
        try:
            audios += [Path(s) for s in read_json(bf).get("songs", {})]
        except Exception:  # noqa: BLE001
            pass
    for key in ("last_audio",):
        v = config.answer(key)
        if v:
            audios.append(Path(v))
    return list(dict.fromkeys(audios))


def fixed_songs(extra: list[Path] | None = None) -> tuple[list[tuple[Path, dict, dict]], list[str]]:
    """([(music.json path, music, edits)], [names of fixed songs whose analysis wasn't found]).
    Every song with section fixes (songs.json) is looked for: by the analysis path recorded
    with the fix (since 0.17.2), the songs you name, and next to every song seqtool knows
    (baselines, the last song) - songs of a show usually share a folder."""
    known = list(dict.fromkeys(list(extra or []) + _known_audio()))
    folders = list(dict.fromkeys(a.parent for a in known if a.parent.exists()))
    musics = [m for m in (_music_for(a) for a in known if a.exists()) if m]
    fixed = {sha: rec for sha, rec in songs._all().items() if (rec.get("sections") or {}).get("boundaries")}
    for sha, rec in fixed.items():
        if rec.get("music") and Path(rec["music"]).exists():
            musics.append(Path(rec["music"]))
        elif rec.get("name"):
            for d in folders:
                m = _music_for(d / rec["name"])
                if m:
                    musics.append(m)
    best: dict[str, tuple] = {}                    # per song: the newest analysis found
    for mp in dict.fromkeys(musics):
        try:
            m = read_json(mp)
        except Exception:  # noqa: BLE001
            continue
        sha = m.get("lineage", {}).get("audio")
        if sha not in fixed:
            continue
        key = _vkey(m)
        if sha not in best or key > best[sha][0]:
            best[sha] = (key, mp, m)
    out = [(mp, m, songs.section_edits(sha)) for sha, (_, mp, m) in best.items()]
    missing = [rec.get("name", sha[:12]) for sha, rec in fixed.items() if sha not in best]
    return out, missing


def _vkey(music: dict) -> tuple:
    """Sort key: newer seqtool first, then with a vocal stem."""
    v = str((music.get("producer") or {}).get("version", "0"))
    parts = tuple(int(x) if x.isdigit() else 0 for x in v.split(".")[:3])
    stem = "vocal_dbfs" in music.get("analysis", {}).get("frames", {}).get("fields", {})
    return parts, stem


def stale(music: dict) -> str | None:
    """Why an analysis is too old to judge detection by, or None."""
    from .. import __version__
    mine = _vkey({"producer": {"version": __version__}})[0][:2]
    have = _vkey(music)[0]
    if have[:2] < mine:
        return f"made by seqtool {'.'.join(map(str, have))}"
    return None


def _stale_note(found) -> None:
    old = [(mp, m, why) for mp, m, _ in found for why in [stale(m)] if why]
    for mp, m, why in old:
        name = m["source"].get("filename") or mp.name
        audio = (m.get("run") or {}).get("audio")
        song = show(audio) if audio and Path(audio).exists() else name
        print(f"{{warn}}{name}: analysis {why}{{/}} - older detection inputs, so it scores lower; "
              f"for a fresh one: 'run --audio \"{song}\" --stems'")


def _canon_type(t: str, aliases: dict) -> str:
    return aliases.get(t, t)


def score_song(music: dict, edits: dict, rules: dict, aliases: dict) -> dict:
    from .classify import sections
    bpm = music["analysis"]["summary"]["tempo"]["bpm"] or 120.0
    tol = max(1.0, 4 * 60.0 / bpm)                               # one bar (typed fixes are often whole seconds)
    truth = sorted(edits["boundaries"])
    det = [s["start"] for s in sections(music, rules)[1:]]
    hit_d = sum(1 for d in det if any(abs(d - t) <= tol for t in truth))
    hit_t = sum(1 for t in truth if any(abs(d - t) <= tol for d in det))
    prec = hit_d / len(det) if det else (1.0 if not truth else 0.0)
    rec = hit_t / len(truth) if truth else 1.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    out = {"boundaries": len(truth), "detected": len(det), "right": hit_t, "missed": len(truth) - hit_t,
           "extra": len(det) - hit_d, "precision": prec, "recall": rec, "f1": f1}
    typed = edits.get("types", {})
    if typed:
        on_yours = sections(music, rules, {"boundaries": truth})
        ok = n = 0
        for t, typ in typed.items():
            s = next((x for x in on_yours if abs(x["start"] - float(t)) < 0.06), None)
            if s is None:
                continue
            n += 1
            ok += _canon_type(s["type"], aliases) == _canon_type(typ, aliases)
        out.update(types=n, types_right=ok)
    return out


def detail_lines(music: dict, edits: dict, rules: dict) -> list[str]:
    """Each of your boundaries next to what detection did there: the nearest detected
    boundary, and whether a candidate existed (proposed, but dropped by the selection)."""
    from .classify import candidates, sections
    an = music["analysis"]
    bpm = an["summary"]["tempo"]["bpm"] or 120.0
    bar = 4 * 60.0 / bpm
    tol = max(1.0, bar)
    truth = sorted(edits["boundaries"])
    det = [s["start"] for s in sections(music, rules)[1:]]
    cands = candidates(music, rules.get("method", "combined"), rules.get("novelty_weight", 0.8),
                       float(rules.get("vocal_entry", 0.0) or 0.0), float(rules.get("lyrics", 1.0)))
    L = [f"    tempo {bpm:.1f} BPM (confidence {an['summary']['tempo'].get('confidence', 0):.2f}), "
         f"a bar is {bar:.2f} s; tolerance {tol:.2f} s; {len(cands)} candidates proposed"]
    L.append(f"    {'yours':>8}  {'nearest detected':>17}  {'off by':>7}        nearest candidate")
    diffs = []
    for t in truth:
        near = min(det, key=lambda d: abs(d - t)) if det else None
        off = (near - t) if near is not None else None
        c = min(cands, key=lambda b: abs(b["time"] - t)) if cands else None
        ok = off is not None and abs(off) <= tol
        if near is not None:
            diffs.append(off)
        if c is None:
            cand = "none proposed"
        else:
            dc = c["time"] - t
            near_c = abs(dc) <= tol
            cand = (f"{c['time']:.1f} s ({dc:+.1f}), strength {c.get('strength', 0.5):.2f}" +
                    (f" ({c['lyrics']})" if c.get("lyrics") else "") +
                    ("" if ok else " - proposed but dropped: a stronger one was within min_bars" if near_c
                     else " - none proposed within a bar"))
        L.append(f"    {t:8.1f}  {('-' if near is None else f'{near:.1f}'):>17}  "
                 f"{('-' if off is None else f'{off:+.1f} s'):>7}  {'{ok}ok{/}' if ok else '{warn}miss{/}'}  {cand}")
    extra = [d for d in det if all(abs(d - t) > tol for t in truth)]
    if extra:
        L.append("    detected but not yours: " + ", ".join(f"{d:.1f}" for d in extra))
    typed = edits.get("types", {})
    if typed:
        aliases = {}
        try:
            from ..common.config import music_prefs
            aliases = music_prefs().get("section_types", {})
        except Exception:  # noqa: BLE001
            pass
        on_yours = sections(music, rules, {"boundaries": truth})
        L.append("    types on your boundaries (yours / detection, and why):")
        for s in on_yours:
            yours = next((v for k, v in typed.items() if abs(float(k) - s["start"]) < 0.06), None)
            if yours is None:
                continue
            same = _canon_type(yours, aliases) == _canon_type(s["type"], aliases)
            why = s.get("type_why") or "the sound (energy, repeats)"
            L.append(f"    {s['start']:8.1f}  {yours:<11} {s['type']:<11} {'{ok}same{/}' if same else '{warn}differs{/}'}  {why}")
    if len(diffs) >= 3:
        med = sorted(diffs)[len(diffs) // 2]
        same_sign = sum(1 for d in diffs if d * med > 0) >= 0.8 * len(diffs)
        if abs(med) > tol and same_sign:
            L.append(f"    {{warn}}detection is consistently {abs(med):.1f} s {'late' if med > 0 else 'early'}{{/}} - "
                     "an offset in the audio, or the beats/downbeats are off (check 'gui': do the bar ticks line up?)")
    return L


def _rules_with(base: dict, combo: dict) -> dict:
    return {**base, **combo}


def report(rows, rules) -> list[str]:
    L = [f"  {'song':<28} {'yours':>5} {'found':>5} {'right':>5} {'missed':>6} {'extra':>5}   F1    types"]
    for mp, m, sc in rows:
        name = m["source"].get("filename") or mp.name
        types = f"{sc['types_right']}/{sc['types']}" if sc.get("types") else "-"
        L.append(f"  {name[:28]:<28} {sc['boundaries']:>5} {sc['detected']:>5} {sc['right']:>5} {sc['missed']:>6} "
                 f"{sc['extra']:>5}  {sc['f1']:.2f}   {types}")
    f1 = sum(sc["f1"] for _, _, sc in rows) / len(rows)
    tn = sum(sc.get("types", 0) for _, _, sc in rows)
    tr = sum(sc.get("types_right", 0) for _, _, sc in rows)
    L.append(f"  {'all songs':<28} boundary F1 {f1:.2f}" + (f", types {tr}/{tn} ({tr / tn:.0%})" if tn else "")
             + f"   [method {rules.get('method', 'combined')}, min_bars {rules.get('min_bars', 8)}, "
               f"min_strength {rules.get('min_strength', 0.0)}, novelty_weight {rules.get('novelty_weight', 0.8)}, "
               f"vocal_entry {rules.get('vocal_entry', 0.0)}, lyrics {rules.get('lyrics', 1.0)}, "
               f"lyric_min_bars {rules.get('lyric_min_bars', 2)}]")
    return L


def mean_f1(found, rules, aliases) -> float:
    return sum(score_song(m, ed, rules, aliases)["f1"] for _, m, ed in found) / len(found)


def _not_found(missing: list[str]) -> None:
    if missing:
        print(f"{{warn}}{len(missing)} song(s) you fixed weren't found{{/}}: {', '.join(missing)} - name them to include "
              "them, e.g. 'sections score path/to/*.mp3' (any song you fixed, analysed with 'run')")


def score_cmd(extra: list[Path] | None = None, detail: bool = False) -> int:
    from .classify import section_rules
    from ..common.config import music_prefs
    found, missing = fixed_songs(extra)
    if not found:
        print("no songs with section fixes found - fix a song's sections first ('sections', then e.g. "
              "'sections merge 3 4'), and keep it in a baseline ('baseline add') so it can be found again")
        return 0
    rules, aliases = section_rules(), music_prefs().get("section_types", {})
    _not_found(missing)
    _stale_note(found)
    rows = [(mp, m, score_song(m, ed, rules, aliases)) for mp, m, ed in found]
    print(f"{{head}}section detection vs your fixes{{/}} ({len(rows)} song(s); detection run without your fixes)")
    for ln in report(rows, rules):
        print(ln)
    if detail:
        for mp, m, ed in found:
            print(f"{{head}}{m['source'].get('filename') or mp.name}{{/}}")
            for ln in detail_lines(m, ed, rules):
                print(ln)
    else:
        print("details per boundary (what detection did at each of yours): 'sections score --detail'")
    print("{note}missed = your boundaries detection didn't find; extra = detected ones you removed; "
          "types = sections you typed that detection types the same{/}")
    print("try other detection settings on these songs: 'sections tune'")
    return 0


def tune_cmd(save: bool | None = None, extra: list[Path] | None = None) -> int:
    from .classify import section_rules
    from ..common.config import music_prefs
    from ..common.log import good, info
    from ..common.prompt import ask
    found, missing = fixed_songs(extra)
    if not found:
        return score_cmd(extra)
    _not_found(missing)
    _stale_note(found)
    base, aliases = section_rules(), music_prefs().get("section_types", {})
    cur = round(mean_f1(found, base, aliases), 4)
    keys = list(GRID)
    tried = []
    from ..common.progress import Progress
    combos = list(itertools.product(*(GRID[k] for k in keys)))
    info(f"trying {len(combos)} combinations of detection settings on {len(found)} song(s) ...")
    prog = Progress(len(combos), "section settings")
    for vals in combos:
        prog.step()
        combo = dict(zip(keys, vals))
        f1 = round(mean_f1(found, _rules_with(base, combo), aliases), 4)
        n_changed = sum(base.get(k) != v for k, v in combo.items())
        tried.append((-f1, n_changed, abs(combo["min_bars"] - base.get("min_bars", 8)), combo))
    prog.done()
    tried.sort(key=lambda x: x[:3])          # best F1; on a tie the fewest changes from your settings
    best, best_f1 = (tried[0][3], -tried[0][0]) if -tried[0][0] > cur + 1e-9 else (None, cur)
    print(f"{{head}}section detection on your {len(found)} fixed song(s){{/}}: "
          f"boundary F1 now {cur:.2f}" + (f", best {best_f1:.2f}" if best else " - already the best of "
                                         f"{len(list(itertools.product(*GRID.values())))} combinations tried"))
    if not best:
        print("the detection settings aren't what holds it back here; send the music.json files and your "
              "songs.json so detection itself can be improved")
        return 0
    rows = [(mp, m, score_song(m, ed, _rules_with(base, best), aliases)) for mp, m, ed in found]
    for ln in report(rows, _rules_with(base, best)):
        print(ln)
    changes = {k: v for k, v in best.items() if base.get(k) != v}
    cmds = "; ".join(f"'pref music.sections.{k} = {v}'" for k, v in changes.items())
    if save is None:
        save = ask(f"Use these settings for every song? [y/N]  ({cmds})", "n", show_default=False).lower() in ("y", "yes")
    if save:
        config.update("music", {"sections": changes})
        good("saved - songs are re-sectioned on their next 'run' (your own fixes still win)")
    else:
        info(f"not saved; to use them later: {cmds}")
    return 0
