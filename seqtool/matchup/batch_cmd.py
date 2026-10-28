# seqtool-command: batch | main | refine | several changes at once - one re-plan, one undo step: batch "pin A @#3 spirals; react B beat --over" | batch changes.txt
"""seqtool batch "CMD; CMD; ..." | batch FILE [--dry-run]

Runs several commands as one change (0.24.29): each does its part, the plan is made once at
the end (not after every command), and the whole batch is one undo step ('undo' takes all
of it back).

    batch "pin MegaTree @#3 spirals; react Arches beat --over; palette rock"
    batch changes.txt              one command per line ('#' starts a comment); ';' works too
    batch changes.txt --dry-run    list the commands, change nothing

If a command fails, the batch stops there and its earlier commands are taken back too:
nothing of it is kept, and the plan is not made. Commands that read or show things
(explain, pin, react, cue, palette with no arguments ...) can be in a batch; these can't:
run, demo, gui, batch, undo, redo.
"""
from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

from ..common.args import split_line
from ..common.log import good, info, warn

NOT_IN_BATCH = {"run", "demo", "gui", "batch", "undo", "redo", "test", "clear", "package", "xlights-kit"}


def commands(text: str) -> list[str]:
    """The commands in a batch: one per line or ';' between; '#' at a line's start or after a space
    (then a space or the end) starts a comment - '@#3' is a section, not a comment."""
    import re
    out = []
    for raw in text.replace("\r", "").split("\n"):
        line = re.split(r"(?:^|\s)#(?:\s|$)", raw, maxsplit=1)[0]
        for part in _split_semicolons(line):
            if part.strip():
                out.append(part.strip())
    return out


def _split_semicolons(line: str) -> list[str]:
    parts, cur, q = [], "", None
    for ch in line:
        if q:
            q = None if ch == q else q
        elif ch in "\"'":
            q = ch
        elif ch == ";":
            parts.append(cur)
            cur = ""
            continue
        cur += ch
    parts.append(cur)
    return parts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool batch", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("words", nargs="+", help='"CMD; CMD; ..." or a file with one command per line')
    ap.add_argument("--dry-run", action="store_true", help="list the commands, change nothing")
    a = ap.parse_args(argv)
    src = " ".join(a.words)
    f = Path(src).expanduser()
    try:                                       # a long list of commands is no file name (0.24.47)
        is_file = len(a.words) == 1 and "\n" not in src and ";" not in src and f.is_file()
    except OSError:
        is_file = False
    if is_file:
        text = f.read_text(encoding="utf-8")
    else:
        text = src
    cmds = commands(text)
    if not cmds:
        raise SystemExit('batch: no commands - e.g. batch "pin MegaTree @#3 spirals; react Arches beat --over"')
    from ..__main__ import discover, dispatch
    known = discover()
    for k, c in enumerate(cmds, 1):
        try:
            w = split_line(c)
        except ValueError as e:
            raise SystemExit(f"batch: command {k} ('{c}'): {e}") from None
        if w[0] in NOT_IN_BATCH:
            raise SystemExit(f"batch: '{w[0]}' can't be in a batch (command {k}) - run it on its own")
        if w[0] not in known:
            from ..common.suggest import suggest
            raise SystemExit(f"batch: command {k}: no command '{w[0]}'" + suggest(w[0], list(known)))
    if a.dry_run:
        print(f"{{head}}batch{{/}} ({len(cmds)} commands):")
        for k, c in enumerate(cmds, 1):
            print(f"  {k:>2}. {{do}}{c}{{/}}")
        return 0
    from ..common import undo
    from . import reroll
    before = undo.snapshot()
    old = None
    try:
        _, old_m, profile, _ = reroll._context()
        old = (old_m, profile)
    except SystemExit:
        pass
    reroll._DEFER["n"] += 1
    reroll._DEFER["pending"] = False
    failed = None
    try:
        for k, c in enumerate(cmds, 1):
            print(f"{{note}}[{k}/{len(cmds)}]{{/}} {{do}}{c}{{/}}")
            try:
                rc = dispatch(split_line(c), known)
            except SystemExit as e:
                rc, msg = (e.code if isinstance(e.code, int) else 1), (e.code if isinstance(e.code, str) else "")
                if msg:
                    print(f"{{err}}{msg}{{/}}")
            if rc:
                failed = (k, c)
                break
    finally:
        reroll._DEFER["n"] -= 1
        pending = reroll._DEFER["pending"]
        reroll._DEFER["pending"] = False
    if failed:
        changed = undo.snapshot() != before
        undo._apply({k: before.get(k) for k in set(before) | set(undo.snapshot())})
        if changed and failed[0] > 1:               # 0.24.36: results made by earlier commands (a split
            info("taking the batch back: the plan is made again from your settings as they were ...")
            try:                                     # writes the sections at once) are made again too
                reroll.rerun()
            except SystemExit as e:
                warn(f"the plan couldn't be made again ({e}) - 'run' makes it")
        warn(f"batch stopped at command {failed[0]} ('{failed[1]}'): the {failed[0] - 1} before it are taken back "
             "too - nothing of the batch is kept; fix that command and run the batch again")
        return 1
    if pending or undo.snapshot() != before:            # a change that doesn't re-plan by itself (sections ...) too
        info("making the plan once for the whole batch (analysis is reused) ...")
        reroll.rerun()
        if old:
            from ..common import config
            from ..common.canonical import read_json
            new_m = read_json(Path(config.answer("last_matchup")))
            lines = reroll.diff(reroll.plan_columns(old[0], old[1]), reroll.plan_columns(new_m, old[1]), old[1])
            print("\n".join(lines) if lines else "  (no visible change)")
    good(f"batch of {len(cmds)} command(s) done - one undo step ('undo' takes all of it back)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
