# seqtool-command: demo | main | pipeline | whole chain on a synthetic song + demo yard
# seqtool-command: run | main_run | pipeline | whole chain on your audio (layout: stored, --rgbeffects or --layout)
"""Run the whole generic chain, reusing fresh intermediate files.

    seqtool                                    # same as: seqtool demo
    seqtool demo                               # synthetic song + demo yard
    seqtool run --audio song.mp3               # your song, demo yard
    seqtool run --audio song.mp3 --rgbeffects xlights_rgbeffects.xml
    seqtool run --audio song.mp3 --layout my-yard.json   # a layout from prop-wizard

All intermediate files go to --out. On re-runs, music/profile/layout/models
files are reused when fresh and rebuilt when stale (changed source file,
changed settings, or made by an older seqtool MAJOR.MINOR); see --stale.
"""
from __future__ import annotations

from collections import Counter

import argparse
import sys
from pathlib import Path

from ..common import freshness
from ..common.canonical import file_sha256, read_json, write_json
from ..common.config import music_prefs, set_user_dir
from ..common.paths import show
from ..common.log import good, info, memo, set_level, stage
from ..matchup import engine
from ..matchup.cli import explain, load_prefs
from ..models.analyze import analyze as analyze_models
from ..music.analyze import analyze as analyze_music
from ..music.classify import classify
from ..validate.validate import validate_plan
from . import layout as demo_layout, synth, view
from ..common.paths import arg as paths_arg


def section_columns(profile: dict, matchup: dict) -> list[tuple]:
    """Per section: the tuple of effect sequences across all targets."""
    cols = []
    for s in profile["sections"]:
        col = []
        for p in matchup["plans"]:
            effs = []
            for g in p["segments"]:
                if g["start"] < s["end"] - 1e-6 and g["end"] > s["start"] + 1e-6:
                    e = g["selected"]["effect"]
                    if not effs or effs[-1] != e:
                        effs.append(e)
            col.append("/".join(effs))
        cols.append(tuple(col))
    return cols


def section_matches(profile: dict, matchup: dict, partial: float = 0.75) -> dict[int, str]:
    """Section index -> '= #2 verse' when its whole effect column repeats an
    earlier section exactly, or '~ #2 verse (6/7)' when most targets match."""
    secs, cols = profile["sections"], section_columns(profile, matchup)
    out = {}
    for j in range(len(secs)):
        best = None
        for i in range(j):
            same = sum(a == b for a, b in zip(cols[i], cols[j]))
            if best is None or same > best[1]:
                best = (i, same)
        if best is None or not cols[j]:
            continue
        i, same = best
        n = len(cols[j])
        ref = f"#{secs[i]['index']} {secs[i].get('type', '?')}"
        if same == n:
            out[secs[j]["index"]] = f"= {ref}"
        elif same / n >= partial:
            out[secs[j]["index"]] = f"~ {ref} {same}/{n}"
    return out


def timeline(profile: dict, matchup: dict) -> str:
    secs = profile["sections"]
    w = 16
    matches = section_matches(profile, matchup)
    cols = section_columns(profile, matchup)
    from ..baseline import label
    nw = min(26, max([len(label(p)) for p in matchup["plans"]] + [8]) + 1)
    head = f"{'':<{nw}}" + "".join(f"{'#' + str(s['index']) + ' ' + s.get('type', '?'):<{w}}"[:w] for s in secs)
    rows = [head,
            f"{'':<{nw}}" + "".join(f"{s['start']:<{w}.1f}" for s in secs),
            f"{'':<{nw}}" + "".join(f"{matches.get(s['index'], ''):<{w}}"[:w] for s in secs)]
    for k, p in enumerate(matchup["plans"]):
        rows.append(f"{label(p)[:nw - 1]:<{nw}}" + "".join(f"{c[k][: w - 1]:<{w}}" for c in cols))
    if matches:
        rows.append("('= #n' : the whole column repeats section #n; '~' : most targets do)")
    return "\n".join(rows)


def _confirm_overlaps(lay: dict, pref_dir) -> None:
    """Props sharing controller channels: warn, or ask once and remember."""
    from ..adapters.xlights.import_layout import review_overlaps
    return review_overlaps(lay, pref_dir)


def _cached(path: Path, build, note=None, audio: Path | None = None, **expect) -> dict:
    doc = freshness.load_if_fresh(path, note=note, **expect)
    if doc is None:
        from ..common.canonical import round_floats
        doc = round_floats(build())           # exactly what is stored, so a fresh run and a re-run agree
        write_json(path, doc)
    elif audio is not None and doc.get("run", {}).get("audio") != str(Path(audio).resolve()):
        doc["run"] = {**doc.get("run", {}), "audio": str(Path(audio).resolve())}   # the song moved:
        write_json(path, doc)                 # 'run' isn't part of the content hash, so nothing goes stale
    return doc


EXPORT_SKIPPED = False


def pipeline(a, demo: bool) -> int:
    set_user_dir(a.preferences)
    from ..music import phonemes as _ph
    _ph.use_arg(getattr(a, "dictionary", None))          # sticky add-on dictionary (0.19.2)
    if a.out is None:
        from ..common.paths import seqtool_folder
        a.out = seqtool_folder(a.audio)
    out = a.out
    out.mkdir(parents=True, exist_ok=True)
    if a.audio:
        audio = a.audio
    elif demo:
        audio = out / "demo-song.wav"
        if not audio.exists():
            write_json(out / "demo-song.truth.json", synth.write(audio))
        info(f"synthetic song: {show(audio)}  (ground truth in demo-song.truth.json)")
    else:
        raise SystemExit("run: --audio is required (or use 'seqtool demo')")
    stem = audio.stem
    from ..common import config as _cfg
    from ..common import current as _current
    _current.remember(audio=audio)
    _cfg.remember("last_out", str(out.resolve()))
    from ..layout import store as _store
    T = 8 if (a.rgbeffects or (not demo and not a.layout and _store.source_info())) else 7
    mp = music_prefs(a.preferences)["analysis"]
    fi = a.frame_interval or mp["frame_interval"]
    stems = a.stems or mp.get("stems", False)

    from ..music.stems import stem_problems
    # stems on: the analysis must have used a stem, and that stem file must still be the
    # one it measured; stems off: an analysis with vocal data from a stem is stale too
    settings = {"analysis.frame_interval": fi}

    def stem_note(doc):
        v = doc.get("analysis", {}).get("summary", {}).get("vocal", {})
        return f"vocal stem: {v['stem_file']}" if v.get("stem_file") else ""
    stage(1, T, "music analysis", "analyze-music",
          f"{stem}.music.json")
    music = _cached(out / f"{stem}.music.json", lambda: analyze_music(audio, stems, fi),
                    note=stem_note, audio=audio, lineage={"audio": file_sha256(audio)}, settings=settings,
                    check=lambda d: stem_problems(d, audio, want=bool(stems)))
    stage(2, T, "music classification", "classify-music",
          f"{stem}.music-profile.json")
    from ..common.canonical import content_sha256 as _csha
    from ..music.classify import lyrics_key, section_edits_for, section_rules
    _edits = section_edits_for(music)
    profile = _cached(out / f"{stem}.music-profile.json",
                      lambda: classify(music, f"{stem}.music.json", a.preferences), inputs={"music": music},
                      settings={"source.sections.rules": section_rules(a.preferences),
                                "source.sections.edits": _csha(_edits) if _edits else None,
                                "source.sections.lyrics": lyrics_key(music)})

    from ..layout import store
    xl_layout = False
    if a.rgbeffects:
        a.rgbeffects = store.find_rgbeffects(a.rgbeffects)
        stage(3, T, f"layout (ingest {a.rgbeffects.name})", "layout", "seqtool-prefs/layout/")
        lay, models = store.ingest(a.rgbeffects, a.preferences)
        xl_layout = True
    elif a.layout:
        stage(3, T, f"layout ({a.layout.name})", "", "layout.json")
        lay = read_json(a.layout)
        models = None
    elif not demo and store.source_info():
        stage(3, T, "layout (stored)", "layout", "")
        lay, models = store.current(a.preferences)
        xl_layout = True
    elif not demo:
        raise SystemExit("no layout: ingest one first with 'seqtool layout xlights_rgbeffects.xml', "
                         "or pass --rgbeffects / --layout")
    else:
        stage(3, T, "layout (built-in demo yard)", "", "layout.json")
        lay, models = demo_layout.demo_layout(), None
    write_json(out / "layout.json", lay)
    stage(4, T, "model analysis", "analyze-models", "layout.models.json")
    if models is None:
        from ..models.analyze import outdated
        models = _cached(out / "layout.models.json", lambda: analyze_models(lay, "layout.json"),
                         inputs={"layout": lay}, check=outdated)
    else:
        write_json(out / "layout.models.json", models)

    prefs = load_prefs(a.preferences)
    from ..common import songs
    song_sha = music["lineage"]["audio"]
    if a.seed is not None:                       # an explicit seed becomes this song's seed
        songs.update(song_sha, audio.name, seed=a.seed)
    seed = songs.seed(song_sha)
    seed_ovr = songs.seed_overrides(song_sha)
    _cfg.remember("last_music", str((out / f"{stem}.music.json").resolve()))
    if songs.get(song_sha).get("sections"):          # keep 'sections score' pointed at this analysis
        songs.update(song_sha, audio.name, music=str((out / f"{stem}.music.json").resolve()))
    fb = None
    for old in list(out.glob(f"{stem}.matchup.iter*.json")) + list(out.glob(f"{stem}.validation.iter*.json")):
        old.unlink()                                  # leftovers from an earlier run with more iterations
    avail = None                                    # only effects the xLights kit has learned
    if any(m.get("origin", {}).get("adapter") == "xlights" for m in models["models"]):
        try:
            from ..adapters.xlights import encoding as _enc
            _e = _enc.find()
            if _e is not None:
                avail = set(_e.effects) | {"transparent", "dark"}
                yours = {k for k, v in prefs["effects"]["effects"].items() if v.get("auto") is False}   # yours (pins):
                #   planned anyway - the export says when it can't write one (0.24.46); choreo is no xLights
                #   effect of its own - not a kit step (0.24.59)
                missing = sorted(set(prefs["effects"]["effects"]) - avail - yours)
                avail |= yours
                if missing:
                    info(f"  not learned by the xLights kit yet, so not used: {', '.join(missing)} "
                         "(xlights-kit --update)")
        except Exception:  # noqa: BLE001
            avail = None
    pins = songs.get(song_sha).get("pins")
    reacts = songs.get(song_sha).get("react")                  # this song's reactions (0.21.4)

    def iterate(seed_c: int, show_stages: bool) -> list:
        """The match/validate rounds for one seed: [(suffix, matchup, validation)]."""
        res, fb_ = [], None
        for it in range(max(1, a.iterations)):
            suffix = "" if it == 0 else f".iter{it}"
            if show_stages:
                stage(5, T, f"matchup, iteration {it}", "match", f"{stem}.matchup{suffix}.json")
            m_ = engine.run(music, profile, models, prefs, seed_c,
                            {"music": f"{stem}.music.json", "music_profile": f"{stem}.music-profile.json",
                             "models": "layout.models.json"}, feedback=fb_, seed_overrides=seed_ovr,
                            pins=pins, available=avail, reacts=reacts,
                            cues=songs.get(song_sha).get("cues"), palette=songs.get(song_sha).get("palette"),
                            feel=songs.get(song_sha).get("feel"))
            if show_stages:
                stage(6, T, f"validation, iteration {it}", "validate", f"{stem}.validation{suffix}.json")
            v_ = validate_plan(m_, models, profile, iteration=m_["settings"]["iteration"])
            res.append((suffix, m_, v_))
            if show_stages:
                sm = v_["summary"]
                col = {"errors": "err", "warnings": "warn", "notes": "note"}
                info(f"iteration {it}: " + ("{ok}" if v_["result"] == "ok" else "{warn}" if v_["result"] == "warning"
                                            else "{err}") + v_["result"] + "{/}" + "".join(
                    f", {{{col[k]}}}{n} {k}{{/}}" for k, n in (("errors", sm["errors"]), ("warnings", sm["warnings"]),
                                                                 ("notes", sm["info"])) if n))
            fb_ = v_["feedback"]
            if fb_["converged"]:
                break
        return res

    ccfg = prefs["scoring"].get("critic", {})
    n_cand = max(1, a.candidates if a.candidates is not None else int(ccfg.get("candidates", 1)))
    if n_cand == 1:
        results = iterate(seed, True)
    else:
        from ..common.seed import sub_seed
        from ..matchup.critic import critique, line
        stage(5, T, f"matchup + validation for {n_cand} seeds", "match",
              f"{stem}.matchup.json (the best)")
        tried = []
        for k in range(n_cand):
            s_k = seed if k == 0 else sub_seed(seed, "candidate", k) % 1_000_000
            r_k = iterate(s_k, False)
            tried.append((critique(r_k[-1][1], r_k[-1][2], profile, ccfg), k, s_k, r_k))
        best = max(tried, key=lambda x: (x[0]["score"], -x[1]))
        for c, k, s_k, _ in tried:
            print(line(s_k, c, "*" if k == best[1] else " ") + ("  (the song's seed)" if k == 0 else ""))
        results = best[3]
        if best[2] != seed:
            rec = songs.get(song_sha)
            hist = list(rec.get("seed_history", [])) + [{"key": "", "previous": rec.get("seed")}]
            songs.update(song_sha, audio.name, seed=best[2], seed_history=hist[-50:])
            info(f"kept seed {best[2]} (the best of {n_cand}); it is now this song's seed - "
                 "'reroll --undo' goes back to the previous one")
            seed = best[2]
        else:
            info(f"the song's seed {seed} scored best of {n_cand}; kept")
    for suffix, m, v in results:
        last_matchup = out / f"{stem}.matchup{suffix}.json"
        write_json(last_matchup, m)
        _cfg.remember("last_matchup", str(last_matchup.resolve()))
        write_json(out / f"{stem}.validation{suffix}.json", v)
    fb = results[-1][2]["feedback"]

    stage(7, T, "summary", "", f"{stem}.summary.txt, {stem}.timeline.html")
    labels = view.write_audacity_labels(out, stem, music, profile)
    quick = getattr(a, "replan", False)               # 0.24.28: a re-plan skips the timeline page (the GUI has its own)
    html_path = out / f"{stem}.timeline.html"
    if not quick or not html_path.exists():
        html_path = view.write_timeline_html(out, stem, audio, music, profile, m, section_matches(profile, m))
    headline = (f"tempo {music['analysis']['summary']['tempo']['bpm']:.1f} BPM, "
                f"{len(profile['sections'])} sections, styles: " +
                ", ".join(f"{k} {v:.2f}" for k, v in sorted(profile["profile"]["styles"].items(),
                                                            key=lambda kv: -kv[1])[:3]))
    ovr = ", ".join(f"{k}={v}" for k, v in sorted(seed_ovr.items()))
    from ..music.sections_cmd import HINT
    from ..music.classify import section_rules as _rules
    lines = ["{head}" + headline + "{/}", f"seed {seed}" + (f" (overrides: {ovr})" if ovr else "")
             + "   {note}(new choices: {do}reroll{/}, {do}reroll TARGET @#N{/}; undo: {do}reroll --undo{/})", "",
             timeline(profile, m), "", HINT.format(min_bars=_rules(a.preferences).get("min_bars", 8)), ""]
    mo = m.get("moments", [])
    if mo:                                            # whole-yard moments (0.20)
        lines.append("{head}whole-yard moments (base pass):{/}")
        lines += [f"  {x['id']:<4} {x['start']:6.1f}-{x['end']:6.1f} s  {x['reason']} ({len(x.get('targets', []))} props, "
                  f"their own effects: {x.get('members', 'cut')})" for x in mo]
        lines.append("")
    for n in m["diagnostics"].get("passes", []):
        lines.append(n)
    skipped = m["diagnostics"]["skipped_targets"]
    if skipped:
        cats: dict[str, list[str]] = {}
        for x in skipped:
            r = x["reason"]
            key = ("models excluded from the layout" if any(w in r for w in ("excluded", "matches", "not controllable",
                                                                      "helper", "listed in"))
                   else "covered by a chosen group" if r.startswith(("driven via", "overlaps"))
                   else "top groups not used (one top group at a time; see scoring.passes.top)"
                   if "'top'" in r or r.startswith("top pass")
                   else "detail targets not used (one per prop; to choose, set the other's role: 'pref models/targets/GROUP/role = unused')"
                   if "'detail'" in r or r.startswith("detail pass")
                   else "groups with role unused (not sequenced)" if "role unused" in r or "role off" in r
                   else r)
            cats.setdefault(key, []).append(x["id"])
        lines.append("{head}not planned in this run:{/}")
        lines += [f"  {len(v)} {k}: {', '.join(v)}" for k, v in cats.items()]
    summary = out / f"{stem}.summary.txt"
    from ..common.color import plain
    summary.write_text(plain("\n".join(lines)) + "\n", encoding="utf-8")
    sizes = {x["id"]: x.get("node_count", 0) for x in models["models"]}
    planned = [p["target"] for p in m["plans"] if p["segments"]]
    focus = max(planned, key=lambda t: (sizes.get(t, 0), t)) if planned else None
    chorus = next((s for s in profile["sections"] if s.get("type") == "chorus"), profile["sections"][0])
    example = None
    if focus and not quick:
        from ..matchup.explain import run as explain_cmd
        at = f"@{(chorus['start'] + chorus['end']) / 2:.1f}"
        cmd = f"seqtool explain {focus} {at}"          # explain defaults to the last results folder
        example = out / f"{stem}.explain-example.txt"
        example.write_text(plain(f"$ {cmd}\n" + explain_cmd(focus, at, last_matchup)) + "\n", encoding="utf-8")
    print("{head}" + headline + "{/}")
    from ..common.log import warn as _warn
    for n in m["diagnostics"].get("faces", []):          # singing faces that couldn't sing (0.19.1)
        _warn(f"  {n}")
    sing = [p["target"] for p in m["plans"] if p.get("pass") == "face" and p["segments"]]
    if sing:
        print(f"  singing faces:       {', '.join(sing)} (while the words are sung)")
    if mo:
        kinds = Counter(x["type"].replace("_", " ") for x in mo)
        print(f"  whole-yard moments:  {len(mo)} (" + ", ".join(f"{n} {k}" for k, n in kinds.items())
              + ")  {note}(scoring.passes.base; 'explain PROP @TIME' in one says why){/}")
    for n in m["diagnostics"].get("passes", []):
        print(f"  {n}")
    from ..common.prefcmd import uses
    for ln in uses("scoring.passes.base.members", "scoring.passes.base.per_minute", "scoring.durations.default",
                   "scoring.passes.variation.aspect", "scoring.passes.top.sections"):
        print("  " + ln)
    print(f"  plan summary:        {show(summary)}")
    if example:
        print(f"  example explanation: {show(example)}   ({{do}}{cmd}{{/}})")
    from ..common.prompt import gui_asker
    in_gui = gui_asker() is not None                 # run from the GUI console: the view above is already live
    print(f"  timeline:            {show(html_path)}" + ("" if in_gui else "   ({do}seqtool gui{/})"))
    print("  sections look wrong? {do}sections{/} lists them and shows how to merge, split, move or retype them")
    from ..common.config import load as _load
    global EXPORT_SKIPPED
    EXPORT_SKIPPED = False
    if xl_layout and quick and not _load("xlights").get("export_on_replan", False):
        EXPORT_SKIPPED = True                         # said by the re-plan's caller (this run is silenced)
    elif xl_layout:
        from ..adapters.xlights import export_xsq, kit
        stage(8, T, "xLights export", "xlights-export", f"{stem}.xsq")
        export_xsq.export(last_matchup, out / f"{stem}.xsq", audio)    # offers the training wizard if needed
    good(f"all artifacts in {show(out)}")
    from ..common.status import scan
    left = [(n, w) for n, w in scan(out) if w and n.startswith(stem + ".")]
    if left:                                         # a run should leave none: say which and why, so it can be fixed
        from ..common.log import warn
        warn("still stale after this run (please report this): " + "; ".join(f"{n} ({', '.join(w)})" for n, w in left))
    if a.view != "none":
        view.offer(a.view, audio, labels, html_path)
    elif not in_gui:
        info("use the {do}gui{/} command to see the waveform, sections and effects")
    return 0


def _parser(prog: str, demo: bool) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog=prog, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    from ..music.phonemes import add_arg as _dict_arg
    _dict_arg(ap)
    ap.add_argument("--out", type=paths_arg, default=Path("seqtool-demo") if demo else None,
                    help="results folder" + ("" if demo else " (default: <song folder>/<song>-seqtool/)"))
    ap.add_argument("--audio", type=paths_arg, default=None,
                    help="mp3/wav/..." + (" (default: generate a synthetic song)" if demo
                                          else " (default: the most recently used song)"))
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--layout", type=paths_arg, help="generic layout.json (e.g. from prop-wizard)")
    g.add_argument("--rgbeffects", type=paths_arg, help="xlights_rgbeffects.xml or the show folder (ingested and kept)")
    ap.add_argument("--preferences", type=paths_arg, default=None,
                    help="user preference folder (default ~/seqtool-prefs); overlays the built-in defaults")
    ap.add_argument("--seed", type=int, default=None,
                    help="master seed; remembered for this song (default: the song's seed - see 'inspect audio')")
    ap.add_argument("--frame-interval", type=float, default=None,
                    help="analysis frame period in seconds (default from preferences/music.json)")
    ap.add_argument("--iterations", type=int, default=4, help="max match/validate rounds (feedback loop)")
    if not demo:
        ap.add_argument("--baseline", nargs="?", const="all", default=None, metavar="N",
                        help="run the songs of your baseline: all of them, or song N ('baseline' numbers them)")
    ap.add_argument("--candidates", type=int, default=None,
                    help="try N seeds and keep the plan the show critic scores best "
                         "(default scoring.critic.candidates, 1)")
    ap.add_argument("--stems", action="store_true", help="separate vocals, drums, bass and other with Demucs (optional dependency): vocal level, "
                    "drum hits, bass and melody notes for reaction presets")
    ap.add_argument("--view", choices=("ask", "audacity", "browser", "none"), default="none",
                    help="open a viewer at the end (default: none - use the 'gui' command any time)")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--replan", action="store_true", help=argparse.SUPPRESS)   # 0.24.28: a re-plan after a change
    if demo:
        ap.add_argument("--bundle", action="store_true", help="the demo as a show of its own - xLights files, song, "
                        "settings and results - in one .zip ('bundle --open' unpacks it like a real show's bundle)")
    return ap


def _remember_run(cmd: str, argv) -> None:
    from ..common import config
    config.remember("last_run", {"cmd": cmd, "argv": [str(x) for x in (argv or [])], "cwd": str(Path.cwd())})


def main(argv=None) -> int:
    a = _parser("seqtool demo", True).parse_args(argv)
    if a.quiet:
        set_level(35)
    if a.bundle:
        return demo_bundle()
    _remember_run("demo", argv)
    return pipeline(a, demo=True)


def demo_bundle() -> int:
    """0.24.36: the demo yard and song as a show of their own, made in a scratch folder with its
    own settings (yours aren't touched), run once, and packed with 'bundle' - the same .zip a
    real show gives, so the seqtool-direction skill can be tried on it in a Claude session."""
    import os
    import tempfile
    from ..common import config
    from ..common.bundle_cmd import make
    from .xlights_files import write as write_show
    dest = Path.cwd() / "seqtool-bundles"
    keep = (config._user_dir, config._default_dir, os.environ.get("SEQTOOL_PREFS"), Path.cwd())
    with tempfile.TemporaryDirectory(prefix="seqtool-demo-") as td:
        root = Path(td)
        show_dir = root / "Demo show"
        song_dir = show_dir / "Demo song"
        write_show(show_dir)
        song_dir.mkdir(parents=True)
        wav = song_dir / "demo-song.wav"
        synth.write(wav)
        mine = config.user_dir() / "xlights-learned"  # what your xLights kit learned: export works there too
        if mine.is_dir():
            import shutil
            shutil.copytree(mine, root / "seqtool-prefs" / "xlights-learned")
        os.environ["SEQTOOL_PREFS"] = str(root / "seqtool-prefs")
        set_user_dir(root / "seqtool-prefs")
        try:
            from ..layout import store
            info("the demo show: xLights files (one generic controller), the synthetic song ...")
            store.ingest(show_dir / "xlights_rgbeffects.xml", keep_added=False)
            os.chdir(song_dir)
            rc = main_run(["--audio", str(wav)])
            if rc:
                return rc
            zf = make(dest)
            final = zf.with_name("seqtool-demo-" + zf.name.split("-", 2)[-1] if zf.name.startswith("demo-song-")
                                 else zf.name)
            zf.replace(final)
        finally:
            os.chdir(keep[3])
            config._user_dir, config._default_dir = keep[0], keep[1]
            if keep[2] is None:
                os.environ.pop("SEQTOOL_PREFS", None)
            else:
                os.environ["SEQTOOL_PREFS"] = keep[2]
    good(f"wrote {final} - the demo as a show: 'bundle --open {final.name}' unpacks it (your own settings "
         "weren't touched)")
    return 0


def main_run(argv=None) -> int:
    from ..common import config as _c
    if _c.answer("replan_pending"):
        _c.remember("replan_pending", False)            # a run makes the plan anyway
    a = _parser("seqtool run", False).parse_args(argv)
    if a.baseline is not None:                   # run --baseline [N]: the songs of the baseline
        from ..baseline import songs_of
        bl = songs_of()
        if not bl:
            raise SystemExit("no baseline yet - 'baseline add' (the current song) or 'baseline add SONG ...' first")
        if a.baseline == "all":
            pick = bl
        elif a.baseline.isdigit() and 1 <= int(a.baseline) <= len(bl):
            pick = [bl[int(a.baseline) - 1]]
        else:
            raise SystemExit(f"run --baseline N: N is 1-{len(bl)} ('baseline' lists the songs), or no N for all")
        rest, skip = [], 0
        for x in argv or []:                       # the other options apply to every song
            if skip:
                skip -= 1
            elif x == "--baseline":
                skip = 1 if a.baseline != "all" else 0
            elif x == "--audio":
                skip = 1
            elif not x.startswith("--baseline="):
                rest.append(x)
        rc = 0
        for n, song in enumerate(pick, 1):
            if len(pick) > 1:
                info(f"{{head}}== song {n}/{len(pick)}: {song.name}{{/}}")
            rc = main_run(["--audio", str(song), *rest]) or rc
        return rc
    if a.audio is None:
        from ..common import config
        from ..common.paths import expand, show
        from ..common.prompt import ask
        last = config.answer("last_audio")
        if last and not Path(last).exists():
            from ..common.current import relocate
            last = str(relocate(last) or last)            # moved: follow it
        if last and Path(last).exists():
            a.audio = Path(last)
            info(f"song: {show(a.audio)} (the most recently used; --audio FILE for another)")
        else:
            ans = ask("run: which song (audio file)?", "", complete="file")
            if not ans:
                raise SystemExit("run needs a song: run --audio FILE")
            a.audio = expand(ans, "file")
        argv = list(argv or []) + ["--audio", str(a.audio)]
    _remember_run("run", argv)
    if a.quiet:
        set_level(35)
    from ..common.paths import anchored
    with anchored(a.audio):                       # results are shown relative to the song's folder
        rc = pipeline(a, demo=False)
    try:                                          # older single-stage files next to the song (0.19.8)
        from ..common import current
        from ..common.log import info as _info       # not 'info': that would make it local to all of main_run
        sup = current.superseded()
        if sup:
            _info(f"{{note}}{len(sup)} older file(s) next to the song ({', '.join(f.name for f in sup[:2])}"
                 f"{' ...' if len(sup) > 2 else ''}) are no longer used{{/}} - '{{do}}status --clean{{/}}' deletes them")
    except Exception:  # noqa: BLE001 - a note only
        pass
    return rc


if __name__ == "__main__":
    sys.exit(main())
