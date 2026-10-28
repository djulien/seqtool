# seqtool-command: undo | undo_cmd | refine | undo the last command that changed your settings (one command = one step)
# seqtool-command: redo | redo_cmd | refine | redo what 'undo' undid
"""seqtool undo [N] | redo [N] | undo --list

Every command you give that changes your settings - preferences, per-song settings
(sections, pins, seeds, lyrics, reactions), name rules, baselines - is one undo
step, labelled with the command line. 'undo' puts those files back as they were
before the command; 'redo' puts them back again. Afterwards the last run is
repeated (the analysis is reused) so the plan matches, and what changed is shown.

    undo              undo the last step          undo 3    the last three
    redo              redo the last undone step
    undo --list       the steps you can undo and redo

A new command after an undo clears the redo steps, as in an editor. Not covered:
the stored show layout and the xLights training (they are re-learned, not edited),
and files a command writes elsewhere (results are rebuilt by the repeated run).
The steps are kept in your preference folder (undo/), so they survive a restart.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from . import config
from .log import good, info, warn

KEEP = 50                                   # steps kept
SKIP = {"answers.json", "history", "history.txt"}          # remembered answers and command history are not settings
READ_ONLY = {"undo", "redo", "help", "-h", "status", "explain", "inspect", "doctor", "effects", "presets", "pwd",
             "memory", "gui", "test", "version", "clear", "trace", "play", "pause", "seek", "volume", "speed",
             "tutorial", "check"}
_depth = threading.local()


def _files() -> list[Path]:
    ud = config.user_dir()
    if not ud.is_dir():
        return []
    out = [f for f in ud.glob("*.json") if f.name not in SKIP]
    out += list((ud / "baselines").glob("*.json")) if (ud / "baselines").is_dir() else []
    return sorted(out)


def snapshot() -> dict[str, str]:
    ud = config.user_dir()
    snap = {}
    for f in _files():
        try:
            snap[str(f.relative_to(ud))] = f.read_text(encoding="utf-8")
        except OSError:
            pass
    return snap


def _store() -> Path:
    return config.user_dir() / "undo" / "steps.json"


def _load() -> dict:
    f = _store()
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"undo": [], "redo": []}
    except (ValueError, OSError):
        return {"undo": [], "redo": []}


def _save(st: dict) -> None:
    f = _store()
    f.parent.mkdir(parents=True, exist_ok=True)
    st["undo"] = st["undo"][-KEEP:]
    st["redo"] = st["redo"][-KEEP:]
    f.write_text(json.dumps(st) + "\n", encoding="utf-8")


def record(cmd: str, argv: list[str], run):
    """Run a command; if it changed settings files, keep it as one undo step."""
    depth = getattr(_depth, "n", 0)
    if depth or cmd in READ_ONLY or "-h" in argv or "--help" in argv:
        return run()
    _depth.n = depth + 1
    try:
        before = snapshot()
        rc = run()
    finally:
        _depth.n = depth
    after = snapshot()
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    if changed:
        st = _load()
        st["undo"].append({"label": " ".join([cmd, *argv]).strip(), "files": changed,
                           "before": {k: before.get(k) for k in changed}, "after": {k: after.get(k) for k in changed}})
        st["redo"] = []
        _save(st)
    return rc


def _apply(state: dict) -> None:
    ud = config.user_dir()
    for rel, text in state.items():
        f = ud / rel
        if text is None:
            f.unlink(missing_ok=True)
        else:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8")


def _rerun_and_show() -> None:
    """Repeat the last run quietly so the plan follows the restored settings."""
    if not config.answer("last_run") or not config.answer("last_matchup"):
        return
    from ..matchup.reroll import _context, diff, plan_columns, rerun
    from .canonical import read_json
    try:
        _, old_m, profile, _ = _context()
    except SystemExit:
        return
    info("re-running the plan (analysis is reused) ...")
    try:
        rerun()
    except SystemExit as e:
        warn(f"the plan wasn't re-run: {e} - 'run' updates it")
        return
    new_m = read_json(Path(config.answer("last_matchup")))
    from .canonical import read_json as _rj
    _, _, profile, _ = _context()
    lines = diff(plan_columns(old_m, profile), plan_columns(new_m, profile), profile)
    print("\n".join(lines) if lines else "  (the plan is the same)")


def _step(direction: str, argv) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog=f"seqtool {direction}", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("n", nargs="?", type=int, default=1)
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    st = _load()
    if a.list:
        if not st["undo"] and not st["redo"]:
            print("nothing to undo yet - commands that change your settings become undo steps")
            return 0
        for i, s_ in enumerate(reversed(st["undo"]), 1):
            print(f"  undo {i}: {s_['label']}  {{note}}({', '.join(s_['files'])}){{/}}")
        for i, s_ in enumerate(reversed(st["redo"]), 1):
            print(f"  redo {i}: {s_['label']}")
        return 0
    src, dst = ("undo", "redo") if direction == "undo" else ("redo", "undo")
    if not st[src]:
        print(f"nothing to {direction}" + (" - 'undo' first" if direction == "redo" else
                                           " (commands that change your settings become undo steps)"))
        return 0
    done = []
    for _ in range(max(1, a.n)):
        if not st[src]:
            break
        s_ = st[src].pop()
        _apply(s_["before"] if direction == "undo" else s_["after"])
        st[dst].append(s_)
        done.append(s_["label"])
    _save(st)
    good(f"{direction}: " + "; ".join(f"'{x}'" for x in done))
    _rerun_and_show()
    more = st[src]
    if more:
        info(f"  next {direction}: '{more[-1]['label']}'" + ("" if direction == "redo" else "  ('redo' takes it back)"))
    return 0


def undo_cmd(argv=None) -> int:
    return _step("undo", list(argv or []))


def redo_cmd(argv=None) -> int:
    return _step("redo", list(argv or []))


if __name__ == "__main__":
    sys.exit(undo_cmd(sys.argv[1:]))
