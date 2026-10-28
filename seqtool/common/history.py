"""The commands you typed, at the prompt and in the GUI console alike (0.19.6), kept in
seqtool-prefs/history.txt (one per line, the newest last, up to 1000; each session starts
with a '# session started ...' line - 0.21.3):

    history          the last 25, numbered     history 100    the last 100
    history TEXT     the ones containing TEXT  history -c     forget them all
    !!               the last command again    !42            command 42 again
    !lyr             the last one starting with 'lyr'
"""
from __future__ import annotations

from pathlib import Path

KEEP = 1000
_LINES: list[str] | None = None
_STARTED = False


def _file() -> Path:
    from . import config
    f = config.user_dir() / "history.txt"
    old = f.with_name("history")                     # before 0.21.3: no extension
    if old.is_file() and not f.exists():
        try:
            old.rename(f)
        except OSError:
            return old
    return f


def _raw() -> list[str]:
    try:
        return _file().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def lines() -> list[str]:
    global _LINES
    if _LINES is None:
        _LINES = [x for x in _raw() if x.strip() and not x.startswith(("_HiStOrY_V2_", "#"))][-KEEP:]   # libedit's
    return _LINES                                                                                       # header, comments


def session_start(where: str = "prompt") -> None:
    """A '# session started ...' line, so the file shows where each session began."""
    import time
    global _STARTED
    if _STARTED:                                      # the GUI opened from the prompt: the same session
        return
    _STARTED = True
    try:
        f = _file()
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a", encoding="utf-8") as fh:
            fh.write(f"# session started {time.strftime('%Y-%m-%d %H:%M:%S')} ({where})\n")
    except OSError:
        pass


def add(line: str) -> None:
    """Remember a command (not a repeat of the one before it, not 'history' itself)."""
    line = line.strip()
    h = lines()
    if not line or (h and h[-1] == line):
        return
    h.append(line)
    try:
        f = _file()
        f.parent.mkdir(parents=True, exist_ok=True)
        if len(h) > KEEP:
            del h[:-KEEP]
            raw = _raw() + [line]                   # keep the session lines of the commands kept
            cmds = [i for i, x in enumerate(raw) if x.strip() and not x.startswith(("#", "_HiStOrY_V2_"))]
            start = cmds[-KEEP] if len(cmds) >= KEEP else 0
            while start > 0 and raw[start - 1].startswith("#"):
                start -= 1
            f.write_text("\n".join(raw[start:]) + "\n", encoding="utf-8")
        else:
            with f.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except OSError:
        pass


def expand(line: str) -> str | None:
    """'!!', '!N', '!-N' and '!TEXT' as the command they name (None: no such command)."""
    s = line.strip()
    if not s.startswith("!") or len(s) < 2:
        return line
    h = lines()
    head, _, rest = s[1:].partition(" ")
    got = None
    if head == "!":
        got = h[-1] if h else None
    elif head.lstrip("-").isdigit():
        n = int(head)
        idx = n - 1 if n > 0 else len(h) + n
        got = h[idx] if 0 <= idx < len(h) else None
    else:
        got = next((x for x in reversed(h) if x.startswith(head)), None)
    if got is None:
        return None
    return got + (" " + rest if rest else "")


def main(argv=None) -> int:
    from .log import good
    args = list(argv or [])
    h = lines()
    if args and args[0] in ("-c", "--clear"):
        h.clear()
        try:
            _file().write_text("", encoding="utf-8")
        except OSError:
            pass
        good("history cleared")
        return 0
    n, find = 25, None
    if args and args[0].isdigit():
        n = int(args[0])
    elif args:
        find = " ".join(args).lower()
    rows = [(i + 1, x) for i, x in enumerate(h) if find is None or find in x.lower()]
    if not rows:
        print("no commands yet" if find is None else f"no command contains '{find}' - 'history' lists the last ones")
        return 0
    w = len(str(rows[-1][0]))
    for i, x in rows[-n:] if find is None else rows:
        print(f"  {{note}}{i:>{w}}{{/}}  {x}")
    print("{note}'!N' runs command N again, '!!' the last one, '!TEXT' the last one starting with TEXT; "
          "'history TEXT' finds, 'history -c' forgets them{/}")
    return 0
