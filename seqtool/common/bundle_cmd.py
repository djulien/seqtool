# seqtool-command: bundle | main | setup | pack seqtool's working files into one .zip (to upload, share or move): bundle | bundle --open FILE.zip
"""seqtool bundle [--out DIR] [--no-audio] [--all] | bundle --open FILE.zip [--into DIR]

Packs everything seqtool works with for the current song into one .zip (0.24.34) - to upload
it into a Claude session (and run the seqtool-direction skill against your own layout instead
of the demo), to send it to someone, or to move to another computer:

    prefs/   your seqtool-prefs folder: settings, songs.json (pins, reactions, feel ...), the
             stored layout, the undo steps (not its cache, rebuilt when needed)
    show/    xlights_rgbeffects.xml and xlights_networks.xml of the stored layout
    song/    the song and its results folder (not the stems and the GUI's WAV play copy -
             --all takes them too); the .xsq files beside the song
    bundle.json   what came from where

    bundle                          -> seqtool-bundles/SONG-DATE.zip (in the folder you are in)
    bundle --no-audio               without the song itself (a re-plan works; a new analysis doesn't)
    bundle --open SONG-DATE.zip     unpack it into SONG-DATE/ (--into DIR: there) and point its
                                    files at the new places; it says how to work there
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import zipfile
from pathlib import Path

from . import config
from .log import good, info, warn

BIG = 50 * 1024 * 1024


def _norm(p: str) -> str:
    s = str(p).replace("\\", "/").rstrip("/")
    return s.lower() if len(s) > 1 and s[1] == ":" else s


def remap(value, mapping: dict[str, str]):
    """Every string in a JSON value that holds one of the old folders, with the new folder
    (the old ones may be Windows paths: any case, either slash)."""
    if isinstance(value, dict):
        return {k: remap(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [remap(v, mapping) for v in value]
    if not isinstance(value, str) or len(value) < 2:
        return value
    low = value.replace("\\", "/")
    cmp = low.lower()
    for old in sorted(mapping, key=len, reverse=True):
        k = _norm(old)
        kk = k.lower() if len(k) > 1 and k[1] == ":" else k
        i = (cmp if kk != k else low).find(kk)
        if i >= 0:
            end = i + len(kk)
            if end < len(low) and low[end] not in "/\"' ":
                continue                                # '/show2' isn't inside '/show'
            return value[:i] + mapping[old] + low[end:]
    return value


def _files(folder: Path, skip) -> list[Path]:
    out = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not skip(Path(root) / d, True)]
        out += [Path(root) / f for f in files if not skip(Path(root) / f, False)]
    return sorted(out)


def make(out_dir: Path | None, audio: bool = True, everything: bool = False) -> Path:
    from . import current
    from ..layout import store
    prefs = config.user_dir()
    song = current.song()
    src = store.source_info()
    stem = Path(song["audio"]).stem if song else "seqtool"
    out_dir = out_dir or Path.cwd() / "seqtool-bundles"
    out_dir.mkdir(parents=True, exist_ok=True)
    zf = out_dir / f"{stem}-{time.strftime('%Y%m%d-%H%M')}.zip"
    entries: list[tuple[Path, str]] = []
    mapping: dict[str, str] = {str(prefs): "prefs"}
    skipped: list[str] = []

    def pskip(p: Path, is_dir: bool) -> bool:
        return is_dir and (p.name == "cache" or p.name.startswith("layout-forgotten-") or p.name == "__pycache__")
    entries += [(f, "prefs/" + f.relative_to(prefs).as_posix()) for f in _files(prefs, pskip)]
    if src:
        rgb = Path(src["path"])
        mapping[str(rgb.parent)] = "show"
        for name in (rgb.name, "xlights_networks.xml"):
            if (rgb.parent / name).is_file():
                entries.append((rgb.parent / name, f"show/{name}"))
    if song:
        a = Path(song["audio"])
        mapping[str(a.parent)] = "song"
        if audio and a.is_file():
            entries.append((a, f"song/{a.name}"))
        for x in sorted(a.parent.glob("*.xsq")):
            entries.append((x, f"song/{x.name}"))
        res = Path(config.answer("last_out") or song.get("folder") or "")
        if res and res.is_dir():
            try:
                rel = "song/" + res.relative_to(a.parent).as_posix()
            except ValueError:
                rel = "results"
                mapping[str(res)] = "results"

            def rskip(p: Path, is_dir: bool) -> bool:
                if everything:
                    return False
                if is_dir:
                    return p.name in ("stems", "__pycache__")
                if p.name.endswith(".play.wav") or p.stat().st_size > BIG:
                    skipped.append(p.name)
                    return True
                return False
            entries += [(f, rel + "/" + f.relative_to(res).as_posix()) for f in _files(res, rskip)
                        if f != a]
    lr = config.answer("last_run") or {}
    if lr.get("cwd") and not any(_norm(lr["cwd"]).startswith(_norm(k)) for k in mapping):
        mapping[lr["cwd"]] = "song"
    seen, uniq = set(), []
    for f, arc in entries:
        if arc not in seen:
            seen.add(arc)
            uniq.append((f, arc))
    from .progress import Progress
    total = sum(f.stat().st_size for f, _ in uniq)
    p = Progress(total, "packing")
    from seqtool import __version__
    with zipfile.ZipFile(zf, "w", zipfile.ZIP_DEFLATED) as z:
        for f, arc in uniq:
            z.write(f, arc)
            p.step(f.stat().st_size)
        z.writestr("bundle.json", json.dumps({
            "seqtool": __version__, "made": time.strftime("%Y-%m-%d %H:%M"), "map": mapping,
            "audio": f"song/{Path(song['audio']).name}" if song and audio else None,
            "left_out": skipped, "files": len(uniq)}, indent=2) + "\n")
    p.done(f"{len(uniq)} files")
    if skipped:
        info(f"  left out (big, rebuilt when needed): {', '.join(skipped[:6])}" + (" ..." if len(skipped) > 6 else "")
             + " - 'bundle --all' takes them too")
    return zf


def open_bundle(zf: Path, into: Path | None) -> Path:
    if not zipfile.is_zipfile(zf):
        raise SystemExit(f"{zf.name} isn't a .zip - give the file 'bundle' made, e.g. 'bundle --open song-20261026-1205.zip'")
    with zipfile.ZipFile(zf) as z:
        try:
            man = json.loads(z.read("bundle.json"))
        except KeyError:
            raise SystemExit(f"{zf.name} has no bundle.json - not made by 'seqtool bundle'") from None
        dest = (into or Path.cwd() / zf.stem).resolve()
        if dest.exists() and any(dest.iterdir()):
            raise SystemExit(f"{dest} isn't empty - choose another folder, e.g. 'bundle --open {zf.name} --into {zf.stem}-2'")
        for n in z.namelist():
            if n.startswith("/") or ".." in Path(n).parts:
                raise SystemExit(f"{zf.name}: unsafe path {n} - not opened")
        z.extractall(dest)
    mapping = {old: (dest / rel).as_posix() for old, rel in man.get("map", {}).items()}
    changed = 0
    for f in sorted(dest.rglob("*.json")):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        new = remap(doc, mapping)
        if new != doc:
            f.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            changed += 1
    info(f"  {changed} file(s) pointed at the new folders")
    return dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool bundle", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=None, help="the folder for the .zip (default ./seqtool-bundles)")
    ap.add_argument("--no-audio", action="store_true", help="without the song itself")
    ap.add_argument("--all", action="store_true", help="the stems and big files too")
    ap.add_argument("--open", dest="open_", default=None, metavar="FILE.zip", help="unpack a bundle and use it")
    ap.add_argument("--into", default=None, help="with --open: unpack here (an empty or new folder)")
    a = ap.parse_args(argv)
    from .paths import expand
    if a.open_:
        zf = expand(a.open_, "file")
        if not zf.is_file():
            raise SystemExit(f"no such file: {a.open_} - e.g. 'bundle --open seqtool-bundles/song-20261026-1205.zip'")
        dest = open_bundle(zf, Path(a.into).expanduser() if a.into else None)
        good(f"opened into {dest}")
        print("{note}to work there (its settings, layout and song):{/}")
        print(f"  Linux / macOS:  cd {dest / 'song'} && SEQTOOL_PREFS={dest / 'prefs'} seqtool status")
        print(f"  Windows:        cd {dest / 'song'} & set SEQTOOL_PREFS={dest / 'prefs'} & seqtool status")
        return 0
    if config.answer("last_audio") is None:
        warn("no current song - the bundle has your settings and layout only ('run --audio SONG' first for a song)")
    zf = make(Path(a.out).expanduser() if a.out else None, not a.no_audio, a.all)
    mb = zf.stat().st_size / 1e6
    good(f"wrote {zf} ({mb:.1f} MB) - 'bundle --open {zf.name}' unpacks it elsewhere (e.g. in a Claude session)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
