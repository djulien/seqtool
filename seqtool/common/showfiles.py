"""Files a sequence uses (pictures, GIFs, videos ...) kept inside the xLights show folder (0.24.47).

xLights finds a file by its path, and a show folder that moves (another computer, a backup, a
bundle) keeps only what is inside it. So when a setting names a file outside the show folder -
'pin Matrix @#2 picture file=~/Downloads/pumpkin.gif' - seqtool offers to copy it in (Enter =
yes; with no one to answer, it is copied), and the copy's path is used from then on:

    where:  general.show_files.folder (default "seqtool-files") in the audio file's folder, when
            that is inside the show folder; else in the show folder itself
    when:   as the setting is given (pin), and at 'xlights-export' for any file still outside
            (the pins naming it are changed to the copy too)
    off:    pref general.show_files.copy = false

A file of the same name already there with the same content is reused; a different one gets
the copy a new name (bat-2.gif).
"""
from __future__ import annotations

import filecmp
import shutil
from pathlib import Path

from . import config


def _prefs() -> dict:
    return {"copy": True, "folder": "seqtool-files", **(config.load("general").get("show_files") or {})}


def show_folder() -> Path | None:
    try:
        from ..layout import store
        src = store.source_info()
        return Path(src["path"]).resolve().parent if src else None
    except Exception:  # noqa: BLE001
        return None


def _inside(p: Path, folder: Path) -> bool:
    try:
        p.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def destination(show: Path) -> Path:
    sub = _prefs()["folder"]
    audio = config.answer("last_audio")
    if audio:
        ad = Path(audio).expanduser().resolve().parent
        if _inside(ad, show):
            return ad / sub
    return show / sub


def outside(value: str) -> Path | None:
    """The file `value` names when it exists outside the show folder, else None (a bare name is
    looked for in the show folder, so it is never 'outside')."""
    show = show_folder()
    if show is None or not value:
        return None
    p = Path(str(value)).expanduser()
    if not p.is_absolute():
        if (show / p).exists() or not p.exists():
            return None
        p = p.resolve()
    if not p.is_file() or _inside(p, show):
        return None
    return p


def bring_in(value: str, what: str = "file") -> str:
    """Offer to copy the file `value` names into the show folder; -> the path to use from now on
    (the copy's, or `value` unchanged)."""
    src = outside(value)
    if src is None or not _prefs()["copy"]:
        return value
    show = show_folder()
    dest_dir = destination(show)
    from .log import good, info
    from .paths import show as shown
    from .prompt import ask
    ans = ask(f"{what} {shown(src)} is outside the show folder ({shown(show)}) - xLights loses it when the show "
              f"folder moves. Copy it to {shown(dest_dir)} and use the copy? [Y/n]", "y", show_default=False)
    if ans.strip().lower() in ("n", "no"):
        info(f"  using {shown(src)} where it is ('pref general.show_files.copy = false' stops asking)")
        return value
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    n = 2
    while dest.exists() and not filecmp.cmp(src, dest, shallow=False):
        dest = dest_dir / f"{src.stem}-{n}{src.suffix}"
        n += 1
    if not dest.exists():
        shutil.copy2(src, dest)
        good(f"  copied to {shown(dest)}")
    else:
        info(f"  already there: {shown(dest)}")
    return str(dest)


def file_settings(effect: str) -> list[str]:
    """The settings of an effect that name a file (effects.json 'file': true)."""
    try:
        effects = config.load("effects")["effects"]
    except Exception:  # noqa: BLE001
        return []
    return [k for k, s in (effects.get(effect, {}).get("parameters") or {}).items() if s.get("file")]


def repin(old: str, new: str) -> int:
    """Pins of the current song naming `old` as a file now name `new`. -> how many."""
    try:
        from ..matchup.reroll import _context
        from . import songs
        sha = _context()[3]
    except (SystemExit, Exception):  # noqa: BLE001
        return 0
    pins, n = list(songs.get(sha).get("pins", [])), 0
    for p in pins:
        for k in file_settings(p.get("effect", "")):
            if (p.get("params") or {}).get(k) == old:
                p["params"][k] = new
                n += 1
    if n:
        songs.update(sha, pins=pins)
    return n
