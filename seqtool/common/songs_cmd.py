# seqtool-command: songs | main | refine | the songs seqtool keeps settings for (pins, section edits ...): songs; songs forget SONG|N; songs forget --current
"""seqtool songs | songs forget SONG|N [--yes] | songs forget --current

Per-song settings - pins, promotions, borrowed effects, section edits, seeds, reactions,
lyrics settings - are kept in seqtool-prefs/songs.json, by the audio's content, so they
come back when the song is run again. The current song (what 'status', 'pin', 'explain'
and the GUI work on) is remembered separately. Neither belongs to the baseline: taking a
song out of the baseline keeps both (0.21.3, the user's surprise).

    songs                       the songs with settings kept, and what is kept (* = current)
    songs forget 2              forget song 2's settings (it asks first; --yes doesn't)
    songs forget "My Song"      by (part of) its name
    songs forget --current      no current song any more (its settings stay)

'undo' brings forgotten settings back. Result files (the song's -seqtool folder) are not
touched.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config, songs
from .log import good, info

CURRENT_KEYS = ("last_audio", "last_music", "last_matchup", "last_out", "last_run")
KINDS = {"pins": "pins", "sections": "section edits", "seed": "seed", "seed_overrides": "rerolls",
         "borrowed": "borrowed", "lyrics": "lyrics", "react": "reactions"}


def _current_sha() -> str | None:
    lm = config.answer("last_matchup") or config.answer("last_music")
    try:
        from .canonical import read_json
        return read_json(Path(lm)).get("lineage", {}).get("audio") if lm and Path(lm).exists() else None
    except Exception:  # noqa: BLE001
        return None


def _rows() -> list[tuple[str, dict]]:
    cur, la = _current_sha(), config.answer("last_audio")
    rows = []
    for sha, rec in songs._all().items():
        if not rec.get("name") and sha == cur and la:      # older records have no name: the current song's
            rec = {**rec, "name": Path(la).name}
        rows.append((sha, rec))
    return sorted(rows, key=lambda kv: (kv[1].get("name") or "~").lower())


def _kept(rec: dict) -> str:
    out = []
    for k, word in KINDS.items():
        v = rec.get(k)
        if v:
            out.append(f"{len(v)} {word}" if isinstance(v, (list, dict)) and k in ("pins", "borrowed", "seed_overrides")
                       else word)
    other = [k for k in rec if k not in KINDS and k not in ("name", "seed_history")]
    return ", ".join(out + other) or "nothing"


def forget_current() -> None:
    for k in CURRENT_KEYS:
        config.remember(k, None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool songs", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", nargs="?", choices=("list", "forget"), default="list")
    ap.add_argument("song", nargs="*", help="the song's number from 'songs', or (part of) its name")
    ap.add_argument("--current", action="store_true", help="forget: only which song is current")
    ap.add_argument("--yes", action="store_true", help="forget without asking")
    a = ap.parse_args(argv)
    rows = _rows()
    cur = _current_sha()
    if a.action == "list":
        if not rows:
            print("no song settings kept yet")
        for i, (sha, rec) in enumerate(rows, 1):
            print(f"  {i:>2}{'*' if sha == cur else ' '} {rec.get('name') or 'song ' + sha[:8] + ' (name not kept)':<36} {_kept(rec)}")
        la = config.answer("last_audio")
        print("{note}" + (f"current song: {Path(la).name}" if la else "no current song")
              + " - 'songs forget N' forgets a song's settings, 'songs forget --current' the current song{/}")
        return 0
    if a.current:
        forget_current()
        good("no current song now - 'run --audio SONG' (or 'run' in the GUI) picks one; its settings are kept")
        return 0
    if not a.song:
        raise SystemExit("songs forget N | NAME  ('songs' numbers them), or 'songs forget --current'")
    want = " ".join(a.song)
    if want.isdigit() and 1 <= int(want) <= len(rows):
        hit = [rows[int(want) - 1]]
    else:
        hit = [r for r in rows if want.lower() in (r[1].get("name") or "").lower()]
    if len(hit) != 1:
        raise SystemExit(f"songs forget: {'no song' if not hit else str(len(hit)) + ' songs'} match '{want}' - "
                         "'songs' lists them; give its number")
    sha, rec = hit[0]
    name = rec.get("name") or sha[:12]
    if not a.yes:
        from .prompt import ask, interactive
        if interactive() and ask(f"forget {name}'s settings ({_kept(rec)})? [y/N]", "n",
                                 show_default=False).lower() not in ("y", "yes"):
            info("nothing forgotten")
            return 0
    data = songs._all()
    data.pop(sha, None)
    songs._file().write_text(__import__("json").dumps(data, indent=2) + "\n", encoding="utf-8")
    msg = f"forgot {name}'s settings ({_kept(rec)})"
    if sha == cur:
        forget_current()
        msg += "; it is no longer the current song"
    good(msg + " - 'undo' brings them back")
    return 0


if __name__ == "__main__":
    sys.exit(main())
