# seqtool-command: update | main | setup | is there a newer seqtool? update (check now, offer to get it) | update --check
"""seqtool update [--check] [--yes]

Newer seqtool versions are published at the project's GitHub page (REPO_URL below). When
seqtool starts (the seqtool> prompt, the GUI, 'start') it looks there - at most once a day, and
only while 'general.check_updates' is on (the default) - and if there is a newer version:

    on a terminal    asks whether to get it; then says what to do to use it, and offers to
                     restart seqtool with it
    elsewhere        says so in one line ('update' gets it)

How it is got: a .pyz of the release when there is one - run once, it upgrades your seqtool
folder where it is (files you changed are kept and asked about, as a .pyz always does); else
the release (or the main branch) as a .zip, unpacked into a folder of its own beside your
seqtool folder - seqtool-X.Y.Z - which you use from then on (your preferences, songs and
results stay where they are: they are not in the seqtool folder).

    update                 check now and offer to get it
    update --check         only say whether there is a newer version
    pref general.check_updates = false     don't look when seqtool starts
    SEQTOOL_CHECK_UPDATES=0                the same, for one shell (tests, scripts)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path

from . import config
from .log import good, info, warn

REPO = "djulien/seqtool"
REPO_URL = f"https://github.com/{REPO}"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RAW_VERSION = "https://raw.githubusercontent.com/" + REPO + "/{branch}/VERSION"
BRANCH_ZIP = REPO_URL + "/archive/refs/heads/{branch}.zip"
BRANCHES = ("main", "master")
TIMEOUT = 4.0
_DONE = [False]


def vkey(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:4])


def enabled() -> bool:
    env = os.environ.get("SEQTOOL_CHECK_UPDATES")
    if env is not None:
        return env.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(config.load("general").get("check_updates", True))


def _get(url: str, binary: bool = False):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "seqtool-update", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT if not binary else 120) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", errors="replace")


def latest() -> dict | None:
    """{"version", "pyz" (url or None), "zip" (url), "page"} of the newest published version, or None
    when it can't be found (no network, no releases and no VERSION file)."""
    try:
        rel = json.loads(_get(API_LATEST))
        ver = str(rel.get("tag_name") or rel.get("name") or "").lstrip("vV")
        if vkey(ver):
            assets = rel.get("assets") or []
            pyz = next((a["browser_download_url"] for a in assets if str(a.get("name", "")).endswith(".pyz")), None)
            zp = next((a["browser_download_url"] for a in assets if str(a.get("name", "")).endswith(".zip")),
                      rel.get("zipball_url"))
            return {"version": ver, "pyz": pyz, "zip": zp, "page": rel.get("html_url") or REPO_URL}
    except Exception:  # noqa: BLE001 - no releases, no network, rate limit: try the VERSION file
        pass
    for br in BRANCHES:
        try:
            ver = _get(RAW_VERSION.format(branch=br)).strip()
        except Exception:  # noqa: BLE001
            continue
        if vkey(ver):
            return {"version": ver, "pyz": None, "zip": BRANCH_ZIP.format(branch=br), "page": REPO_URL}
    return None


def install_root() -> Path:
    """The folder seqtool runs from (the one holding seqtool.py)."""
    return Path(__file__).resolve().parents[2]


def check(force: bool = False) -> dict | None:
    """The newer version, if there is one (checked at most once a day unless force)."""
    from seqtool import __version__
    last = config.answer("update_check") or {}
    today = time.strftime("%Y-%m-%d")
    if not force and last.get("day") == today:
        got = last.get("latest")
    else:
        got = latest()
        config.remember("update_check", {"day": today, "latest": got})
    if got and vkey(got["version"]) > vkey(__version__):
        return got
    return None


def at_start(where: str = "prompt") -> None:
    """When seqtool starts: look for a newer version (once per run, if enabled)."""
    if _DONE[0] or not enabled():
        return
    _DONE[0] = True
    try:
        new = check()
    except Exception:  # noqa: BLE001 - never in the way of starting
        return
    if not new:
        return
    from seqtool import __version__
    from .prompt import gui_asker, interactive, terminal
    if where == "prompt" and interactive() and terminal() and gui_asker() is None:
        offer(new)
    else:
        info(f"{{note}}seqtool {new['version']} is available (this is {__version__}) - 'update' gets it; "
             f"{new['page']}{{/}}")


def offer(new: dict, yes: bool = False) -> int:
    from seqtool import __version__
    from .prompt import ask
    if not yes and ask(f"seqtool {new['version']} is available (you have {__version__}). Download it now? [Y/n]",
                       "y", show_default=False).strip().lower() in ("n", "no"):
        info(f"  later: 'update' (or {new['page']}); 'pref general.check_updates = false' stops the check")
        return 0
    root = install_root()
    try:
        if new.get("pyz") and (root / ".seqtool-manifest.json").exists():
            return _via_pyz(new, root)
        return _via_zip(new, root)
    except Exception as e:  # noqa: BLE001
        warn(f"couldn't get seqtool {new['version']} ({e}) - download it yourself: {new['page']}")
        return 1


def _download(url: str, dest: Path) -> Path:
    info(f"downloading {url} ...")
    data = _get(url, binary=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def _via_pyz(new: dict, root: Path) -> int:
    """A .pyz upgrades the unpacked folder in place (keeping and asking about files you changed)."""
    import subprocess
    pyz = _download(new["pyz"], root.parent / f"seqtool-{new['version']}.pyz")
    rc = subprocess.call([sys.executable, str(pyz), "--unpack-to", str(root), "--unpack-only"])
    if rc:
        warn(f"the new .pyz couldn't upgrade {root} - run it yourself: python {pyz}")
        return rc
    good(f"seqtool {new['version']} is in {root} (from {pyz.name})")
    return _restart(root / "seqtool.py",
                    f"to use it: quit seqtool and start it again (python {pyz.name}, or as you always do)")


def _via_zip(new: dict, root: Path) -> int:
    """A .zip goes into a folder of its own beside this one: seqtool-X.Y.Z."""
    dest = root.parent / f"seqtool-{new['version']}"
    if dest.exists():
        info(f"{dest} is there already")
    else:
        tmp = root.parent / f".seqtool-{new['version']}-download"
        zpath = _download(new["zip"], tmp / "seqtool.zip")
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(tmp / "x")
        top = tmp / "x"
        while not (top / "seqtool.py").exists():               # a GitHub archive: one folder inside
            subs = [p for p in top.iterdir() if p.is_dir()]
            if len(subs) != 1:
                shutil.rmtree(tmp, ignore_errors=True)
                raise RuntimeError("the download has no seqtool.py")
            top = subs[0]
        shutil.move(str(top), str(dest))
        shutil.rmtree(tmp, ignore_errors=True)
        good(f"seqtool {new['version']} is in {dest}")
    return _restart(dest / "seqtool.py",
                    f"to use it: quit seqtool and start it from the new folder - cd {dest} and python seqtool.py "
                    f"(your preferences and songs carry over; the old folder {root.name} can go once you're happy)")


def _restart(script: Path, how: str) -> int:
    from .prompt import ask, gui_asker, interactive, terminal
    info("  " + how)
    if gui_asker() is not None or not interactive() or not terminal():
        return 0
    if ask("Restart seqtool with it now? [Y/n]", "y", show_default=False).strip().lower() in ("n", "no"):
        return 0
    info("restarting seqtool ...")
    sys.stdout.flush()
    sys.stderr.flush()
    args = [a for a in sys.argv[1:]]
    os.execv(sys.executable, [sys.executable, str(script), *args])
    return 0                                                     # not reached


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool update", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="only say whether there is a newer version")
    ap.add_argument("--yes", action="store_true", help="get it without asking")
    a = ap.parse_args(argv)
    from seqtool import __version__
    try:
        new = check(force=True)
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"update: couldn't look at {REPO_URL} ({e}) - is the network there?") from None
    got = config.answer("update_check") or {}
    if not new:
        if not got.get("latest"):
            print(f"couldn't find a published seqtool version at {REPO_URL} (no network, or nothing published yet)")
        else:
            print(f"seqtool {__version__} is the newest (published: {got['latest']['version']})")
        return 0
    if a.check:
        print(f"seqtool {new['version']} is available (this is {__version__}) - 'update' gets it; {new['page']}")
        return 0
    return offer(new, a.yes)


if __name__ == "__main__":
    sys.exit(main())
