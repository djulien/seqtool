"""Inline colour codes for console text.

Write the codes straight into strings; whatever finally shows the text renders them:

    print(f"{{ok}}wrote {path}{{/}}  ({{note}}3 notes{{/}})")

    {err}   red      errors
    {warn}  yellow   warnings, stale files
    {ok}    green    successful outcomes
    {do}    pink     something for the user to do: a command to type, a step
    {note}  blue     background / debug information
    {head}  teal     headings, summaries, high-level results
    {b}     bold
    {copy}  text to copy (e.g. a line to paste into a file): the GUI shows it in a box
            with a Copy button; the terminal shows it as it is
    {/}     back to the colour before (codes nest)

Colour names work too: {red} {yellow} {green} {pink} {blue} {teal}; and any colour as
{#RRGGBB} (0.24.25: palette swatches).

The terminal gets ANSI colours (unless NO_COLOR is set or output is not a
terminal - then the codes are removed); the GUI turns them into coloured
spans; files written to disk get plain text (plain()).
"""
from __future__ import annotations

import io
import os
import re

ROLE = {"err": "red", "warn": "yellow", "ok": "green", "do": "pink", "note": "blue", "head": "teal", "b": "bold",
        "copy": "plain"}
ANSI = {"red": "\x1b[91m", "yellow": "\x1b[93m", "green": "\x1b[92m", "pink": "\x1b[95m", "blue": "\x1b[94m",
        "teal": "\x1b[96m", "bold": "\x1b[1m", "plain": ""}
RESET = "\x1b[0m"
NAMES = tuple(ROLE) + tuple(ANSI)
TAG = re.compile(r"\{(" + "|".join(sorted(NAMES, key=len, reverse=True)) + r"|#[0-9A-Fa-f]{6}|/)\}")


COMMANDS: set[str] = set()          # command names, set at start-up (set_commands)
_CMD_RE = None


def set_commands(names) -> None:
    """Example commands quoted in any message ('sections merge 3 4', 'seqtool run ...')
    and '$ seqtool ...' lines are highlighted as things to type."""
    global _CMD_RE
    COMMANDS.update(names)
    alts = "|".join(sorted((re.escape(n) for n in COMMANDS), key=len, reverse=True))
    _CMD_RE = re.compile(r"'((?:seqtool |\./seqtool\.py )?(?:" + alts + r")(?:\s[^'\n]*)?)'")


def mark_commands(text: str) -> str:
    if _CMD_RE is None or "'" not in text and "$ " not in text:
        return text
    text = _CMD_RE.sub(lambda m: "'{do}" + m.group(1) + "{/}'", text)
    return re.sub(r"(?m)^(\s*)(\$ seqtool [^\n{]*)$", r"\1{do}\2{/}", text)


def plain(text: str) -> str:
    """The text without colour codes."""
    return TAG.sub("", text)


def _code(c: str) -> str:
    if c.startswith("#"):
        return "\x1b[38;2;{};{};{}m".format(*(int(c[i:i + 2], 16) for i in (1, 3, 5)))
    return ANSI[c]


def ansi(text: str) -> str:
    stack: list[str] = []

    def sub(m):
        name = m.group(1)
        if name == "/":
            if stack:
                stack.pop()
            return RESET + "".join(_code(c) for c in stack)
        c = ROLE.get(name, name)
        stack.append(c)
        return _code(c)
    out = TAG.sub(sub, text)
    return out + (RESET if stack else "")


def use_color(stream) -> bool:
    return "NO_COLOR" not in os.environ and hasattr(stream, "isatty") and stream.isatty()


class ColorStream(io.TextIOBase):
    """Wraps sys.stdout / sys.stderr: renders colour codes as ANSI on a terminal,
    removes them otherwise."""
    tag_aware = True

    def __init__(self, real):
        self.real = real

    def write(self, s):
        if os.environ.get("SEQTOOL_TAGS") == "1":   # 0.24.39: a child of the GUI - its codes go as they are
            self.real.write(s)
            return len(s)
        self.real.write(ansi(mark_commands(s)) if use_color(self.real) else plain(s))
        return len(s)

    def flush(self):
        try:
            self.real.flush()
        except Exception:  # noqa: BLE001
            pass

    def isatty(self):
        return self.real.isatty()

    def fileno(self):
        return self.real.fileno()

    @property
    def encoding(self):
        return getattr(self.real, "encoding", "utf-8")

    @property
    def errors(self):
        return getattr(self.real, "errors", "strict")

    @property
    def buffer(self):
        return self.real.buffer

    @property
    def line_buffering(self):
        return getattr(self.real, "line_buffering", True)


def install() -> None:
    import sys
    if not getattr(sys.stdout, "tag_aware", False):
        sys.stdout = ColorStream(sys.stdout)
    if not getattr(sys.stderr, "tag_aware", False):
        sys.stderr = ColorStream(sys.stderr)


def for_stream(text: str, stream) -> str:
    """Keep the codes for streams that render them, plain text for anything else."""
    return text if getattr(stream, "tag_aware", False) else plain(text)
