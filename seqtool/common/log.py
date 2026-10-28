"""Console logging, adapted from the user's my_utils.py.

Same call style (good/error/warn/info/debug/memo, inline-returning the last
arg, "@lineno" suffix), plus:
  * a numeric level filter (SEQTOOL_DEBUG env or set_level(); default 10 = all)
  * everything goes to stderr so stdout stays clean for piping JSON
  * colours are inline codes ({ok} ... {/}, see color.py); NO_COLOR / non-tty removes them
  * seconds(): hours factor fixed (was 360, should be 3600)
"""
from __future__ import annotations

import contextlib
import inspect
import io
import os
import sys
import time

START_TIME = time.perf_counter()

from .color import for_stream

# message kind -> inline colour code (see color.py)
CODES = {"good": "ok", "error": "err", "warn": "warn", "info": None, "debug": "note",
         "memo": "do", "stage": "head"}
LEVELS = {"error": 50, "warn": 40, "stage": 32, "good": 30, "info": 30, "memo": 20, "debug": 10}
_level = int(os.environ.get("SEQTOOL_DEBUG", "10"))
# "@lineno" suffixes: on for debug messages; SEQTOOL_LINENO=1 adds them to warnings/errors too
_show_lines = os.environ.get("SEQTOOL_LINENO", "0") == "1"


def set_level(level: int) -> None:
    global _level
    _level = int(level)


def _lineno(depth: int) -> int:
    try:
        return inspect.stack()[depth + 1].lineno
    except IndexError:
        return 0


def out(kind: str, *args, depth: int = 0, **kwargs):
    if LEVELS[kind] < _level:
        return args[-1] if args else None
    stream = kwargs.pop("file", sys.stderr)
    text = " ".join(str(a) for a in args)
    if kind == "debug" or (_show_lines and kind in ("error", "warn")):
        text += f"  @{_lineno(depth + 2)}"
    if CODES[kind]:
        text = "{" + CODES[kind] + "}" + text + "{/}"
    print(for_stream(text, stream), file=stream, **kwargs)
    return args[-1] if args else None


def good(*a, **k): return out("good", *a, **k)
def error(*a, **k): return out("error", *a, **k)
def warn(*a, **k): return out("warn", *a, **k)
def info(*a, **k): return out("info", *a, **k)
def debug(*a, **k): return out("debug", *a, **k)
def memo(*a, **k): return out("memo", *a, **k)


STAGES: list = []
PROGRESS = False
EOL = "\x1b[K\r"                                     # clear to the end of the line, back to its start


def rewrites(stream) -> bool:
    """Whether a progress line can be rewritten in place on this stream: a terminal, or the GUI
    console (whose streams say handles_cr)."""
    if getattr(stream, "handles_cr", False) or os.environ.get("SEQTOOL_TAGS") == "1":   # the GUI, or its child
        return True
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError, OSError):
        return False


def progress(text: str, stream=None, level: str | None = None) -> None:
    """A progress message (design rule, 0.24.32): it rewrites one line - the text, then
    clear-to-end-of-line and a carriage return - so a run of them doesn't scroll the useful
    output away; the next output (or progress_end) takes the line over. Where lines can't be
    rewritten (a log file, a pipe) it is an ordinary line. level: a log kind ('info') whose
    level must be shown; None = always (a silenced re-plan still says where it is)."""
    if level and LEVELS[level] < _level:
        return
    s = stream or sys.stderr
    if rewrites(s):
        s.write(for_stream(text, s) + EOL)
        s.flush()
    else:
        print(for_stream(text, s), file=s, flush=True)


def progress_end(stream=None) -> None:
    """Clears a progress line left by progress(), so a shorter line after it isn't mixed with it."""
    s = stream or sys.stderr
    if rewrites(s):
        s.write("\x1b[K")
        s.flush()


def stage(n: int, total: int, title: str, command: str = "", output: str = "") -> None:
    """Banner printed when a pipeline stage starts, so users can tell which stage
    produced which messages and files."""
    import time as _t
    STAGES.append((title, _t.monotonic()))             # 0.24.27: how long each stage took (rerun timings)
    if PROGRESS:                                       # 0.24.31: a silenced re-plan still says where it is
        import re as _re
        t = _re.sub(r"^matchup, iteration (\d+)", lambda m: f"planning, round {int(m.group(1)) + 1}", title)
        t = _re.sub(r"^validation, iteration (\d+)", lambda m: f"checking the plan, round {int(m.group(1)) + 1}", t)
        t = {"music analysis": "music analysis (reused when it can be)", "summary": "writing the summary"}.get(t, t)
        progress("{note}  ... " + t + "{/}")
    text = f"{n}/{total} {title}"
    if output:
        text += f" -> {output}"
    if command:
        text += f"   [seqtool {command}]"
    out("stage", "\n{b}== " + text + "{/}")


def seconds(duration: float) -> str:
    for factor, units in ((3600, "hr"), (60, "min"), (1, "sec"), (1e-3, "msec"), (1e-6, "usec")):
        if duration >= factor:
            return f"{duration / factor:.1f} {units}".replace(".0 ", " ")
    return "(no time)"


def elapsed(since: float | None = None) -> str:
    if not hasattr(elapsed, "previous"):
        elapsed.previous = START_TIME
    now = time.perf_counter()
    r = seconds(now - (since if since is not None else elapsed.previous))
    elapsed.previous = now
    return r


class _TagBuffer(io.StringIO):
    tag_aware = True                                   # keeps the colour codes, so problems can be found

    def isatty(self):
        return False


@contextlib.contextmanager
def captured():
    """Everything this thread prints (stdout and stderr) goes into a buffer (0.24.37) - in the GUI
    only this command's own output (its streams route per thread)."""
    buf = _TagBuffer()
    undo = []
    for name in ("stdout", "stderr"):
        s = getattr(sys, name)
        if hasattr(s, "local"):
            undo.append((s, getattr(s.local, "target", None)))
            s.local.target = buf
        else:
            undo.append((name, s))
            setattr(sys, name, buf)
    try:
        yield buf
    finally:
        for a, b in reversed(undo):
            if isinstance(a, str):
                setattr(sys, a, b)
            else:
                a.local.target = b
