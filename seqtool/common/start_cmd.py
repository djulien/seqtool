# seqtool-command: start | main | setup | run the commands for the start of a session (general.session_start: doctor, sections, feel)
"""seqtool start [--list]

Runs the commands of 'general.session_start' (preferences/general.json; yours in
seqtool-prefs/general.json) - by default 'doctor', 'sections' and 'feel': is everything in
place, the song's parts, its creative controls (0.24.34) - and 'xlights-kit --update' (0.24.47),
which runs only when there is a layout and the xLights training lacks steps (new effects), and
then where you can answer it (the seqtool> prompt, the GUI); elsewhere it is reported as a problem. The seqtool> prompt runs them when it
starts; the seqtool-direction skill runs 'start' first.

    start                          run them, showing only problems (doctor's 'fix' lines, errors)
    start --no-quiet               run them, showing everything they print
    start --list                   which they are
    pref general.session_start = ["doctor", "sections"]     change the list ([] = none)
"""
from __future__ import annotations

import argparse
import contextlib
import sys

from . import config


def commands() -> list[str]:
    return [c for c in (config.load("general").get("session_start") or []) if str(c).strip()]


def _at_start(w: list[str], known: dict) -> tuple[str | None, str]:
    """A command's own say on whether it runs at the start: its module's at_start(argv) ->
    ('skip', why) | ('ask', what) - 'ask' = it needs someone to answer it (0.24.47)."""
    spec = known.get(w[0])
    if not spec:
        return None, ""
    try:
        import importlib
        fn = getattr(importlib.import_module(spec[0]), "at_start", None)
        return fn(w[1:]) if fn else (None, "")
    except Exception:  # noqa: BLE001
        return None, ""


def run_all(quiet: bool = True) -> int:
    """quiet (0.24.37, the default): only problems are shown - doctor's 'fix' lines, errors, a
    command that failed - and one line that they ran."""
    from ..__main__ import discover, dispatch
    from .args import split_line
    from .log import captured
    cmds, known = commands(), discover()
    problems = 0
    for c in cmds:
        w = split_line(c)
        if w[0] in ("start", "gui", "run", "demo", "batch", "undo", "redo"):
            print(f"{{warn}}start: '{w[0]}' isn't run at the start - take it out of general.session_start{{/}}")
            continue
        mode, why = _at_start(w, known)
        if mode == "skip":
            if not quiet:
                print(f"{{head}}> {c}{{/}}  {{note}}(not needed: {why}){{/}}")
            continue
        if mode == "ask":
            from .prompt import gui_asker, terminal
            if not (terminal() or gui_asker() is not None):
                problems += 1
                print(f"{{err}}start: '{c}'{{/}} - {why}")
                continue
            print(f"{{head}}> {c}{{/}}")             # it asks things: not captured
            try:
                rc = dispatch(w, known) or 0
            except SystemExit as e:
                rc = e.code if isinstance(e.code, int) else 1
                if isinstance(e.code, str):
                    print(e.code)
            problems += 1 if rc else 0
            continue
        if not quiet:
            print(f"{{head}}> {c}{{/}}")
        msg, rc = "", 0
        with (captured() if quiet else contextlib.nullcontext()) as buf:
            try:
                rc = dispatch(w, known) or 0
            except SystemExit as e:                   # e.g. 'sections' with no song yet
                rc = e.code if isinstance(e.code, int) else 1
                msg = e.code if isinstance(e.code, str) else ""
        if not quiet:
            if msg:
                print(msg)
            continue
        bad = [ln for ln in buf.getvalue().splitlines() if "{err}" in ln]
        if bad or rc:
            problems += 1
            print(f"{{err}}start: '{c}'{{/}}" + (f" - {msg}" if msg else (" failed" if rc and not bad else "")))
            for ln in bad[:12]:
                print(ln)
    if quiet:
        print("{note}(start: " + ", ".join(cmds) + (f" - {problems} with problems" if problems else " - no problems")
              + "; 'start --no-quiet' shows everything){/}")
    return 1 if problems else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool start", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="show the commands, run nothing")
    ap.add_argument("--quiet", action=argparse.BooleanOptionalAction, default=True,
                    help="only problems (the default); --no-quiet: everything they print")
    a = ap.parse_args(argv)
    if a.list:
        cs = commands()
        print("general.session_start: " + (", ".join(cs) if cs else "(none)")
              + "   {note}('pref general.session_start' changes it){/}")
        return 0
    from .update import at_start
    at_start("start")                                # 0.24.56: a newer seqtool? (one line here)
    return run_all(a.quiet)


if __name__ == "__main__":
    sys.exit(main())
