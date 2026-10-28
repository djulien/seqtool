# seqtool-command: inspect | main | look | show details: inspect xlights | layout | audio [file]
"""seqtool inspect TARGET [args]

Shows details about one thing. Targets are discovered from tags in the
modules that know about them:

    # seqtool-inspect: name | function | help

so new targets can be added without touching this file.
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent
TAG = re.compile(r"^# seqtool-inspect:\s*([\w-]+)\s*\|\s*(\w+)\s*\|\s*(.*)$", re.M)


def targets() -> dict[str, tuple[str, str, str]]:
    out = {}
    for f in sorted(PKG.rglob("*.py")):
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        for name, func, helptext in TAG.findall(text):
            mod = "seqtool." + ".".join(f.relative_to(PKG).with_suffix("").parts)
            out[name] = (mod, func, helptext.strip())
    return out


def main(argv=None) -> int:
    argv = list(argv or [])
    t = targets()
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: inspect TARGET [args]\n")
        for name, (_, _, h) in sorted(t.items()):
            print(f"  {name:<10} {h}")
        return 0
    name = argv[0]
    hits = [n for n in t if n.startswith(name)]
    if name not in t and len(hits) != 1:
        raise SystemExit(f"unknown inspect target '{name}' (have: {', '.join(sorted(t))}; e.g. 'inspect audio')")
    mod, func, _ = t[name if name in t else hits[0]]
    lines = getattr(importlib.import_module(mod), func)(argv[1:])
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
