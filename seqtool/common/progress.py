"""Progress for anything that takes more than a few seconds (0.19.8 rule, DESIGN §2):

    p = Progress(total, "trying settings")     # total: how many steps (or seconds of audio)
    for ...: p.step()                          # or p.at(done)
    p.done("tried 96 combinations")

On a terminal and in the GUI console one line is rewritten in place (log.progress, the
0.24.32 rule); elsewhere (a log, a pipe) a line is printed every 10%. Nothing is shown for work that finishes within `quiet` seconds.
"""
from __future__ import annotations

import sys
import time

from .log import info, progress, progress_end, rewrites


def _dur(sec: float) -> str:
    return f"{sec:.0f} s" if sec < 90 else f"{sec / 60:.1f} min"


class Progress:
    def __init__(self, total: float, label: str, quiet: float = 1.5):
        self.total, self.label, self.quiet = float(total or 0), label, quiet
        self.t0, self.n, self.shown, self.any = time.monotonic(), 0.0, -10, False
        self.tty = rewrites(sys.stderr)

    def step(self, k: float = 1.0) -> None:
        self.at(self.n + k)

    def at(self, done: float) -> None:
        self.n = done
        el = time.monotonic() - self.t0
        if el < self.quiet:
            return
        p = int(100 * min(1.0, done / self.total)) if self.total else 0
        if not self.tty and p < self.shown + 10:
            return
        if self.tty and p == self.shown and el - getattr(self, "_last", 0) < 1:
            return
        self.shown, self._last, self.any = p, el, True
        eta = f", about {_dur(el * (100 - p) / p)} to go" if 3 <= p < 100 else ""
        txt = f"  {self.label}: {p:3d}%  ({_dur(el)} so far{eta})"
        progress(txt, level="info")

    def done(self, note: str | None = None) -> None:
        el = time.monotonic() - self.t0
        if self.any or el >= self.quiet:
            txt = f"  {self.label}: 100%  ({_dur(el)})" + (f" - {note}" if note else "")
            progress_end()
            info(txt)
