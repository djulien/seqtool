# seqtool-command: palette | main | refine | the song's colour palette, from its music style - or yours: palette rock 2 --hue 30
"""seqtool palette [STYLE [N]] [--hue DEG] | palette colors C1,C2,... [--accent C,...] | palette auto

The colour palette comes from the song's music style (the analysis scores each style;
the strongest one with palettes in preferences palettes.json is used, and the seed picks one
of its palettes). For the current song you can choose instead (0.24.25):

    palette                      the styles as the music scored them, and the palette in use
    palette ballad               the ballad palettes for this song (the seed still picks which)
    palette ballad 2             its second palette
    palette --hue 40             the colours turned 40 degrees round the colour wheel (any style)
    palette rock 1 --hue -60     all three
    palette colors green,purple,orange --accent blue
                                 your own colours for this song (0.24.46): names or #RRGGBB; the
                                 accent colours are added for loud parts (default: the preferences'
                                 palettes.high_energy_accent); --hue and 'feel warmth' still apply
    palette auto                 back to the music's choice

The GUI: 2. Song > colour palette ... - a wheel with a wedge per style; a ring of a wedge is
one of its palettes and where you click across the wedge turns the hue (the middle: as it is).
Only the colours change: the effects are still chosen for the music's own style. The palettes
themselves (and new styles) are in preferences: 'pref palettes'. After a change the last 'run'
is repeated (the analysis is reused).
"""
from __future__ import annotations

import argparse
import sys

from ..common import config, songs
from ..common.log import info


def _swatch(cols: list[str]) -> str:
    return " ".join(f"{{{c}}}██{{/}} {c}" for c in cols)


COLOR_NAMES = {"red": "#FF0000", "green": "#00C000", "lime": "#00FF00", "blue": "#0000FF", "navy": "#000080",
               "yellow": "#FFE000", "orange": "#FF8000", "purple": "#8000C0", "violet": "#A040FF", "magenta": "#FF00FF",
               "pink": "#FF60B0", "cyan": "#00FFFF", "teal": "#00A0A0", "white": "#FFFFFF", "warmwhite": "#FFD8A0",
               "gold": "#FFB000", "amber": "#FFA000", "brown": "#8B4513", "black": "#000000", "gray": "#808080",
               "grey": "#808080"}


def parse_colors(text: str) -> list[str]:
    """'green,purple,#FF8000' -> ['#00C000', '#8000C0', '#FF8000']"""
    out = []
    for w in [x.strip() for x in str(text).replace(" ", ",").split(",") if x.strip()]:
        c = COLOR_NAMES.get(w.lower().replace("-", "").replace("_", ""))
        if c is None:
            m = __import__("re").fullmatch(r"#?([0-9A-Fa-f]{6})", w)
            if not m:
                raise SystemExit(f"palette colors: '{w}' is no colour - a name ({', '.join(list(COLOR_NAMES)[:8])} ...) "
                                 "or #RRGGBB, e.g. 'palette colors green,purple,#FF8000'")
            c = "#" + m.group(1).upper()
        out.append(c)
    return out


def _describe(ov: dict | None) -> str:
    if not ov:
        return "the music's choice"
    if ov.get("colors"):
        return ", ".join(["your colours " + " ".join(ov["colors"])]
                         + ([f"accent {' '.join(ov['accent'])}"] if ov.get("accent") else [])
                         + ([f"hue {ov['hue']:+.0f} degrees"] if ov.get("hue") else []))
    return ", ".join([ov["style"] if ov.get("style") else "the music's style"]
                     + ([f"palette {ov['pick'] + 1}"] if ov.get("pick") is not None else [])
                     + ([f"hue {ov['hue']:+.0f} degrees"] if ov.get("hue") else []))


def info_for(m: dict | None, profile: dict | None, sha: str | None) -> dict:
    """What the GUI's palette panel shows."""
    lib = config.load("palettes")["styles"]
    styles = ((profile or {}).get("profile") or {}).get("styles", {})
    pal = (m or {}).get("palettes") or {}
    return {"styles": styles, "library": lib, "override": songs.get(sha).get("palette") if sha else None,
            "base": pal.get("base"), "accent": pal.get("accent")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool palette", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("words", nargs="*", help="STYLE [N] | auto")
    ap.add_argument("--hue", type=float, default=None, help="turn every colour this many degrees round the colour wheel")
    ap.add_argument("--accent", default=None, help="with 'colors': the accent colours for loud parts (names or #RRGGBB)")
    a = ap.parse_args(argv)
    from .reroll import _context
    path, m, profile, sha = _context()
    if not sha:
        raise SystemExit("palette: no current song - 'run --audio SONG' first")
    d = info_for(m, profile, sha)
    lib = d["library"]
    if not a.words and a.hue is None:
        ranked = sorted(d["styles"].items(), key=lambda kv: -kv[1])
        print("{head}music styles{/} (as the analysis scored this song): "
              + ", ".join(f"{k} {v:.2f}" for k, v in ranked[:6]))
        if d["base"]:
            print(f"{{head}}palette{{/}}  {_swatch(d['base']['colors'])}")
            print(f"  {d['base'].get('why', '')}")
        if d["override"]:
            print(f"{{note}}yours for this song: {_describe(d['override'])} ('palette auto' undoes it){{/}}")
        print("styles with palettes: " + ", ".join(f"{k} ({len(v)})" for k, v in lib.items())
              + " - e.g. '{do}palette " + next(iter(lib)) + " 1 --hue 30{/}'")
        return 0
    ov = dict(d["override"] or {})
    if a.words and a.words[0].lower() == "auto":
        new = None
        label = "palette: the music's choice again"
    elif a.words and a.words[0].lower() in ("colors", "colours", "color", "colour"):
        if len(a.words) < 2:
            raise SystemExit("palette colors C1,C2,... - e.g. 'palette colors green,purple,orange --accent blue'")
        new = {"colors": parse_colors(",".join(a.words[1:]))}
        if a.accent:
            new["accent"] = parse_colors(a.accent)
        if a.hue is not None and abs(((a.hue + 180) % 360) - 180) >= 0.5:
            new["hue"] = round(((a.hue + 180) % 360) - 180, 1)
        label = "palette for this song: " + _describe(new)
    else:
        if a.words:
            st = next((k for k in lib if k.lower() == a.words[0].lower()), None)
            if st is None:
                raise SystemExit(f"palette: no style '{a.words[0]}' - the styles with palettes: {', '.join(lib)} "
                                 f"(e.g. 'palette {next(iter(lib))}')")
            ov = {"style": st, **({"hue": ov["hue"]} if ov.get("hue") else {})}
            if len(a.words) > 1:
                try:
                    n = int(a.words[1])
                except ValueError:
                    raise SystemExit(f"palette {st} N: N is a number, 1 to {len(lib[st])}") from None
                if not 1 <= n <= len(lib[st]):
                    raise SystemExit(f"palette {st} has {len(lib[st])} palette(s) - e.g. 'palette {st} 1'")
                ov["pick"] = n - 1
        if a.hue is not None:
            h = ((a.hue + 180) % 360) - 180
            if abs(h) < 0.5:
                ov.pop("hue", None)
            else:
                ov["hue"] = round(h, 1)
        new = ov or None
        label = "palette for this song: " + _describe(new)
    songs.update(sha, palette=new)
    from .reroll import deferring, rerun
    if deferring():                                   # 0.24.29: 'batch' plans once, at the end
        rerun()
        from ..common.log import good
        good(label + "  {note}(" + _deferred() + "){/}")
        return 0
    info("re-running the plan (analysis is reused) ...")
    rerun()
    from ..common.log import good
    good(label + " ('undo' takes it back)")
    from ..common.canonical import read_json
    from pathlib import Path
    nm = read_json(Path(config.answer("last_matchup")))
    b = (nm.get("palettes") or {}).get("base")
    if b:
        info(f"  now: {_swatch(b['colors'])}")
    return 0


def _deferred() -> str:
    from .reroll import deferred_note
    return deferred_note()


if __name__ == "__main__":
    sys.exit(main())
