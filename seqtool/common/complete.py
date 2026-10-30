"""Completion for the seqtool> prompt and the GUI console (0.19.5), IDE-style: as you
type, the commands, then each command's options and sub-commands, then the values that
fit where the cursor is - file and folder names, props and groups of your layout,
effects, presets, faces, Whisper models, sections (@#3) ...

    complete(line) -> {"start": index in line where the word being completed begins,
                       "word": that word, "items": [{"text", "hint"}, ...]}

What a command accepts is read from its own argparse parser (built by calling the
command with a parse_args that stops right away), so new commands and options
complete without being listed here; COMMAND_WORDS only adds the words a command
takes in free-form positionals (face build / use / show ...).
"""
from __future__ import annotations

import argparse
import importlib
import os
import re
import shlex
from glob import glob
from pathlib import Path

_PARSERS: dict[str, argparse.ArgumentParser | None] = {}
MAX = 40

# free-form positionals: the words for the first / later positions ('*' = a kind of value)
COMMAND_WORDS = {
    "face": [["build", "use", "show", "write", "remove", "list", "format"]],
    "baseline": [["add", "remove", "update", "diff", "save"]],
    "rules": [["add", "test", "remove"]],
    "pin": [["*target"], ["*time", "*effect"], ["*effect"]],
    "unpin": [["*target"], ["*time"]],
    "promote": [["*target", "*time"]],
    "demote": [["*target"], ["*time"]],
    "reroll": [["*target"], ["*time"]],
    "explain": [["*target", "music"], ["*time"]],
    "react": [["*target"], ["*preset"], ["*time"]],
    "groups": [["*group", "*anyprop"]],                 # 0.21.6: names, not files
    "models": [["*anyprop"]],
    "prefer": [["*target"], ["*effect"]],
    "help": [["*command"]],
    "history": [["-c"]],
    "xsq-borrow": [["*path"]],
    "borrow": [["*target"], ["*time"]],
    "unborrow": [["*target"], ["*time"]],
    "pref": [["*prefname", "changed", "edit", "reset"], ["*prefnext"], ["*prefvalue"]],
    "cd": [["*dir"]],
    "dir": [["*path"]],
    "ls": [["*path"]],
    "tutorial": [["*tutorial"]],
    "inspect": [["*inspect"]],
    "play": [["*time"]],
    "seek": [["*time"]],
    "layout": [["*path"]],
}
FACE_SUB = {"build": ["*prop", "*path"], "use": ["*prop", "*face"], "show": ["*face"], "write": ["*face"],
            "remove": ["*face"]}
PATH_DESTS = {"audio", "file", "out", "matchup", "music", "layout", "rgbeffects", "output", "dictionary", "dir",
              "preferences", "unpack_to"}


class _Stop(Exception):
    def __init__(self, parser):
        self.parser = parser


def parser_of(cmd: str) -> argparse.ArgumentParser | None:
    """The command's argparse parser, built without running the command."""
    if cmd in _PARSERS:
        return _PARSERS[cmd]
    from ..__main__ import discover
    cmds = discover()
    got = None
    if cmd in cmds:
        mod, func, _, _ = cmds[cmd]
        import inspect
        fn = getattr(importlib.import_module(mod), func)
        try:
            parses = "parse_args" in inspect.getsource(fn)
        except (OSError, TypeError):
            parses = False
        if not parses:                                 # no argparse here: calling it would RUN it (0.19.9 - 'pref'
            _PARSERS[cmd] = None                       # printed its list, 'undo' would have undone)
            return None
        import threading
        orig = argparse.ArgumentParser.parse_args
        me = threading.current_thread()

        def stop(self, *a, **k):                       # only in this thread: a command may be running in another
            if threading.current_thread() is me:
                raise _Stop(self)
            return orig(self, *a, **k)
        argparse.ArgumentParser.parse_args = stop
        try:
            fn([])                                     # stops at its parse_args (output isn't redirected: a
                                                       # command running in another thread would lose its own)
        except _Stop as e:
            got = e.parser
        except BaseException:  # noqa: BLE001 - a command that does things before parsing: no options then
            got = None
        finally:
            argparse.ArgumentParser.parse_args = orig
    _PARSERS[cmd] = got
    return got


def _abc(text: str) -> list:
    """Alphabetical, any case, numbers in order (Flood2 before Flood10) - 0.21.4."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", text)]


def _files(word: str, dirs_only: bool = False) -> list[dict]:
    raw = os.path.expanduser(word)
    out = []
    for p in sorted(glob(raw + "*"), key=_abc)[:MAX * 2]:
        d = os.path.isdir(p)
        if dirs_only and not d:
            continue
        shown = p if not word.startswith("~") else "~" + p[len(os.path.expanduser("~")):]
        out.append({"text": shown + ("/" if d else ""), "hint": "folder" if d else "file", "space": not d})
    return out


def _layout_names(kind: str | None = None, every: bool = False) -> list[dict]:
    try:
        from ..layout import store
        got = store.current() if store.source_info() else None
    except Exception:  # noqa: BLE001
        got = None
    if not got:
        return []
    out = []
    for m in got[1]["models"]:
        if kind and m["kind"] != kind:
            continue
        if m["kind"] == "submodel" or (not every and not m.get("supported_for_generation", True)):
            continue
        out.append({"text": m["id"], "hint": m["kind"] + (f", {m.get('geometry_class', '').lower()}" if m.get("geometry_class") else "")})
    return sorted(out, key=lambda x: _abc(x["text"]))


def _targets() -> list[dict]:
    """The planned targets of the current song (as pin / explain name them), else the layout's."""
    try:
        from . import current
        from .canonical import read_json
        s = current.song()
        if s and s.get("matchup"):
            plans = read_json(s["matchup"])["plans"]
            seen, out = set(), []
            for p in plans:
                if p["target"] not in seen:
                    seen.add(p["target"])
                    out.append({"text": p["target"], "hint": p.get("pass", "main") + " pass"})
            return sorted(out, key=lambda x: _abc(x["text"]))
    except Exception:  # noqa: BLE001
        pass
    return _layout_names()


def _sections() -> list[dict]:
    try:
        from . import current
        from .canonical import read_json
        s = current.song()
        prof = read_json(s["profile"]) if s and s.get("profile") else None
    except Exception:  # noqa: BLE001
        prof = None
    if not prof:
        return [{"text": "@#1", "hint": "section 1"}, {"text": "@0:30", "hint": "a time (m:ss)"}]
    return [{"text": f"@#{x['index']}", "hint": f"{x.get('type', '')} {int(x['start'] // 60)}:{x['start'] % 60:04.1f}"}
            for x in prof["sections"]]


def _effects() -> list[dict]:
    from . import config
    effs = config.load("effects")["effects"]
    return [{"text": k, "hint": v.get("family", "")} for k, v in effs.items() if k != "face"]


def _presets() -> list[dict]:
    try:
        from ..matchup.reactive import load_presets
        return [{"text": k, "hint": "preset"} for k in sorted(load_presets())]
    except Exception:  # noqa: BLE001
        return []


def _faces(prop: str | None = None) -> list[dict]:
    from . import config
    out = [{"text": n, "hint": "built"} for n in (config.answer("built_faces") or {})]
    try:
        from ..layout import store
        lay = store.current()[0] if store.source_info() else None
        for p in (lay or {}).get("props", []):
            if prop and p["id"].lower() != prop.lower():
                continue
            out += [{"text": f["name"], "hint": f"{p['id']}, {f.get('kind')}"} for f in p.get("faces", [])]
    except Exception:  # noqa: BLE001
        pass
    seen, uniq = set(), []
    for x in out:
        if x["text"] not in seen:
            seen.add(x["text"])
            uniq.append(x)
    return uniq


def _pref_names(word: str) -> list[dict]:
    """Preference names, one level at a time: 'mu' -> music, 'music.' -> music.sections ...,
    'music.sections.' -> its settings (0.20.2: they didn't complete after a dot)."""
    try:
        from .prefcmd import _merged, files
    except Exception:  # noqa: BLE001
        return []
    parts = word.split(".")
    if len(parts) == 1:
        return [{"text": f, "hint": "preferences", "space": False} for f in files()]
    f, path, _last = parts[0], parts[1:-1], parts[-1]
    if f not in files():
        return []
    try:
        node = _merged(f)
    except BaseException:  # noqa: BLE001
        return []
    for k in path:
        node = node.get(k) if isinstance(node, dict) else None
        if node is None:
            return []
    if not isinstance(node, dict):
        return []
    base = ".".join([f] + path) + "."
    out = []
    for k, v in node.items():
        if str(k).startswith("_") or "." in str(k):
            continue
        group = isinstance(v, dict) and bool(v)
        import json as _j
        out.append({"text": base + k + ("." if group else ""), "space": not group,
                    "hint": "settings" if group else _j.dumps(v)[:30]})
    return out


def _kind_items(kind: str, word: str, prev: list[str]) -> list[dict]:
    if kind == "target":
        return _targets()
    if kind == "prop":
        return _layout_names("model")
    if kind == "group":                                 # a path typed: the layout file instead
        return [] if word.startswith(("/", "~", ".")) else _layout_names("group", every=True)
    if kind == "anyprop":                               # unused ones too ('models X --enable')
        return [] if word.startswith(("/", "~", ".")) else _layout_names("model", every=True)
    if kind == "time":
        return _sections()
    if kind == "effect":
        return _effects()
    if kind == "preset":
        return _presets()
    if kind == "face":
        return _faces(prev[0] if prev else None)
    if kind == "path":
        return _files(word)
    if kind == "dir":
        return _files(word, dirs_only=True)
    if kind == "preffile":
        try:
            from .prefcmd import files as pref_files
            return [{"text": f, "hint": "preferences"} for f in pref_files()]
        except Exception:  # noqa: BLE001
            return []
    if kind == "prefname":
        return _pref_names(word)
    if kind == "prefnext":                              # after a name: '=' to set it
        if prev and prev[0] in ("reset",):
            return _pref_names(word)
        if prev and prev[0] == "edit":
            return _kind_items("preffile", word, [])
        return [{"text": "=", "hint": "set it"}]
    if kind == "prefvalue":
        try:
            from .prefcmd import MISSING, _get, _merged, choices_for, resolve
            if len(prev) >= 2 and prev[1] == "=":
                f, path = resolve(prev[0])
                ch = choices_for(f, path)
                if ch:
                    return [{"text": c, "hint": ""} for c in ch]
                v = _get(_merged(f), path)
                if isinstance(v, bool):
                    return [{"text": "true", "hint": ""}, {"text": "false", "hint": ""}]
                if v is not MISSING:
                    import json as _j
                    return [{"text": _j.dumps(v), "hint": "the current value"}]
        except BaseException:  # noqa: BLE001 - resolve() exits on unknown names
            return []
        return []
    if kind == "command":
        from ..__main__ import discover
        return [{"text": n, "hint": h} for n, (_, _, _, h) in sorted(discover().items())]
    if kind == "tutorial":
        try:
            from ..tutorial import tutorials
            return [{"text": k, "hint": v.get("title", "")} for k, v in tutorials().items()]
        except Exception:  # noqa: BLE001
            return []
    if kind == "inspect":
        try:
            from ..inspect import targets
            return [{"text": k, "hint": h} for k, (_, _, h) in sorted(targets().items())]
        except Exception:  # noqa: BLE001
            return []
    return []


def _value_items(cmd: str, action, word: str) -> list[dict]:
    """Values for an option or positional of the command's parser."""
    if action.choices:
        return [{"text": str(c), "hint": ""} for c in action.choices]
    dest = action.dest
    if dest == "model":
        from ..music.transcribe import MEMORY_GB
        return [{"text": k, "hint": f"about {v} GB"} for k, v in MEMORY_GB.items()]
    if dest in ("prop", "target"):
        return _layout_names("model")
    if dest == "group":
        return _layout_names("group")
    if dest == "submodel":
        try:
            from ..layout import store
            return [{"text": m["id"], "hint": "submodel"} for m in store.current()[1]["models"] if m["kind"] == "submodel"]
        except Exception:  # noqa: BLE001
            return []
    if dest in PATH_DESTS or getattr(action.type, "__name__", "") == "arg" or "path" in (action.help or "").lower():
        return _files(word, dirs_only=dest in ("out", "dir", "preferences", "unpack_to"))
    return []


def complete_answer(text: str, kind: str) -> dict:
    """Completion while a question is asked (0.24.3): paths for 'dir' / 'file' questions."""
    toks = text.rsplit(" ", 1) if kind not in ("dir", "file") else [text]
    word = toks[-1]
    items = _files(word, dirs_only=kind == "dir") if kind in ("dir", "file") else []
    return {"start": len(text) - len(word), "word": word, "items": items}


def complete(line: str) -> dict:
    from ..__main__ import BUILTINS, discover
    try:
        toks = shlex.split(line)
        if line.endswith(" ") and not line.endswith("\\ "):
            toks.append("")
    except ValueError:                                 # an open quote: complete the quoted word
        toks = shlex.split(line + '"')
    if not toks:
        toks = [""]
    word = toks[-1]
    start, q, i = 0, None, 0                          # where the last word begins in the raw line
    while i < len(line):
        c = line[i]
        if c == "\\" and q != "'":
            i += 2
            continue
        if q:
            q = None if c == q else q
        elif c in "\"'":
            q = c
        elif c == " ":
            start = i + 1
        i += 1
    items: list[dict] = []
    if len(toks) == 1:
        names = discover()
        items = [{"text": n, "hint": h} for n, (_, _, _, h) in sorted(names.items())] + \
                [{"text": n, "hint": h[1] if isinstance(h, tuple) else str(h)} for n, h in sorted(BUILTINS.items())]
    else:
        cmd = toks[0]
        cmds = discover()
        hits = [n for n in cmds if n.startswith(cmd)]
        if cmd not in cmds and len(hits) == 1:
            cmd = hits[0]
        ap = parser_of(cmd)
        prev = toks[1:-1]
        opt_actions = {o: a for a in (ap._actions if ap else []) for o in a.option_strings}
        last = prev[-1] if prev else None
        eq = ""
        if word.startswith("--") and "=" in word and word.split("=", 1)[0] in opt_actions:   # 0.24.58: --audio=FILE
            last, (eq, word) = word.split("=", 1)[0], (word.split("=", 1)[0] + "=", word.split("=", 1)[1])
            start += len(eq)
        if last in opt_actions and opt_actions[last].nargs != 0 and not (opt_actions[last].nargs == "?" and word.startswith("-")):
            items = _value_items(cmd, opt_actions[last], word)
        elif word.startswith("-") and ap:
            items = [{"text": o, "hint": (a.help or "").split(" (")[0][:70]} for a in ap._actions
                     for o in a.option_strings if o.startswith("--") and o != "--help"]
        else:
            free = [t for i, t in enumerate(prev) if not t.startswith("-")
                    and not (i > 0 and prev[i - 1] in opt_actions and opt_actions[prev[i - 1]].nargs != 0)]
            pos = len(free)
            spec = COMMAND_WORDS.get(cmd)
            if cmd == "face" and free and free[0] in FACE_SUB:
                sub = FACE_SUB[free[0]]
                spec = [[free[0]]] + [[k] for k in sub]
            kinds: list[str] = []
            if spec:
                kinds = spec[min(pos, len(spec) - 1)] if pos < len(spec) or cmd in ("pin",) else []
            elif ap:
                posacts = [a for a in ap._actions if not a.option_strings and a.dest != "help"]
                if pos < len(posacts):
                    items = _value_items(cmd, posacts[pos], word)
                elif posacts and posacts[-1].nargs in ("*", "+"):
                    items = _value_items(cmd, posacts[-1], word)
            for k in kinds:
                if k.startswith("*"):
                    items += _kind_items(k[1:], word, free[1:] if cmd == "face" else free)
                else:
                    items.append({"text": k, "hint": ""})
            if not items and (word.startswith(("/", "~", ".")) or "/" in word or "\\" in word):
                items = _files(word)
    low = word.lower()
    if any(c in word for c in "*?["):                 # 0.24.58: a pattern typed - what it matches
        import fnmatch
        items = [x for x in items if fnmatch.fnmatch(x["text"].lower(), low + "*")]
        low = ""
    if word.startswith("@"):
        low = word.lower()
    items = [x for x in items if x["text"].lower().startswith(low)] or \
            [x for x in items if low and low in x["text"].lower()]
    out, seen = [], set()
    for x in items:
        if x["text"] not in seen:
            seen.add(x["text"])
            q = x["text"]
            if re.search(r"[\s\"'#]", q) and not q.startswith("@#"):
                q = '"' + q.replace('"', '\\"') + '"'
            out.append({"text": q, "hint": x.get("hint", ""), "space": x.get("space", True)})
    return {"start": start, "word": word, "items": out[:MAX]}
