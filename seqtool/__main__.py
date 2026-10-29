#!/usr/bin/env python3
"""seqtool - music-to-light-sequence toolchain.

usage: seqtool                          interactive prompt (type 'help')
       seqtool <command> [options]      run one command and exit
       seqtool -demo [demo options]     run the demo
       seqtool <command> -h             help for one command
Any unique start of a command works ('expl' = explain).

global options (before the command):
  -demo, --demo          run the demo
  --gui                  open the live browser GUI (waveform, sections, effects, console)
  --version              print the version
  --test                 run the unit tests
  --quiet                hide progress messages
  --install=ask|yes|no   optional package installs (default ask)
  --stale=ask|rebuild|warn   stale intermediate files (default ask)
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import re
import shlex
import sys
import traceback
from glob import glob
from pathlib import Path

if __package__ in (None, ""):          # executed as a plain script: make the package importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "seqtool"

PKG = Path(__file__).resolve().parent
TAG = re.compile(r"^# seqtool-command:\s*([\w-]+)\s*\|\s*(\w+)\s*\|\s*(\w+)\s*\|\s*(.*)$", re.M)
# help topics: topic -> (title, command sections it lists)
TOPICS = {"refine": ("Refine (after a run: change choices, fix sections)", ["refine"]),
          "setup": ("Setup (once per show / xLights version)", ["setup"]),
          "stages": ("Single stages (run any of them on their own, in any order)", ["stages"]),
          "commands": ("Other commands", ["look", "tools"])}
BUILTINS = {"help": ("tools", "help [topic|command]"),
            "test": ("tools", "run the unit tests (-v for the full list)"),
            "version": ("tools", "print the seqtool version"),
            "clear": ("tools", "clear the screen (prompt only)"),
            "trace": ("tools", "full traceback of the last error (prompt only)"),
            "history": ("tools", "the commands you typed (history N | TEXT | -c; !N, !! or !TEXT runs one again)"),
            "quit": ("tools", "leave the prompt (also: exit, Ctrl-D)")}


def discover() -> dict[str, tuple[str, str, str, str]]:
    """name -> (module, function, section, help), read from '# seqtool-command:' tags
    without importing anything, so startup stays instant."""
    found = {}
    for f in sorted(PKG.rglob("*.py")):
        if f.name == "__main__.py":
            continue
        try:
            head = f.read_text(encoding="utf-8")[:2000]
        except OSError:
            continue
        for name, func, section, helptext in TAG.findall(head):
            mod = "seqtool." + ".".join(f.relative_to(PKG).with_suffix("").parts)
            found[name] = (mod, func, section, helptext.strip())
    return found


def _section_lines(cmds, sections) -> list[str]:
    rows = {n: c[3] for n, c in cmds.items() if c[2] in sections}
    rows.update({n: h for n, (sec, h) in BUILTINS.items() if sec in sections})
    return [f"  {{do}}{n:<16}{{/}} {h}" for n, h in sorted(rows.items())]


def usage(cmds, topic: str | None = None) -> str:
    from seqtool import __version__
    parts = __doc__.split("\n\n")
    ver = f"{{note}}seqtool {__version__}{{/}}"
    if topic:
        title, secs = TOPICS[topic]
        return "\n".join([ver, f"{{head}}{title}:{{/}}"] + _section_lines(cmds, secs))
    lines = ["{head}" + parts[0] + "{/}" + f"  {ver}", "", parts[1], "", parts[2].rstrip(), "", "{head}Pipeline:{/}"]
    lines += _section_lines(cmds, ["pipeline"])
    lines += ["", "{head}More help:{/}"]
    lines += [f"  {{do}}help {t:<11}{{/}} {TOPICS[t][0].split(' (')[0].lower()}: "
              + ", ".join(sorted([n for n, c in cmds.items() if c[2] in TOPICS[t][1]]
                                 + [n for n, (sec, _) in BUILTINS.items() if sec in TOPICS[t][1]]))
              for t in TOPICS]
    lines.append("  {do}help COMMAND    {/} options for one command")
    lines.append("  {do}tutorial        {/} guided walk-throughs of common tasks")
    return "\n".join(lines)


def run_tests(argv=None) -> int:
    """seqtool test [-v] [Class.test ...]: one progress line rewritten in place; -v for the
    full list. Tests never prompt."""
    import shutil as _sh
    import tempfile
    import time
    import unittest
    argv = list(argv or [])
    verbose = "-v" in argv or "--verbose" in argv
    names = [a for a in argv if not a.startswith("-")]
    root = PKG.parent
    tests = root / "tests"
    if not tests.is_dir():
        print(f"no tests in this copy ({tests}): packages leave them out - 'package --with-tests' includes them", file=sys.stderr)
        return 2
    saved_env = {k: os.environ.get(k) for k in ("SEQTOOL_STALE", "SEQTOOL_NONINTERACTIVE", "SEQTOOL_PREFS")}
    os.environ.update(SEQTOOL_STALE="rebuild", SEQTOOL_NONINTERACTIVE="1",
                      SEQTOOL_PREFS=tempfile.mkdtemp(prefix="seqtool-prefs-"))
    from seqtool.common import config, deps, freshness
    freshness.set_mode("rebuild")
    deps.set_mode("no")
    config.set_user_dir(None)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        loader = unittest.TestLoader()
        suite = (loader.loadTestsFromNames([f"tests.test_mvp.{n}" for n in names]) if names
                 else loader.discover(str(tests), top_level_dir=str(root)))
        if verbose:
            return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
        total = suite.countTestCases()
        term = sys.__stderr__
        width = max(40, _sh.get_terminal_size((100, 20)).columns - 1)
        tty = term.isatty()

        class Progress(unittest.TestResult):
            n = 0

            def startTest(self, test):
                super().startTest(test)
                Progress.n += 1
                line = f"[{Progress.n:>3}/{total}] {type(test).__name__}.{test._testMethodName}"
                term.write(("\r" + line[:width].ljust(width)) if tty else line + "\n")
                term.flush()

        t0 = time.time()
        result = Progress()
        suite.run(result)
        if tty:
            term.write("\r" + " " * width + "\r")
        for kind, items in (("FAIL", result.failures), ("ERROR", result.errors)):
            for test, tb in items:
                term.write(f"\n{kind}: {test.id()}\n{tb}")
        bad = len(result.failures) + len(result.errors)
        term.write(f"Ran {result.testsRun} tests in {time.time() - t0:.1f}s - "
                   + ("OK\n" if not bad else f"{bad} FAILED\n"))
        return 0 if not bad else 1
    finally:
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        config.set_user_dir(None)


from seqtool.common.args import split_line  # noqa: E402 - also makes quoted "--x" words positional


def apply_globals(argv: list[str]) -> tuple[list[str], int | None]:
    """Consume leading global options. Returns (rest, exit code if handled)."""
    from seqtool import __version__
    from seqtool.common import deps, freshness, log
    while argv and (argv[0].startswith("--") or argv[0] == "-demo"):
        opt = argv.pop(0)
        if opt in ("-demo", "--demo"):
            argv.insert(0, "demo")
            break
        if opt == "--gui":
            import webbrowser
            from seqtool.gui import server
            url = server.ensure_running()
            webbrowser.open(url)
            log.info(f"browser GUI: {url}")
        elif opt == "--later":                     # 0.24.39: the change now, the plan later ('replan')
            LATER[0] = True
        elif opt == "--quiet":
            log.set_level(35)
        elif opt.startswith("--install="):
            deps.set_mode(opt.split("=", 1)[1])
        elif opt.startswith("--stale="):
            freshness.set_mode(opt.split("=", 1)[1])
        elif opt == "--version":
            print(f"seqtool {__version__}")
            return argv, 0
        elif opt == "--test":
            return argv, run_tests(argv)
        elif opt in ("--help", "-h"):
            print(usage(discover()))
            return argv, 0
        else:
            print(f"unknown option {opt}  (seqtool -h)", file=sys.stderr)
            return argv, 2
    return argv, None


LATE_GLOBALS = ("--stale", "--install", "--quiet", "--later")
LATER = [False]
NEEDS_PLAN = {"xlights-export", "bundle", "explain", "inspect", "status"}     # they read the plan


def late_globals(mod: str, args: list[str]) -> tuple[list[str], int | None]:
    """0.24.34: seqtool's own options after the command name too ('batch "..." --stale=rebuild'),
    when the command has no option of that name itself; a quoted word ('"--quiet"') is text."""
    from .common.args import Literal
    own = None
    out, i = [], 0
    while i < len(args):
        w = args[i]
        name = w.split("=", 1)[0]
        if not isinstance(w, Literal) and name in LATE_GLOBALS:
            if own is None:
                try:
                    spec = importlib.util.find_spec(mod)
                    own = Path(spec.origin).read_text(encoding="utf-8") if spec and spec.origin else ""
                except Exception:  # noqa: BLE001
                    own = ""
            if f'"{name}"' not in own:
                if name not in ("--quiet", "--later") and "=" not in w and i + 1 < len(args):
                    w = f"{name}={args[i + 1]}"           # '--stale rebuild'
                    i += 1
                _, rc = apply_globals([w])
                if rc is not None:
                    return args, rc
                i += 1
                continue
        out.append(w)
        i += 1
    return out, None


def dispatch(argv: list[str], cmds: dict) -> int:
    from seqtool import __version__
    argv, rc = apply_globals(list(argv))
    if rc is not None:
        return rc
    if not argv:
        return 0
    cmd = argv[0]
    if cmd in ("-h", "help"):
        if len(argv) > 1:
            t = argv[1].lower()
            topic = next((k for k in TOPICS if k.startswith(t)), None)
            if topic and t not in cmds:
                print(usage(cmds, topic))
                return 0
            if t in ("effects", "presets") and t in cmds:   # their listing is the help ('rules' has its own, 0.19.9)
                return dispatch([t] + argv[2:], cmds)
            return dispatch([argv[1], "-h"], cmds)
        print(usage(cmds))
        return 0
    if cmd == "clear":
        from .common.color import _windows_vt
        sys.stdout.write("\033[2J\033[H" if _windows_vt(sys.stdout) else "\n" * 40)
        sys.stdout.flush()
        return 0
    if cmd == "test":
        return run_tests(argv[1:])
    if cmd == "version":
        print(f"seqtool {__version__}")
        return 0
    if cmd == "history":
        from .common import history
        return history.main(argv[1:])
    if cmd not in cmds:
        hits = [c for c in list(cmds) + ["test", "version", "clear", "history"] if c.startswith(cmd)]
        if len(hits) != 1:
            why = f"ambiguous: {', '.join(sorted(hits))}" if hits else "unknown"
            print(f"{why} command {cmd!r}  ('help' lists commands)", file=sys.stderr)
            return 2
        return dispatch([hits[0]] + argv[1:], cmds)
    _check_updated()
    if cmd in BASELINE_ARG and "--baseline" in argv[1:]:
        return _for_baseline(cmd, argv[1:], cmds)
    mod, func, _, _ = cmds[cmd]
    rest, rc = late_globals(mod, argv[1:])
    if rc is not None:
        return rc
    argv = [cmd] + rest
    from .common.paths import anchored
    from .common import undo
    later, LATER[0] = LATER[0], False
    if not later and cmd in NEEDS_PLAN:               # 0.24.40: a change made --later is planned first
        from .common import config as _c
        if _c.answer("replan_pending"):
            from .matchup import replan_cmd
            print("{note}(making the plan first - changes made with --later are waiting for it){/}")
            replan_cmd.main([])
    if later:                                         # 0.24.39: settings now, the plan when 'replan' runs
        from .matchup import reroll
        reroll._DEFER["n"] += 1
        reroll._DEFER["why"] = "gui" if later == "gui" else "later"
    try:
        with anchored(anchor_for(cmd, argv[1:])):
            return undo.record(cmd, argv[1:],           # one command = one undo step (if it changed settings)
                               lambda: _friendly(lambda: run_command(cmd, getattr(importlib.import_module(mod), func), argv[1:])))
    finally:
        if later:
            from .matchup import reroll
            reroll._DEFER["n"] -= 1
            reroll._DEFER.pop("why", None)
            if reroll._DEFER["pending"] and not reroll._DEFER["n"]:
                reroll._DEFER["pending"] = False
                from .common import config as _c
                _c.remember("replan_pending", True)
                pass


def _friendly(call):
    """User mistakes (a file that isn't there, an audio file where a .json belongs) as a
    plain message instead of a Python error."""
    from .common.canonical import NotJSON
    try:
        return call()
    except NotJSON as e:
        raise SystemExit(f"{e} - give the song or its .json result (e.g. 'classify-music SONG.mp3')") from None
    except FileNotFoundError as e:
        from .common.paths import where
        raise SystemExit(f"not found: {e.filename}{where(e.filename or '')} - check the name "
                         "('pwd' shows the working folder, 'cd FOLDER' changes it)") from None
    except Exception as e:                                       # 0.24.55: a missing package - its own fix line
        from .common.deps import MissingDependency
        from .common.paths import NoMatch
        if isinstance(e, (MissingDependency, NoMatch)):
            raise SystemExit(str(e)) from None
        if isinstance(e, OSError) and getattr(e, "winerror", None) == 123:     # 0.24.58: '*' etc. in a name
            raise SystemExit(f"'{e.filename}' isn't a file name Windows allows (a * or ? that matched nothing?) - "
                             "'pwd' shows the working folder") from None
        raise


# commands that take a song and also understand '--baseline [N]' (as 'run' does): how the
# song is given to them
SWITCH = "@current"
BASELINE_ARG = {"analyze-music": None, "classify-music": None, "match": "--music", "validate": "--matchup",
                "lyrics": "--audio", "sections": "--audio",
                # these work on the current song: '--baseline N' makes song N the current song first (0.19)
                "xlights-export": SWITCH, "explain": SWITCH, "pin": SWITCH, "unpin": SWITCH, "reroll": SWITCH,
                "promote": SWITCH, "demote": SWITCH,
                "gui": SWITCH, "status": SWITCH, "inspect": SWITCH, "play": SWITCH}


_UPDATED_SAID = []


def _check_updated() -> None:
    """A long session (the seqtool> prompt, the GUI) keeps running the code it started
    with: say so when seqtool was updated on disk since."""
    if _UPDATED_SAID:
        return
    from seqtool import __version__
    try:
        disk = (Path(__file__).resolve().parents[1] / "VERSION").read_text().strip()
    except OSError:
        return
    if disk != __version__:
        _UPDATED_SAID.append(disk)
        from .common.log import warn
        warn(f"seqtool {disk} is installed, but this session is still running {__version__} - "
             "quit and start seqtool again to use the new version")


def _for_baseline(cmd: str, args: list[str], cmds: dict) -> int:
    """'CMD --baseline N': CMD on song N of the baseline; '--baseline' alone: on each song."""
    from .baseline import songs_of
    i = args.index("--baseline")
    n = args[i + 1] if i + 1 < len(args) and args[i + 1].isdigit() else None
    rest = args[:i] + args[i + (2 if n else 1):]
    songs = songs_of()
    if not songs:
        raise SystemExit("no baseline yet - 'baseline add' adds the current song")
    if n is not None and not 1 <= int(n) <= len(songs):
        raise SystemExit(f"{cmd} --baseline N: N is 1-{len(songs)} ('baseline' lists the songs), or no N for all")
    nums = list(range(1, len(songs) + 1)) if n is None else [int(n)]
    flag = BASELINE_ARG[cmd]
    rc = 0
    for k in nums:
        s = songs[k - 1]
        print(f"{{head}}baseline song {k}: {s.name}{{/}}", flush=True)
        if flag == SWITCH:
            if not make_current(s, k):
                rc = max(rc, 1)
                continue
            rc = max(rc, dispatch([cmd] + rest, cmds) or 0)
        else:
            rc = max(rc, dispatch([cmd] + rest + ([flag] if flag else []) + [str(s)], cmds) or 0)
    return rc


def make_current(song: Path, k: int | None = None) -> bool:
    """Make a song the current song (its newest results, and 'run --audio SONG' as the run
    that pin / reroll repeat), for the commands that work on the current song."""
    from .common import config, current
    from .common.log import warn
    cur = current.song(song)
    if cur is None or cur.get("matchup") is None:
        warn(f"{song.name} has no results yet - e.g. 'run --baseline {k}'" if k else
             f"{song.name} has no results yet - e.g. 'run --audio {song}'")
        return False
    current.remember(audio=song, music=cur["music"], matchup=cur["matchup"])
    config.remember("last_out", str(Path(cur["matchup"]).parent.resolve()))
    lr = config.answer("last_run") or {}
    cwd = Path(lr.get("cwd", "."))
    same = lr.get("cmd") == "run" and any((cwd / x).resolve() == song.resolve()
                                          for x in lr.get("argv", []) if not str(x).startswith("-"))
    if not same:                                  # the last run was another song: repeat this one's
        config.remember("last_run", {"cmd": "run", "argv": ["--audio", str(song.resolve())], "cwd": str(Path.cwd())})
    return True


SONG_CMDS = {"analyze-music", "classify-music", "match", "validate", "sections", "lyrics", "reroll", "pin", "promote", "demote",
             "unpin", "explain", "status", "inspect", "react", "baseline", "xlights-export"}
LAYOUT_CMDS = {"layout", "xlights-import", "groups", "analyze-models", "rules"}


def anchor_for(cmd: str, args: list[str]):
    """The file a command mainly works on, so its messages show paths next to it
    relative to it: the song (song commands) or the show layout (layout commands).
    'run' and 'demo' anchor themselves once the song is known."""
    try:
        from .common import config
        if cmd in SONG_CMDS:
            if cmd == "analyze-music":
                pos = [x for x in args if not x.startswith("-")]
                if pos and Path(pos[0]).is_file():
                    return Path(pos[0])
            if "--audio" in args and args.index("--audio") + 1 < len(args):
                return Path(args[args.index("--audio") + 1])
            la = config.answer("last_audio")
            return Path(la) if la else None
        if cmd in LAYOUT_CMDS:
            from .layout import store
            pos = [x for x in args if not x.startswith("-")]
            if cmd in ("layout", "xlights-import") and pos and Path(pos[0]).exists():
                try:
                    return store.find_rgbeffects(Path(pos[0]))
                except SystemExit:
                    return None
            src = store.source_info()
            return Path(src["path"]) if src else None
    except Exception:  # noqa: BLE001 - only affects how paths are shown
        return None
    return None


class MissingArgs(Exception):
    pass


def run_command(name: str, fn, args: list[str]) -> int:
    """Run a command; on a terminal, prompt for required arguments that are missing
    (previous answers are offered as defaults) and run it again."""
    import argparse
    from seqtool.common.prompt import ask, interactive
    if not interactive():
        return fn(args) or 0
    orig = argparse.ArgumentParser.error

    def error(self, message):
        if "the following arguments are required:" in message:
            raise MissingArgs(message.split(":", 1)[1])
        orig(self, message)
    argparse.ArgumentParser.error = error
    try:
        try:
            return fn(args) or 0
        except MissingArgs as m:
            flags: list[str] = []
            positional: list[str] = []
            for raw in [x.strip() for x in str(m).split(",") if x.strip()]:
                flag = raw.split("/")[0]                      # "--audio" or "model"
                label = flag.lstrip("-")
                val = ask(f"{name}: {label}?", "", remember_as=f"arg:{name}:{label}")
                if val and any(ch in val for ch in "*?["):
                    from seqtool.common.paths import expand
                    val = str(expand(val))
                if not val:
                    print("cancelled")
                    return 1
                if flag.startswith("-"):
                    flags += [flag, val]
                else:
                    positional.append(val)
            return fn(args + flags + positional) or 0
    finally:
        argparse.ArgumentParser.error = orig


# ------------------------------------------------------------------ REPL --
def _expand(tokens: list[str]) -> list[str]:
    """~ is expanded here; glob patterns are left to the commands, whose file and
    folder arguments resolve them (one match used, several -> pick one)."""
    return [os.path.expanduser(t) if t.startswith("~") else t for t in tokens]


def repl(cmds: dict) -> int:
    from seqtool import __version__
    from seqtool.common import config
    from seqtool.common import history as _hs
    _hs.session_start("prompt")
    from seqtool.common import update as _up
    _up.at_start("prompt")                       # 0.24.56: a newer seqtool? (general.check_updates)
    from seqtool.common import current as _cur
    _cur.follow_song()
    try:
        import readline
        from seqtool.common import history as _h
        for x in _h.lines():                          # the GUI's commands too (one file, common/history)
            readline.add_history(x)
        names = sorted(list(cmds) + list(BUILTINS) + ["exit"] + list(TOPICS))

        hints: dict[str, str] = {}

        def complete(text, state):
            """Tab: commands, then the command's options, sub-commands and values - files,
            props, effects, sections ... (common/complete.py, shared with the GUI console)."""
            if state == 0:
                buf = readline.get_line_buffer()[:readline.get_endidx()]
                try:
                    from seqtool.common.complete import complete as engine, complete_answer
                    from seqtool.common.prompt import answer_kind
                    res = complete_answer(buf, answer_kind()) if answer_kind() else engine(buf)
                    pre = buf[len(buf) - len(text):res["start"]] if res["start"] > len(buf) - len(text) else ""
                    complete.opts = [pre + x["text"] + (" " if x.get("space", True) else "") for x in res["items"]
                                     if (pre + x["text"]).startswith(text) or not text or pre
                                     or any(c in text for c in "*?[\"")]     # 0.24.58: --audio=, patterns
                    hints.clear()
                    hints.update({x["text"]: x.get("hint", "") for x in res["items"]})
                except Exception:  # noqa: BLE001 - never break the prompt
                    complete.opts = [n + " " for n in names if n.startswith(text)] if " " not in buf.lstrip() else \
                        [p + ("/" if os.path.isdir(p) else " ") for p in glob(os.path.expanduser(text) + "*")]
            return complete.opts[state] if state < len(complete.opts) else None
        complete.opts = []

        def show_matches(substitution, matches, longest):
            print()
            w = max((len(m.strip()) for m in matches), default=0)
            for m in matches[:40]:
                h = hints.get(m.strip(), "")
                print(f"  {m.strip():<{w}}  {h[:60]}" if h else f"  {m.strip()}")
            if len(matches) > 40:
                print(f"  ... {len(matches) - 40} more")
            print("seqtool> " + readline.get_line_buffer(), end="", flush=True)
        readline.set_completer(complete)
        readline.set_completer_delims(" \t")
        readline.set_completion_display_matches_hook(show_matches)
        readline.parse_and_bind("tab: complete")
    except ImportError:
        readline = None
        if os.name == "nt":                     # 0.24.58: Windows' Python has no line editor of its own
            print("(Tab completion at this prompt needs pyreadline3 on Windows: 'py -m pip install pyreadline3', "
                  "then start seqtool again - the GUI's console completes without it)")
    print(f"seqtool {__version__} - type 'help' for commands, 'quit' to leave")
    try:                                              # 0.24.34: general.session_start (doctor, sections, feel)
        from seqtool.common import start_cmd
        from seqtool.gui import server as _gs
        if start_cmd.commands() and _gs.running() is None:   # 0.24.37: with --gui they run in its console
            start_cmd.run_all()
    except Exception as e:  # noqa: BLE001 - never stop the prompt from starting
        print(f"(the start commands stopped: {e})")
    last_tb = None
    while True:
        try:
            line = input("seqtool> ").strip()
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            print()
            continue
        if not line or line.startswith("#"):
            continue
        if line.startswith("!"):                     # !! / !N / !TEXT: a command from the history
            from seqtool.common import history
            got = history.expand(line)
            if got is None:
                print(f"no command {line} in the history - 'history' lists them")
                continue
            line = got
            print(line)
            if readline:
                readline.replace_history_item(readline.get_current_history_length() - 1, line)
        from seqtool.common import history as _hist
        if not line.startswith("history"):
            _hist.add(line)
        if line in ("quit", "exit", "q", "bye"):
            break
        if line == "trace":
            print(last_tb or "no error so far")
            continue
        try:
            argv = _expand(split_line(line))
        except ValueError as e:
            print(f"can't parse that line: {e}")
            continue
        try:
            from seqtool.gui import server as gui_server
            from seqtool.gui.server import EXEC_LOCK

            def waiting(source, held):
                print(f"(waiting for the {source} command '{held}' to finish ...)")
            EXEC_LOCK.acquire("terminal", line, waiting)   # never overlaps a command from the browser GUI
            try:
                dispatch(argv, cmds)
            finally:
                EXEC_LOCK.release()
                from seqtool.common import current as _cur2
                _cur2.after_command()                    # a new current song: its folder (0.21.4)
                if gui_server.running() is not None:
                    gui_server.running().check_now()     # refresh open GUI pages at once
        except SystemExit as e:              # argparse errors, explicit SystemExit("message")
            if e.code not in (0, None) and not isinstance(e.code, int):
                print(e.code)
        except KeyboardInterrupt:
            print("\ninterrupted")
        except Exception as e:  # keep the session alive
            last_tb = traceback.format_exc()
            print(f"error: {e.__class__.__name__}: {e}   ('trace' shows details)")
    return 0                                         # the history is saved as each command is typed (common/history)


def _serve_until_interrupted() -> None:
    from seqtool.gui import server
    srv = server.running()
    if srv is None:
        return
    print(f"browser GUI running at {srv.url}  - Ctrl-C to stop")
    try:
        while True:
            import time
            time.sleep(3600)
    except KeyboardInterrupt:
        print()
    finally:
        server.stop()


def _colour_argparse() -> None:
    """Command help (-h) gets the same colour codes as the rest: headings teal."""
    import argparse
    if getattr(argparse.ArgumentParser, "_seqtool_coloured", False):
        return
    orig = argparse.ArgumentParser.format_help

    def fmt(self):
        from seqtool import __version__
        text = orig(self)
        text = re.sub(r"^(usage:)", r"{head}\1{/}", text)
        text = re.sub(r"^(positional arguments:|options:|optional arguments:)$", r"{head}\1{/}", text, flags=re.M)
        if self.prog.startswith("seqtool"):                # every help says which version (0.19.10)
            text = f"{{note}}seqtool {__version__}{{/}}\n" + text
        return text
    argparse.ArgumentParser.format_help = fmt
    argparse.ArgumentParser._seqtool_coloured = True


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    from seqtool.common import color
    color.install()                                   # inline colour codes -> ANSI / plain
    from seqtool.common.paths import ensure_work_dir
    was = os.getcwd()
    moved = ensure_work_dir()                         # e.g. the .pyz double-clicked on Windows: System32
    if moved is not None:
        from seqtool.common.log import warn
        warn(f"seqtool can't keep its files in {was}{os.sep} - working in {moved}{os.sep} instead "
             "{note}('cd FOLDER' changes it; or start seqtool from a command prompt in the folder you want){/}")
    from seqtool.common import config as _config
    _config.user_dir()                                # fixed now, before the working folder moves
    note = _config.old_folder_note()
    if note:
        from seqtool.common.log import warn
        warn(note)
    _colour_argparse()
    cmds = discover()
    color.set_commands(list(cmds) + list(BUILTINS) + ["tutorial"])
    from seqtool.common.prompt import interactive
    if not argv:
        if interactive():
            try:
                return repl(cmds)
            finally:                                  # a GUI opened with 'gui' closes with the prompt
                from seqtool.gui import server
                server.stop()
        print(usage(cmds))
        return 0
    from seqtool import __version__
    from seqtool.common import log
    rest, rc = apply_globals(list(argv))
    if rc is not None:
        return rc
    from seqtool.gui import server
    if not rest:                                      # e.g. 'seqtool --gui'
        if server.running() is None:
            return 0
        if interactive():
            try:
                return repl(cmds)
            finally:
                server.stop()
        _serve_until_interrupted()
        return 0
    if rest[0] not in ("test", "help", "-h", "version"):
        log.info(f"seqtool {__version__}")
    rc = dispatch(rest, cmds)
    if server.running() is not None:                  # 'seqtool --gui run ...': keep the GUI up afterwards
        _serve_until_interrupted()
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:          # e.g. piped into head
        sys.exit(0)
