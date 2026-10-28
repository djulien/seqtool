"""--debug for commands whose results can surprise (0.19.5): a plain-text log of what
the command saw and decided, written next to the song's results (or the command's own
output), with the path printed. The user's rule: a command that is unreliable or may
need diagnosing gets --debug, and they all work the same way.

    from ..common.debuglog import DebugLog
    dbg = DebugLog.for_song(audio, "align") if a.debug else None
    if dbg: dbg.head("your words"); dbg.row(...); ...; dbg.save()
"""
from __future__ import annotations

import time
from pathlib import Path

from .color import plain


class DebugLog:
    def __init__(self, path: Path, title: str):
        self.path = Path(path)
        self.lines = [title, time.strftime("written %Y-%m-%d %H:%M"), ""]

    @classmethod
    def for_song(cls, audio: Path, what: str) -> "DebugLog":
        from .paths import seqtool_folder
        d = seqtool_folder(Path(audio))
        d.mkdir(parents=True, exist_ok=True)
        return cls(d / f"{Path(audio).stem}.debug-{what}.txt", f"seqtool {what} --debug: {Path(audio).name}")

    def head(self, text: str) -> None:
        self.lines += ["", text, "-" * min(78, len(text))]

    def line(self, text: str = "") -> None:
        self.lines.append(plain(str(text)))

    def kv(self, **kw) -> None:
        for k, v in kw.items():
            self.lines.append(f"{k.replace('_', ' ')}: {v}")

    def save(self) -> Path:
        from .log import info
        from .paths import show
        self.path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")
        info(f"  {{note}}debug log: {show(self.path)}{{/}}")
        return self.path


def add_arg(ap, what: str) -> None:
    ap.add_argument("--debug", action="store_true", help=f"write a log of {what} (path printed at the end)")
