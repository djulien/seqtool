# seqtool-command: doctor | main | setup | is everything in place for your show? checks setup, says what to do next
"""seqtool doctor : check that everything a run needs is in place.

Checks, in the order you would set things up:
  - Python and numpy; ffmpeg (needed for MP3 and other non-WAV audio)
  - your preferences folder (and that your preference files are valid JSON)
  - the stored show layout (ingested? source file still there and unchanged?)
  - the xLights training (learned? complete for the current kit?)
  - group roles (reviewed for this layout?)
  - vocal stems (Demucs installed? on by default?)
  - the current song (its result files fresh?)

Each line is ok, a note, or something to fix, with the command that fixes it.
It ends with the one thing to do next. Nothing is changed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path

from . import __version__
from .common import config
from .common.paths import show

OK, OPT, NOTE, FIX = "ok", "opt", "note", "fix"
MARK = {OK: "{ok}ok  {/}", OPT: "{note}opt {/}", NOTE: "{warn}note{/}", FIX: "{err}fix {/}"}


def checks() -> list[tuple[str, str, str, str]]:
    """[(status, area, message, command to type or '')]"""
    out = []
    add = lambda st, area, msg, cmd="": out.append((st, area, msg, cmd))   # noqa: E731

    # --- tools
    v = sys.version_info
    add(OK if v >= (3, 10) else FIX, "python", f"Python {v.major}.{v.minor}.{v.micro}"
        + ("" if v >= (3, 10) else " - seqtool needs 3.10 or newer"))
    try:
        import numpy
        add(OK, "numpy", f"numpy {numpy.__version__}")
    except ImportError:
        add(FIX, "numpy", "numpy is missing", "pip install numpy")
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        add(OK, "ffmpeg", "ffmpeg found (any audio format)")
    else:
        add(NOTE, "ffmpeg", "ffmpeg not found: only WAV songs can be read - install ffmpeg for MP3 and others")

    # --- preferences
    ud = config.user_dir()
    bad = []
    for f in sorted(ud.glob("*.json")) if ud.is_dir() else []:
        try:
            json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            bad.append(f.name)
    if bad:
        add(FIX, "preferences", f"not valid JSON: {', '.join(bad)} in {show(ud)}", f"pref edit {Path(bad[0]).stem}")
    else:
        changed = [f.stem for f in sorted(ud.glob("*.json")) if f.stem not in ("answers", "songs")] if ud.is_dir() else []
        add(OK, "preferences", f"{show(ud)}" + (f" (you changed: {', '.join(changed)})" if changed else " (all defaults)"))

    # --- layout
    from .layout import store
    src = store.source_info()
    if src is None:
        add(FIX, "layout", "no show layout stored yet", "layout path/to/show")
    else:
        from .common.canonical import file_sha256
        path = Path(src["path"])
        if not path.exists():
            add(NOTE, "layout", f"{show(path)} no longer exists; the stored copy is used", "layout path/to/show")
        elif file_sha256(path) != src["sha256"]:
            add(NOTE, "layout", f"{show(path)} changed since it was stored; the next run re-reads it",
                "layout " + show(path))
        else:
            lay = json.loads((store.folder() / "layout.json").read_text(encoding="utf-8"))
            rep = lay.get("import_report", {})
            add(OK, "layout", f"{show(path)} ({rep.get('controllable', '?')} usable models, "
                f"{rep.get('groups', len(lay.get('groups', [])))} groups)")

    # --- xLights training
    xl = src is not None and str(src["path"]).lower().endswith(".xml")
    if xl:
        from .adapters.xlights import kit
        vers = kit.learned_versions()
        if not vers:
            add(FIX, "xLights", "nothing learned about your xLights version yet (needed to write .xsq files)",
                "xlights-kit")
        else:
            from .adapters.xlights.encoding import find
            enc = find()
            todo = kit.missing_steps(enc.version)[1] if enc else []
            if todo:
                names = ", ".join(dict.fromkeys(st.get("effect") or st["kind"] for st in todo if st["kind"] != "change"))
                add(NOTE, "xLights", f"training for {enc.version} lacks {len(todo)} step(s): {names}",
                    "xlights-kit --update")
            else:
                add(OK, "xLights", f"training complete for xLights {enc.version if enc else vers[-1]}")

    # --- group roles
    if src is not None:
        lay = json.loads((store.folder() / "layout.json").read_text(encoding="utf-8"))
        ask_kinds = {"umbrella", "submodel_view"}
        n = sum(1 for g in lay.get("groups", []) if g.get("structure", {}).get("kind") in ask_kinds)
        if n and config.answer("groups_reviewed") != src["sha256"]:
            add(NOTE, "groups", f"roles of {n} whole-yard / submodel group(s) are guessed from the layout; "
                "check them once", "groups")
        elif n:
            add(OK, "groups", "group roles reviewed for this layout")

    # --- stems
    on = config.music_prefs()["analysis"].get("stems", False)
    have = importlib.util.find_spec("demucs") is not None
    if have:
        add(OK, "stems", "Demucs installed; stems (vocals, drums, bass, other) " + ("on for every song" if on else
            "used with run --stems ('pref stems = true' for every song)"))
    else:
        add(NOTE if on else OPT, "stems", "Demucs not installed" + (" but stems are on: the next run offers to install it"
                                                     if on else " (optional: vocal activity, drum hits, bass and melody notes; seqtool offers to install it)"),
            "run --stems")

    # --- current song
    from .common import current
    cur = current.song()
    if cur is None:
        add(NOTE, "song", "no song yet", "run --audio path/to/song.mp3")
    elif not cur["audio"].exists():
        add(NOTE, "song", f"{show(cur['audio'])} not found", "run --audio path/to/song.mp3")
    else:
        from .common.status import current_rows
        rows = current_rows()
        stale = [n for n, why in rows if why]
        if not rows:
            add(NOTE, "song", f"{show(cur['audio'])}: no results yet", "run")
        elif stale:
            add(NOTE, "song", f"{show(cur['audio'])}: {len(stale)} stale file(s); the next run rebuilds them", "run")
        else:
            add(OK, "song", f"{show(cur['audio'])}: {len(rows)} result files, all fresh")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool doctor", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.parse_args(argv)
    rows = checks()
    print(f"{{head}}seqtool {__version__} - setup check{{/}}")
    for st, area, msg, cmd in rows:
        print(f"  {MARK[st]}  {area:<12} {msg}" + (f"   -> '{cmd}'" if cmd and st != OK else ""))
    todo = [r for r in rows if r[0] == FIX and r[3]] or [r for r in rows if r[0] == NOTE and r[3]]
    if todo:
        print(f"{{head}}next:{{/}} '{todo[0][3]}'")
    else:
        print("{head}ready:{/} 'run --audio path/to/song.mp3' (or just 'run' for the current song)")
    return 1 if any(r[0] == FIX for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
