"""seqtool.pyz - the launcher that starts the newest seqtool beside it (0.24.59).

Built by 'seqtool package' next to seqtool-X.Y.Z.pyz. It holds no seqtool of its own:
it looks in its own folder for

* seqtool-X.Y.Z.pyz files (each one holds a whole seqtool), and
* the unpacked 'seqtool' folder they unpack into, and seqtool-X.Y.Z folders (where
  seqtool's 'update' puts a downloaded .zip) - a .seqtool-manifest.json or VERSION file
  says which version each is,

and runs the newest, with the same arguments. A .pyz newer than the unpacked folder
upgrades that folder first (as running it by hand would). So keep seqtool.pyz as the
one thing you start (a shortcut, a double-click) and drop newer seqtool-X.Y.Z.pyz
downloads beside it - or let seqtool's 'update' command put them there.

Its own option: --which   say what it would run, and stop.
Standard library only.
"""
import json
import os
import re
import subprocess
import sys

NAME = re.compile(r"^seqtool-(\d+(?:\.\d+)*)\.pyz$", re.I)


def vtuple(v):
    try:
        return tuple(int(x) for x in str(v).strip().split("."))
    except ValueError:
        return ()


def here():
    p = os.path.abspath(sys.argv[0] if sys.argv and sys.argv[0] else __file__)
    return p if os.path.isdir(p) else os.path.dirname(p)


def unpacked_version(folder):
    """The version of an unpacked seqtool folder, or None."""
    for f, read in ((".seqtool-manifest.json", lambda t: json.loads(t).get("version")), ("VERSION", str.strip)):
        p = os.path.join(folder, f)
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as fh:
                    return read(fh.read()) or None
            except (OSError, ValueError):
                pass
    return None


def candidates(folder):
    """[(version tuple, kind, path)] - kind 'pyz' or 'folder' - newest first."""
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        names = []
    for n in names:
        m = NAME.match(n)
        if m:
            out.append((vtuple(m.group(1)), "pyz", os.path.join(folder, n)))
    subs = ["seqtool"] + [n for n in names if re.match(r"^seqtool-\d+(\.\d+)*$", n)]   # update's own folders too
    for sub in subs:
        d = os.path.join(folder, sub)
        v = unpacked_version(d) if os.path.isfile(os.path.join(d, "seqtool.py")) else None
        if v:
            out.append((vtuple(v), "folder", d))
    # the same version as a folder and a .pyz: the folder (nothing to unpack)
    out.sort(key=lambda c: (c[0], c[1] == "folder"), reverse=True)
    return out


def main():
    args = sys.argv[1:]
    folder = here()
    found = candidates(folder)
    if not found:
        print(f"seqtool.pyz: no seqtool beside it in {folder}\n"
              "  Put a seqtool-X.Y.Z.pyz (from https://github.com/djulien/seqtool) in this folder, then start "
              "seqtool.pyz again.")
        if os.name == "nt" and not os.environ.get("PROMPT"):
            input("Press Enter to close this window ")
        return 1
    ver, kind, path = found[0]
    label = ".".join(map(str, ver))
    if "--which" in args:
        print(f"seqtool {label}: {path}")
        return 0
    cmd = [sys.executable, path] + args if kind == "pyz" else [sys.executable, os.path.join(path, "seqtool.py")] + args
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
