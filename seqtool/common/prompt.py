"""Interactive prompts.

* In the terminal: the question goes on its own line(s) and the input line is
  a short "> ", so line editing (backspace, arrows, history via readline)
  works normally. Prompts always reach the real terminal, even if stdout is
  captured.
* In the browser GUI: a command started from the GUI console runs with a
  per-thread "asker" installed by the GUI server; ask() sends the question to
  the browser and waits for the answer typed there.
* With no terminal and no GUI, the default is returned immediately (never blocks).
* remember_as="key": the previous answer (seqtool-prefs/answers.json) becomes
  the default, and the new answer is saved.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import threading

try:
    import readline  # noqa: F401  (enables editing/history for input())
except ImportError:      # Windows without pyreadline
    pass

_local = threading.local()


class Cancelled(KeyboardInterrupt):
    """Raised inside a command when the user cancels a question in the GUI."""


def set_gui_asker(fn) -> None:
    """Install (or with None, remove) the GUI question handler for this thread."""
    _local.asker = fn


def gui_asker():
    return getattr(_local, "asker", None)


def interactive() -> bool:
    """Can we ask the user something? True on a terminal, or inside a GUI command.
    False when SEQTOOL_NONINTERACTIVE=1 (set by the test runner) or with no terminal."""
    if gui_asker() is not None:                 # a GUI command: the browser answers
        return True
    if os.environ.get("SEQTOOL_NONINTERACTIVE") == "1":
        return False
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def terminal() -> bool:
    """True only for a real terminal (for the few things that read keys directly)."""
    if os.environ.get("SEQTOOL_NONINTERACTIVE") == "1" or gui_asker() is not None:
        return False
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def answer_kind() -> str | None:
    """What the question being asked wants (0.24.3): 'dir' / 'file' - completion offers paths."""
    return getattr(_local, "kind", None) or _KIND[0]


_KIND: list = [None]                          # the terminal's (one prompt at a time)


def ask(question: str, default: str = "", remember_as: str | None = None, show_default: bool = True,
        complete: str | None = None) -> str:
    """complete: 'dir' or 'file' - Tab (terminal) and the GUI console's list offer paths."""
    _local.kind, _KIND[0] = complete, complete
    try:
        return _ask(question, default, remember_as, show_default)
    finally:
        _local.kind, _KIND[0] = None, None


def _ask(question: str, default: str = "", remember_as: str | None = None, show_default: bool = True) -> str:
    from . import config
    if remember_as:
        default = config.answer(remember_as, default)
        if default and remember_as.startswith("arg:") and ("/" in default or "\\" in default) \
                and not any(ch in default for ch in "*?[") and not Path(default).exists():
            from .current import relocate                 # a remembered file that has moved (or is gone)
            found = relocate(default)
            default = str(found) if found else ""
    if not interactive():
        return default
    asker = gui_asker()
    if asker is not None:
        ans = asker(question.strip(), default if show_default else "").strip()
    else:
        term = sys.__stdout__ or sys.stdout
        q = question.rstrip()
        if show_default and default:
            q += f"  [Enter = {default}]"
        from .color import ansi, mark_commands, plain, use_color
        q = mark_commands(q)
        inline = q.endswith(">") and "\n" not in q          # a prompt like 'tutorial>' is the input prompt itself
        q = "{do}" + q + "{/}"
        rendered = ansi(q) if use_color(term) else plain(q)
        if not inline:
            term.write(rendered + "\n")
            term.flush()
        saved = sys.stdout
        sys.stdout = term                      # input() writes its prompt to sys.stdout
        try:
            import re as _re                  # readline must not count colour codes as prompt width
            ans = input(_re.sub(r"(\x1b\[[0-9;]*m)", "\x01\\1\x02", rendered) + " " if inline else "> ").strip()
        except EOFError:
            ans = ""
        finally:
            sys.stdout = saved
    result = ans if ans else default
    if remember_as and ans:
        config.remember(remember_as, result)
    return result
