# seqtool-command: play | play_cmd | look | play the song in the GUI: play | play #3 | play chorus 2 | play @1:05
# seqtool-command: pause | pause_cmd | look | pause the GUI player (play continues)
# seqtool-command: seek | seek_cmd | look | move the play head: seek -5 | seek +5 | seek 0 | seek @1:05 | seek #3
# seqtool-command: volume | volume_cmd | look | GUI player volume: volume 80 | volume +10 | volume -10 | volume
# seqtool-command: speed | speed_cmd | look | GUI playback speed: speed 0.75 | speed 75% | speed 1 | speed
"""Control the GUI's audio player from the command line (the seqtool> prompt or the
GUI console). The player lives in the browser page, so the GUI must be open
('gui', or start with 'seqtool --gui').

    play                 play from the play head
    play #3              play from the start of section 3
    play chorus          from the first chorus;  'play chorus 2' the second one
    play @1:05           from 1:05 (seconds, m:ss)
    pause                pause ('play' continues from there)
    seek -5 / seek +5    back / forward 5 seconds (any number)
    seek 0               to the beginning;  'seek @1:05', 'seek #3' also work
    volume 80            volume in percent;  'volume +10' / 'volume -10';  'volume' shows it
    speed 0.75           playback speed (also '75%');  'speed 1' is normal;  'speed' shows it
"""
from __future__ import annotations

import re
import sys

from ..common.log import good, info


def _server():
    from . import server
    srv = server.running()
    if srv is None:
        raise SystemExit("the player is in the GUI, which isn't open - 'gui' opens it "
                         "(or start seqtool with 'seqtool --gui')")
    if not srv.hub.clients:
        raise SystemExit("no GUI page is connected - 'gui' opens one")
    return srv


def _send(**action) -> None:
    _server().hub.send("player", action)


def _state(wait: float = 0.0) -> dict:
    if wait:                                   # let the page report what the last action did
        import time
        time.sleep(wait)
    return getattr(_server(), "player_state", {}) or {}


def _profile() -> dict | None:
    from ..common import current
    from ..common.canonical import read_json
    s = current.song()
    return read_json(s["profile"]) if s and s.get("profile") else None


def _clock(t: float) -> str:
    t = round(t, 1)
    return f"{int(t // 60)}:{t % 60:04.1f}"


def where(words: list[str]) -> tuple[float, str]:
    """'#3' | '3' | 'chorus' | 'chorus 2' | '@1:05' -> (seconds, description)."""
    text = " ".join(words).strip()
    if text.startswith("@") and not text.startswith("@#"):
        from ..matchup.explain import parse_time
        t = parse_time(text, None)
        return t, _clock(t)
    prof = _profile()
    if prof is None:
        raise SystemExit("no sections yet - 'run' the song first, or give a time: 'play @1:05'")
    secs = prof["sections"]
    m = re.fullmatch(r"@?#?(\d+)", text)
    if m:
        n = int(m.group(1))
        if not 1 <= n <= len(secs):
            raise SystemExit(f"no section #{n} (1-{len(secs)}; 'sections' lists them)")
        s = secs[n - 1]
    else:
        m = re.fullmatch(r"([a-z_\- ]+?)\s*(\d+)?", text.lower())
        name, k = (m.group(1).strip(), int(m.group(2) or 1)) if m else (text.lower(), 1)
        hits = [s for s in secs if s.get("type", "").lower() == name]
        if not hits:
            types = ", ".join(dict.fromkeys(s.get("type", "?") for s in secs))
            raise SystemExit(f"no '{name}' section - this song has: {types} (e.g. 'play {secs[-1].get('type')}')")
        if k > len(hits):
            raise SystemExit(f"only {len(hits)} '{name}' section(s) - e.g. 'play {name} {len(hits)}'")
        s = hits[k - 1]
    return s["start"], f"#{s['index']} {s.get('type', '?')} ({_clock(s['start'])})"


def play_cmd(argv=None) -> int:
    argv = list(argv or [])
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv:
        t, what = where(argv)
        _send(cmd="play", at=t)
        good(f"playing from {what}")
    else:
        _send(cmd="play")
        st = _state()
        good("playing" + (f" from {_clock(st['t'])}" if "t" in st else " from the play head"))
    return 0


def pause_cmd(argv=None) -> int:
    _send(cmd="pause")
    st = _state(0.4)
    good("paused" + (f" at {_clock(st['t'])}" if "t" in st else "") + " - 'play' continues")
    return 0


def seek_cmd(argv=None) -> int:
    argv = list(argv or [])
    if not argv or argv[0] in ("-h", "--help"):
        print("seek -5 | seek +5 | seek 0 | seek @1:05 | seek #3   (move the play head)")
        return 0
    a = argv[0]
    if re.fullmatch(r"[+-]\d+(\.\d+)?", a):
        _send(cmd="seek", by=float(a))
        good(f"{'forward' if float(a) > 0 else 'back'} {abs(float(a)):g} s")
    elif re.fullmatch(r"\d+(\.\d+)?", a):
        _send(cmd="seek", at=float(a))
        good(f"play head at {_clock(float(a))}")
    else:
        t, what = where(argv)
        _send(cmd="seek", at=t)
        good(f"play head at {what}")
    return 0


def volume_cmd(argv=None) -> int:
    argv = list(argv or [])
    if not argv:
        st = _state()
        info(f"volume {round(100 * st.get('volume', 1.0))}%  (e.g. 'volume 80', 'volume -10')")
        return 0
    m = re.fullmatch(r"([+-]?)(\d+)%?", argv[0])
    if not m:
        raise SystemExit("volume 0-100, or +N / -N - e.g. 'volume 80', 'volume -10'")
    v = int(m.group(2))
    if m.group(1):
        _send(cmd="volume", by=(v if m.group(1) == "+" else -v) / 100)
        good(f"volume {m.group(1)}{v}%")
    else:
        _send(cmd="volume", to=max(0, min(100, v)) / 100)
        good(f"volume {max(0, min(100, v))}%")
    return 0


def speed_cmd(argv=None) -> int:
    argv = list(argv or [])
    if not argv:
        st = _state()
        info(f"speed {st.get('rate', 1.0):g}x  (e.g. 'speed 0.75', 'speed 1')")
        return 0
    a = argv[0]
    try:
        r = float(a[:-1]) / 100 if a.endswith("%") else float(a.rstrip("x"))
    except ValueError:
        raise SystemExit("speed 0.25-4 (or a percentage) - e.g. 'speed 0.75', 'speed 75%', 'speed 1'")
    r = max(0.25, min(4.0, r))
    _send(cmd="speed", to=r)
    good(f"speed {r:g}x" + ("" if r == 1 else " ('speed 1' is normal)"))
    return 0


if __name__ == "__main__":
    sys.exit(play_cmd(sys.argv[1:]))
