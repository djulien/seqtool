# seqtool-command: score | main | refine | the song's score: its terms and every direction in one file - score | score write | score apply FILE | score note "TEXT"
"""seqtool score [show] | score write [FILE] | score apply FILE [--dry-run] | score note "TEXT" [--commands "..."]

A song's score (0.24.50): everything you said about this song, in one readable place - the
section fixes, colours, feel, your terms (definitions), cues, pins, reactions and seeds - as
the seqtool commands that make them, in order, with the directions you gave as notes. It is a
batch file: edit it, and 'score apply' makes the song so again; it is also the song's record
(kept beside the exported .xsq, written each time you export).

    score                        show it
    score write                  write it: <song>-seqtool/<song>.score.txt (or FILE)
    score apply Song.score.txt   make the song what the file says: this song's settings are
                                 replaced by it (one undo step - 'undo' takes it back); a line
                                 that fails stops it and nothing is kept
    score apply FILE --dry-run   the commands, changing nothing
    score note "a wind-up twinkle on ALL in the intro" --commands "pin \\"1. ALL\\" @#1 twinkle"
                                 keep a direction you gave and what it became (the
                                 seqtool-direction skill does this for each one)

Kept for the whole show, not in a song's score (listed as notes): definitions with --show,
reactions and faces set as preferences, name rules. The lyrics and borrowed effects stay with
the song as they are ('lyrics', 'borrow' change them).
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from pathlib import Path

from ..common import songs
from ..common.log import good, info


def q(text) -> str:
    """A word for a command line - quoted only when it must be."""
    s = str(text)
    return s if s and all(c.isalnum() or c in "-_.,:@/=%+" for c in s) and not s.startswith("#") else shlex.quote(s)


def _at(t) -> str:
    return f"@{float(t):g}"


def _val(v) -> str:
    if isinstance(v, dict) and "ramp" in v:
        return "..".join(f"{x:g}" for x in v["ramp"])
    if isinstance(v, dict) and "curve" in v:
        return "..".join(f"{y:g}" for _, y in v["curve"])
    if isinstance(v, list):
        return ",".join(f"{x:g}" if isinstance(x, (int, float)) else str(x) for x in v)
    if isinstance(v, float):
        return f"{v:g}"
    return str(v).replace("_", "-") if v in ("per_model",) else str(v)


def _color_word(hexs: list[str]) -> str:
    from .palette_cmd import COLOR_NAMES
    back = {}
    for k, v in COLOR_NAMES.items():
        back.setdefault(v.upper(), k)
    return ",".join(back.get(h.upper(), h) for h in hexs)


def _sec_label(profile, t) -> str:
    if not profile:
        return ""
    s = next((x for x in profile["sections"] if x["start"] <= float(t) < x["end"]), profile["sections"][-1])
    return f"#{s['index']} {s.get('type', '')}".strip()


def build(sha: str, profile: dict | None, name: str = "") -> list[str]:
    """The score: comment lines ('# ...') and command lines."""
    from seqtool import __version__
    rec = songs.get(sha)
    L = [f"# seqtool score: {name or rec.get('name') or sha[:12]}   (seqtool {__version__}, {time.strftime('%Y-%m-%d %H:%M')})",
         "# Everything said about this song, as the commands that make it. 'score apply FILE' makes the",
         "# song so again (its settings replaced by these); edit freely - one command per line.", ""]

    def head(t):
        L.extend(["", f"# == {t} =="])
    sec = rec.get("sections") or {}
    if sec.get("boundaries"):
        types = sec.get("types") or {}
        head("sections (your fixes: where each starts; =TYPE: its type)")
        L.append("sections set " + " ".join(_at(b) + (f"={types[f'{b:.2f}']}" if f"{b:.2f}" in types else "")
                                            for b in sorted(sec["boundaries"])))
    pal, feel = rec.get("palette"), rec.get("feel") or {}
    if pal or feel:
        head("colours and feel")
    if pal:
        if pal.get("colors"):
            L.append("palette colors " + _color_word(pal["colors"]) + (f" --accent {_color_word(pal['accent'])}"
                                                                      if pal.get("accent") else "")
                     + (f" --hue {pal['hue']:g}" if pal.get("hue") else ""))
        elif pal.get("style"):
            L.append(f"palette {pal['style']}" + (f" {pal['pick'] + 1}" if pal.get("pick") is not None else "")
                     + (f" --hue {pal['hue']:g}" if pal.get("hue") else ""))
        elif pal.get("hue"):
            L.append(f"palette auto --hue {pal['hue']:g}")
    for k, v in feel.items():
        if k != "sections" and isinstance(v, (int, float)):
            L.append(f"feel {k} {v:g}")
    for s in feel.get("sections") or []:
        L.append(f"feel {s['name']} {s['value']:g} {_at(s['at'])}" + ("" if s.get("repeats", True) else " --only")
                 + (f"   # {_sec_label(profile, s['at'])}" if profile else ""))
    defs = rec.get("definitions") or []
    if defs:
        head("your terms (definitions) for this song")
        for d in defs:
            parts = ["define set", q(d["name"])]
            if d.get("level") == "section":
                parts.append(_at(d["at"]))
                if not d.get("repeats", True):
                    parts.append("--only")
            if d.get("for"):
                parts += ["--for", q(d["for"])]
            if d.get("data") is not None:
                parts += ["--data", shlex.quote(json.dumps(d["data"], ensure_ascii=False))]
            parts.append(q(d.get("text") or d["name"]))
            L.append(" ".join(parts))
    from ..common import definitions as DF
    show = DF.show_entries()
    if show:
        L.append("# for the whole show (not replayed here; 'define get NAME' shows them): "
                 + ", ".join(sorted({f"'{e['name']}'" for e in show})))
    cues = rec.get("cues") or []
    if cues:
        head("cues")
        groups: dict = {}
        for c in sorted(cues, key=lambda c: float(c["t"])):
            groups.setdefault((c.get("tag"), tuple(c.get("for") or ()), c.get("len")), []).append(c)
        for (tag, who, ln), cs in groups.items():
            for i in range(0, len(cs), 12):
                L.append("cue add " + " ".join(_at(c["t"]) for c in cs[i:i + 12])
                         + (f" --tag {tag}" if tag else "") + (f" --for {q(','.join(who))}" if who else "")
                         + (f" --len {ln:g}" if ln else ""))
    pins = rec.get("pins") or []
    if pins:
        head("pins (an effect forced somewhere; @TIME = the section playing then)")
        for p in pins:
            tgt = p["target"] + ("" if p.get("pass", "main") == "main" else
                                 f" ({'placed' if p['pass'] == 'place' else p['pass']})")
            parts = ["pin", q(tgt)]
            if p.get("at") is not None:
                parts.append(_at(p["at"]))
            parts.append(p["effect"])
            for k, v in (p.get("params") or {}).items():
                parts.append(q(f"{k}={_val(v)}"))
            if not p.get("repeats", True):
                parts.append("--only")
            if p.get("how"):
                parts += ["--how", q(p["how"])]
            L.append(" ".join(parts) + (f"   # {_sec_label(profile, p['at'])}" if profile and p.get("at") is not None else ""))
    reacts = rec.get("react") or []
    if reacts:
        head("reactions (this song)")
        for e in reacts:
            parts = ["react", q(e["target"]), q(e.get("preset", "off"))]
            parts.append(_at(e["at"]) if e.get("at") is not None else "--song")
            if e.get("over"):
                parts.append("--over")
            if e.get("at") is not None and not e.get("repeats", True):
                parts.append("--only")
            L.append(" ".join(parts))
    seeds = (rec.get("seed"), rec.get("seed_overrides") or {})
    if seeds[0] is not None or seeds[1]:
        head("seeds (seqtool's random choices, kept)")
        if seeds[0] is not None:
            L.append(f"reroll --seed {seeds[0]}")
        ids = {s["id"]: s for s in (profile or {}).get("sections", [])}
        for key, n in sorted(seeds[1].items()):
            tgt, _, sid = key.partition("@")
            where = _at(ids[sid]["start"] + 0.01) if sid in ids else ""
            if sid and not where:
                continue
            L.append(" ".join(x for x in ["reroll", q(tgt) if tgt else "", where, f"--seed {n}"] if x))
    dirs = rec.get("directions") or []
    if dirs:
        head("the directions you gave (and what they became)")
        for d in dirs:
            L.append(f"score note {q(d['text'])}" + (f" --commands {shlex.quote(d['commands'])}" if d.get("commands") else ""))
    mp = {}
    try:
        from ..common import config
        mp = config.load("models").get("targets", {})
    except Exception:  # noqa: BLE001
        pass
    show_rx = sorted(k for k, v in mp.items() if v.get("react") or v.get("face"))
    if show_rx:
        L.append("")
        L.append("# set for the whole show (preferences, not replayed here): reactions / faces on "
                 + ", ".join(show_rx[:12]) + (" ..." if len(show_rx) > 12 else ""))
    return L


def path_for(sha: str) -> Path:
    from ..common import config
    lm = config.answer("last_matchup")
    rec = songs.get(sha)
    stem = Path(rec.get("name") or "song").stem
    folder = Path(lm).parent if lm else Path.cwd()
    return folder / f"{stem}.score.txt"


def write(sha: str, profile, out: Path | None = None) -> Path:
    f = out or path_for(sha)
    f.write_text("\n".join(build(sha, profile)) + "\n", encoding="utf-8")
    return f


def _ctx():
    from .reroll import _context
    _, m, profile, sha = _context()
    if not sha:
        raise SystemExit("score: no current song - 'run --audio SONG' first")
    return m, profile, sha


CLEAR = ("pins", "react", "cues", "palette", "feel", "definitions", "sections", "seed_overrides", "directions")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool score", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", nargs="?", default="show", choices=("show", "write", "apply", "note"))
    ap.add_argument("words", nargs="*")
    ap.add_argument("--dry-run", action="store_true", help="apply: list the commands, change nothing")
    ap.add_argument("--commands", default=None, help="note: what the direction became (commands, ';' between)")
    a = ap.parse_args(argv)
    m, profile, sha = _ctx()
    if a.action == "show":
        for ln in build(sha, profile):
            print(("{note}" + ln + "{/}") if ln.startswith("#") else ln)
        return 0
    if a.action == "write":
        f = write(sha, profile, Path(a.words[0]).expanduser() if a.words else None)
        good(f"wrote the score: {f}  ('score apply' it to make the song so again)")
        return 0
    if a.action == "note":
        if not a.words:
            raise SystemExit('score note "TEXT" [--commands "..."] - e.g. score note "calmer intro" --commands "feel intensity low @#1"')
        ds = list(songs.get(sha).get("directions") or [])
        text = " ".join(a.words)
        ds = [d for d in ds if d["text"] != text] + [{"text": text, **({"commands": a.commands} if a.commands else {}),
                                                       "when": time.strftime("%Y-%m-%d")}]
        songs.update(sha, directions=ds)
        good(f"noted: {text}")
        return 0
    if not a.words:
        raise SystemExit("score apply FILE - e.g. score apply 'My Song.score.txt'")
    f = Path(" ".join(a.words)).expanduser()
    if not f.is_file():
        raise SystemExit(f"score apply: no file {f} - 'score write' makes one")
    from . import batch_cmd
    if a.dry_run:
        return batch_cmd.main([str(f), "--dry-run"])
    from ..common import undo
    before = undo.snapshot()
    songs.update(sha, **{k: None for k in CLEAR})
    info(f"this song's settings are replaced by {f.name} ...")
    rc = batch_cmd.main([str(f)])
    if rc:
        undo._apply(before)
        from .reroll import rerun
        try:
            rerun()
        except SystemExit:
            pass
        info("the song's settings are as they were before 'score apply'")
        return rc
    good(f"the song is as {f.name} says")
    return 0


if __name__ == "__main__":
    sys.exit(main())
