"""A small line editor for the Windows console (0.24.59).

Windows' Python has no readline, and pyreadline3 can stop seqtool at start on newer
Pythons, so on Windows seqtool reads its prompt lines itself (msvcrt): typing,
Backspace / Delete, Left / Right / Home / End, Up / Down for the history, Esc to
clear the line, and Tab for completion (common/complete.py - the same engine as the
GUI console and readline). Ctrl+C cancels the line, Ctrl+Z on an empty line ends.

read_line() takes the key source as a parameter so it can be tested off Windows.
"""
from __future__ import annotations

import os
import sys

MAX_LIST = 40


def available() -> bool:
    """True on a real Windows console, where read_line() is used instead of input()."""
    if os.name != "nt" or os.environ.get("SEQTOOL_READLINE") == "1":
        return False
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _common(words: list[str]) -> str:
    if not words:
        return ""
    a, b = min(words, key=str.lower), max(words, key=str.lower)
    n = 0
    while n < min(len(a), len(b)) and a[n].lower() == b[n].lower():
        n += 1
    return words[0][:n]


def read_line(prompt: str, complete=None, history: list[str] | None = None,
              getch=None, out=None) -> str:
    """One line from the console. complete(text_before_cursor) -> {"start", "items": [{"text", "hint",
    "space"}]}. getch() -> one character (msvcrt.getwch on Windows)."""
    if getch is None:
        import msvcrt
        getch = msvcrt.getwch
    out = out or sys.__stdout__ or sys.stdout
    hist = list(history or [])
    hi = len(hist)
    buf, pos, drawn = "", 0, 0
    keep = ""                                     # the line being typed while Up / Down browse

    def draw():
        nonlocal drawn
        out.write("\r" + prompt + buf + " " * max(0, drawn - len(buf)) + "\r" + prompt + buf[:pos])
        out.flush()
        drawn = len(buf)

    out.write(prompt)
    out.flush()
    while True:
        ch = getch()
        if ch in ("\r", "\n"):
            out.write("\r\n")
            out.flush()
            return buf
        if ch == "\x03":
            out.write("^C\r\n")
            out.flush()
            raise KeyboardInterrupt
        if ch in ("\x1a", "\x04") and not buf:
            raise EOFError
        if ch in ("\x00", "\xe0"):                # arrows and the other special keys
            k = getch()
            if k == "K":
                pos = max(0, pos - 1)
            elif k == "M":
                pos = min(len(buf), pos + 1)
            elif k == "G":
                pos = 0
            elif k == "O":
                pos = len(buf)
            elif k == "S":
                buf = buf[:pos] + buf[pos + 1:]
            elif k in ("H", "P") and hist:
                if hi == len(hist):
                    keep = buf
                hi = max(0, hi - 1) if k == "H" else min(len(hist), hi + 1)
                buf = hist[hi] if hi < len(hist) else keep
                pos = len(buf)
            draw()
            continue
        if ch == "\x08":
            if pos:
                buf, pos = buf[:pos - 1] + buf[pos:], pos - 1
            draw()
            continue
        if ch == "\x1b":
            buf, pos = "", 0
            draw()
            continue
        if ch == "\t":
            if complete is None:
                continue
            try:
                res = complete(buf[:pos])
            except Exception:  # noqa: BLE001 - never break the prompt
                continue
            items = res.get("items") or []
            start = min(int(res.get("start", pos)), pos)
            if len(items) == 1:
                it = items[0]
                ins = it["text"] + (" " if it.get("space", True) else "")
                buf, pos = buf[:start] + ins + buf[pos:], start + len(ins)
            elif items:
                pre = _common([x["text"] for x in items])
                if len(pre) > pos - start:
                    buf, pos = buf[:start] + pre + buf[pos:], start + len(pre)
                else:
                    out.write("\r\n")
                    w = max(len(x["text"]) for x in items[:MAX_LIST])
                    for x in items[:MAX_LIST]:
                        h = (x.get("hint") or "")[:60]
                        out.write(f"  {x['text']:<{w}}  {h}".rstrip() + "\r\n")
                    if len(items) > MAX_LIST:
                        out.write(f"  ... {len(items) - MAX_LIST} more\r\n")
                    out.write(prompt)
                    drawn = 0
            draw()
            continue
        if ch < " ":
            continue
        buf, pos = buf[:pos] + ch + buf[pos:], pos + 1
        if pos == len(buf):
            out.write(ch)                         # the usual case: no redraw needed
            out.flush()
            drawn = len(buf)
        else:
            draw()
