# seqtool-command: pref | main | setup | see or change preferences: pref, pref NAME, pref NAME = VALUE, pref edit FILE
"""seqtool pref [NAME] [= VALUE] | pref reset NAME | pref changed | pref edit FILE

    pref                          list the preference files
    pref sections                 show a node; any depth, dots or slashes:
    pref music.sections.min_bars      music.sections.min_bars  ==  music/sections/min_bars
    pref min_bars                 a unique key name alone also works
    pref min_bars = 12            set a value (numbers, true/false, lists, {...} are JSON;
                                  anything else is text) - stored in YOUR preferences only
    pref reset min_bars           back to the built-in default
    pref changed                  everything you have changed
    pref edit music               open your music.json in a text editor ($EDITOR)

Keys that contain dots (e.g. group names like "1.ALL") need slash notation:
    pref models/targets/1.ALL/role = top

Built-in defaults are never modified; your values are kept in the user
preference folder (see 'pwd') and override the defaults key by key.
Lines marked * are your values.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from . import config
from .log import good, info, warn
from .paths import show

MISSING = object()


# extra preference "files" whose defaults live elsewhere; user values go under a key of another file
VIRTUAL = {"param_map": {"default": Path(__file__).resolve().parents[1] / "adapters" / "xlights" / "param_map.json",
                         "user_file": "xlights", "user_key": "param_map"}}


def files() -> list[str]:
    return sorted([p.stem for p in config.DEFAULT_DIR.glob("*.json")] + list(VIRTUAL))


def _read_user_file(fname: str) -> dict:
    f = config.user_dir() / f"{fname}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except ValueError as e:
            raise SystemExit(f"{show(f)} is not valid JSON ({e}); fix it with 'pref edit {fname}'")
    return {}


def _user(name: str) -> dict:
    if name in VIRTUAL:
        v = VIRTUAL[name]
        return dict(_read_user_file(v["user_file"]).get(v["user_key"], {}))
    u = _read_user_file(name)
    for vname, v in VIRTUAL.items():                       # hide virtual sub-trees from their host file
        if v["user_file"] == name:
            u.pop(v["user_key"], None)
    return u


def _save_user(name: str, data: dict) -> Path:
    if name in VIRTUAL:
        v = VIRTUAL[name]
        host = _read_user_file(v["user_file"])
        if data:
            host[v["user_key"]] = data
        else:
            host.pop(v["user_key"], None)
        return config.save(v["user_file"], host)
    host = _read_user_file(name)
    keep = {v["user_key"]: host[v["user_key"]] for v in VIRTUAL.values()
            if v["user_file"] == name and v["user_key"] in host}
    return config.save(name, {**data, **keep})


def _default(name: str) -> dict:
    if name in VIRTUAL:
        return json.loads(VIRTUAL[name]["default"].read_text(encoding="utf-8"))
    return json.loads((config.DEFAULT_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _merged(name: str) -> dict:
    return config._merge(_default(name), _user(name))


def _get(d, path):
    for k in path:
        if not isinstance(d, dict) or k not in d:
            return MISSING
        d = d[k]
    return d


def uses(*names: str, width: int = 100) -> list[str]:
    """The preferences a command's output depends on, with their values (the user's rule,
    0.20.0: a command affected by preferences says which): lines to print at the end,
    e.g. uses("xlights.exclude_controllers", "xlights.exclude_layout_groups")."""
    parts = []
    for n in names:
        f, *path = n.split(".")
        try:
            v = _get(_merged(f), tuple(path))
            mine = _get(_user(f), tuple(path)) is not MISSING
        except (SystemExit, OSError, ValueError):
            continue
        if v is MISSING:
            continue
        txt = json.dumps(v, ensure_ascii=False)
        if len(txt) > 40:
            txt = txt[:37] + "..."
        parts.append(f"{n} = {txt}" + (" (yours)" if mine else ""))
    if not parts:
        return []
    out, cur = [], "settings used: "
    for i, x in enumerate(parts):
        piece = x + ("; " if i < len(parts) - 1 else "")
        if len(cur) + len(piece) > width and cur.strip() != "settings used:":
            out.append(cur.rstrip())
            cur = "  "
        cur += piece
    out.append(cur.rstrip())
    out[-1] += "  ('pref NAME' shows or changes one)"
    return ["{note}" + x + "{/}" for x in out]


def _leaf_paths(d, prefix=()):
    for k, v in d.items():
        if k.startswith("_"):
            continue
        yield prefix + (k,)
        if isinstance(v, dict):
            yield from _leaf_paths(v, prefix + (k,))


def resolve(name: str) -> tuple[str, tuple]:
    """'music.sections.min_bars', 'music/sections/min_bars', 'sections', 'min_bars' -> (file, path)."""
    parts = [p for p in (name.split("/") if "/" in name else name.split(".")) if p]
    if not parts:
        raise SystemExit("empty name")
    fl = files()
    hits = [f for f in fl if f == parts[0]] or [f for f in fl if f.startswith(parts[0])]
    if len(hits) == 1 and (len(parts) > 1 or parts[0] in fl or not _search(parts)):
        return hits[0], tuple(parts[1:])
    found = _search(parts)
    if len(found) == 1:
        return found[0]
    if found:
        more = f" (+{len(found) - 8} more)" if len(found) > 8 else ""
        raise SystemExit(f"'{name}' is ambiguous - give more of the path: "
                         + ", ".join(f + "." + ".".join(p) for f, p in found[:8]) + more)
    if len(parts) > 1:                                # a new name in a map of your own (section_types.spoken)
        maps = _search_maps(parts[:-1])
        if len(maps) == 1:
            return maps[0][0], maps[0][1] + (parts[-1],)
    raise SystemExit(f"no preference named '{name}' ('pref' lists the files)")


def _search_maps(parts) -> list[tuple[str, tuple]]:
    """Places whose path ends with `parts` and that hold a mapping (where new names can go)."""
    out = []

    def walk(f, node, path):
        if isinstance(node, dict):
            if path and tuple(parts) == path[-len(parts):]:
                out.append((f, path))
            for k, v in node.items():
                if not str(k).startswith("_"):
                    walk(f, v, path + (k,))
    for f in files():
        walk(f, _merged(f), ())
    return out


def _search(parts) -> list[tuple[str, tuple]]:
    out = []
    for f in files():
        merged = _merged(f)
        for p in _leaf_paths(merged):
            if tuple(parts) == p[-len(parts):]:
                out.append((f, p))
    return out


# settings with a fixed set of values (0.20.2: 'pref NAME' shows them, setting another is refused);
# '*' stands for any one key
CHOICES = {
    "xlights.shadow_models": ["skip_shadow", "sequence_shadow"],
    "scoring.passes.base.members": ["cut", "over", "under"],
    "scoring.passes.variation.aspect": ["auto", "color", "direction", "effect"],
    "scoring.decision.grid": ["downbeat", "bar", "beat"],
    "music.sections.method": ["novelty", "laplacian", "combined"],
    "music.sections.snap": ["bar", "beat", "none"],
    "models.group_roles.*": ["auto", "top", "unit", "detail", "unused"],
    "models.targets.*.role": ["top", "unit", "detail", "unused"],
    "models.targets.*.base_members": ["cut", "over", "under"],
}
DURATION_KEYS = ("scoring.durations.",)


def choices_for(name: str, path: tuple) -> list | None:
    key = ".".join((name,) + tuple(path))
    for pat, ch in CHOICES.items():
        a, b = pat.split("."), key.split(".")
        if len(a) == len(b) and all(x == "*" or x == y for x, y in zip(a, b)):
            return ch
    return None


def about(name: str, path: tuple, value) -> list[str]:
    """What a setting may be and what it does: its valid values (or kind of value) and the
    sentences of the nearest description that name it."""
    out = []
    ch = choices_for(name, path)
    key = ".".join((name,) + tuple(path))
    if ch:
        out.append("valid values: " + " | ".join(ch))
    elif key.startswith(DURATION_KEYS):
        out.append('valid values: seconds (e.g. 2.5), "N bars" or "N beats" (e.g. "8 bars"), or null (no limit)')
    elif isinstance(value, bool):
        out.append("valid values: true | false")
    elif isinstance(value, (int, float)):
        out.append("valid values: a number")
    elif isinstance(value, list):
        out.append('valid values: a list, e.g. ["a", "b"] (or [] for none)')
    elif value is None:
        out.append("valid values: a value, or null")
    merged = _merged(name)
    k = path[-1] if path else name
    for depth in range(len(path), -1, -1):              # the nearest description that mentions it
        node = _get(merged, path[:depth])
        doc = node.get("_doc") if isinstance(node, dict) else None
        if not doc:
            continue
        import re as _re
        sents = [x.strip() for x in _re.split(r"(?<!e\.g\.)(?<!i\.e\.)(?<=\.)\s+", doc) if _re.search(rf"\b{_re.escape(k)}\b", x)]
        if sents:
            for line in textwrap.wrap("about: " + " ".join(sents[:3]), 100):
                out.append(line)
            break
    return out


def _fmt(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def render(name: str, path: tuple) -> list[str]:
    merged, user, dflt = _merged(name), _user(name), _default(name)
    node = _get(merged, path)
    if node is MISSING:
        raise SystemExit(f"{name}.{'.'.join(path)} does not exist - 'pref {name}' shows what is there")
    title = name + ("." + ".".join(path) if path else "")
    lines = []
    if not isinstance(node, dict):
        u, d = _get(user, path), _get(dflt, path)
        lines.append(f"{title} = {_fmt(node)}" + (f"   * yours (default {_fmt(d)})" if u is not MISSING and d is not MISSING
                                                   else "   * yours" if u is not MISSING else ""))
        lines += ["  " + x for x in about(name, path, node)]
        return lines
    doc = node.get("_doc")
    if doc:
        lines += ["# " + l for l in textwrap.wrap(doc, 96)]
    lines.append(f"{title}:")

    def walk(n, p, depth):
        for k, v in n.items():
            if k.startswith("_"):
                continue
            pp = p + (k,)
            u = _get(user, pp)
            pad = "  " * depth
            if isinstance(v, dict):
                lines.append(f"{pad}{k}:" + ("" if v else " {}"))
                walk(v, pp, depth + 1)
            else:
                mark = ""
                if u is not MISSING:
                    d = _get(dflt, pp)
                    mark = f"   * yours" + (f" (default {_fmt(d)})" if d is not MISSING else " (added)")
                lines.append(f"{pad}{k} = {_fmt(v)}{mark}")
    walk(node, path, 1)
    return lines


def _parse_value(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text


def _compatible(new, old) -> bool:
    if old is MISSING:
        return True
    num = (int, float)
    if isinstance(old, bool) or isinstance(new, bool):
        return isinstance(old, bool) == isinstance(new, bool) or old is None
    if isinstance(old, num) and isinstance(new, num):
        return True
    if "auto" in (old, new) and (isinstance(old, num) or isinstance(new, num) or old == new):
        return True                                       # 'auto' or a number (e.g. vocal_gate_db)
    return old is None or type(new) is type(old)


def set_value(name: str, path: tuple, value, force: bool = False) -> Path:
    if not path:
        raise SystemExit("give a key inside the file, e.g. 'pref music.sections.min_bars = 12'")
    merged = _merged(name)
    old = _get(merged, path)
    if old is MISSING:
        depth = len(path) - 1                              # deepest existing ancestor must be a dict
        while depth > 0 and _get(merged, path[:depth]) is MISSING:
            depth -= 1
        if not isinstance(_get(merged, path[:depth]) if depth else merged, dict):
            raise SystemExit(f"{name}.{'.'.join(path[:depth])} is not a group of settings")
        warn(f"{name}.{'.'.join(path)} is a new key (not in the defaults) - check the spelling")
    ch = choices_for(name, path)
    if ch and value not in ch and not force:
        raise SystemExit(f"{name}.{'.'.join(path)} can be {' | '.join(ch)} - e.g. 'pref {name}.{'.'.join(path)} = {ch[0]}'")
    if not force and not _compatible(value, old):
        raise SystemExit(f"{name}.{'.'.join(path)} is {type(old).__name__} ({_fmt(old)}); "
                         f"{_fmt(value)} is {type(value).__name__} - use --force to set it anyway")
    user = _user(name)
    node = user
    for k in path[:-1]:
        node = node.setdefault(k, {})
    node[path[-1]] = value
    return _save_user(name, user)


def reset_value(name: str, path: tuple) -> bool:
    user = _user(name)
    if not path:
        if not user:
            return False
        _save_user(name, {})
        return True
    chain = [user]
    for k in path[:-1]:
        if not isinstance(chain[-1], dict) or k not in chain[-1]:
            return False
        chain.append(chain[-1][k])
    if path[-1] not in chain[-1]:
        return False
    del chain[-1][path[-1]]
    for i in range(len(path) - 1, 0, -1):                 # prune empty parents
        if chain[i] == {}:
            del chain[i - 1][path[i - 1]]
    _save_user(name, user)
    return True


def changed() -> list[str]:
    out = []
    for f in files():
        user = _user(f)
        for p in _leaf_paths(user):
            v = _get(user, p)
            if not isinstance(v, dict):
                d = _get(_default(f), p)
                out.append(f"{f}.{'.'.join(p)} = {_fmt(v)}" + (f"   (default {_fmt(d)})" if d is not MISSING else "   (added)"))
    return out


def editor_command() -> list[str] | None:
    for var in ("VISUAL", "EDITOR"):
        if os.environ.get(var):
            return os.environ[var].split()
    for cand in ("nano", "vim", "vi", "notepad"):
        if shutil.which(cand):
            return [cand]
    return None


def edit(name: str) -> int:
    if name in VIRTUAL:
        info(f"{name} values are stored in {VIRTUAL[name]['user_file']}.json under \"{VIRTUAL[name]['user_key']}\"")
        name = VIRTUAL[name]["user_file"]
    f = config.user_dir() / f"{name}.json"
    if not f.exists():
        config.user_dir().mkdir(parents=True, exist_ok=True)
        f.write_text("{\n}\n", encoding="utf-8")
    cmd = editor_command()
    if cmd is None:
        raise SystemExit(f"no text editor found - set $EDITOR, or edit {show(f)} yourself")
    info(f"editing {show(f)} (only your changes go here; 'pref {name}' shows the defaults)")
    from .prompt import ask
    while True:
        subprocess.call(cmd + [str(f)])
        try:
            json.loads(f.read_text(encoding="utf-8"))
            good(f"{show(f)} is valid; takes effect on the next run")
            return 0
        except ValueError as e:
            warn(f"not valid JSON: {e}")
            if ask("edit again? [Y/n]", "y", show_default=False).lower() in ("n", "no"):
                warn("left as is - seqtool will report this file until it is fixed")
                return 1


def main(argv=None) -> int:
    argv = list(argv or [])
    force = "--force" in argv
    argv = [a for a in argv if a != "--force"]
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if not argv:
        print("preference files (built-in defaults; * = you have changes):")
        for f in files():
            d = _default(f)
            mark = "*" if _user(f) else " "
            doc = (d.get("_doc") or "").split(". ")[0][:80]
            print(f"  {mark} {f:<10} {doc}")
        print(f"your values: {show(config.user_dir())}   ('pref NAME' to look, 'pref NAME = VALUE' to change)")
        return 0
    if argv[0] == "changed":
        lines = changed()
        print("\n".join(lines) if lines else "no changes - everything is at the built-in defaults")
        return 0
    if argv[0] == "edit":
        if len(argv) < 2:
            raise SystemExit("pref edit FILE   (one of: " + ", ".join(files()) + ")")
        name, _ = resolve(argv[1])
        return edit(name)
    if argv[0] == "reset":
        if len(argv) < 2:
            raise SystemExit("pref reset NAME  (e.g. 'pref reset min_bars'; 'pref changed' lists your values)")
        name, path = resolve(argv[1])
        if reset_value(name, path):
            good(f"{name}{'.' + '.'.join(path) if path else ''} is back to the default")
        else:
            info("nothing to reset - that is already the default")
        return 0
    text = " ".join(argv)
    if "=" in text:
        key, val = text.split("=", 1)
        name, path = resolve(key.strip())
        f = set_value(name, path, _parse_value(val.strip()), force)
        good(f"{name}.{'.'.join(path)} = {_fmt(_get(_merged(name), path))}   (saved in {show(f)}; "
             "takes effect on the next run)")
        return 0
    name, path = resolve(text.strip())
    for line in render(name, path):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
