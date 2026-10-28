# seqtool-command: tutorial | main | look | guided walk-throughs of common tasks: tutorial [NAME]
"""seqtool tutorial [NAME] [--restart]

Guided walk-throughs, one step at a time (like the xLights training wizard):
each step says what to do and checks that it happened before moving on.

At the tutorial> prompt:
    Enter       run the suggested command (or confirm a step done outside seqtool)
    any command run it, as at the seqtool> prompt (e.g. your own variation)
    s / b       skip this step / go back one
    q           stop (progress is kept; 'tutorial NAME' resumes)

Without NAME: the list of tutorials and how far you got in each.
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .common import config
from .common.prompt import Cancelled, ask

DATA = Path(__file__).with_name("tutorials.json")


def tutorials() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))["tutorials"]


# ------------------------------------------------------------------ checks
def _song():
    from .common import current
    try:
        return current.song() or {}
    except Exception:  # noqa: BLE001
        return {}


def _models_prefs():
    return config.load("models")


def check(name: str | None, ran_ok: bool) -> bool:
    if not name:
        return ran_ok
    s = _song()
    if name == "matchup":
        return bool(s.get("matchup"))
    if name == "layout_stored":
        from .layout import store
        try:
            return store.current() is not None
        except Exception:  # noqa: BLE001
            return False
    if name == "react_set":
        mp = _models_prefs()
        return any(v.get("react") not in (None, "off") for v in mp.get("targets", {}).values()) or \
            any(r.get("react") for r in mp.get("rules", []) or [])
    if name == "rule_exists":
        return bool(_models_prefs().get("rules"))
    if name == "user_preset":
        f = config.user_dir() / "presets.json"
        try:
            return f.exists() and bool(json.loads(f.read_text()).get("presets"))
        except ValueError:
            return False
    if name in ("lyrics", "section_edit"):
        from .common import songs
        from .common.canonical import file_sha256
        a = s.get("audio")
        if not a or not Path(a).exists():
            return False
        rec = songs.get(file_sha256(Path(a)))
        return bool(rec.get("lyrics") if name == "lyrics" else rec.get("sections"))
    if name == "kit":
        from .adapters.xlights import kit
        from .adapters.xlights.encoding import find
        e = find() if kit.learned_versions() else None
        return bool(e) and not kit.missing_steps(e.version)[1]
    if name in ("words", "faces_used"):                       # 0.19.3: the singing-face tutorial
        if name == "faces_used":
            return any(v.get("face") not in (None, "off") for v in _models_prefs().get("targets", {}).values())
        from .common import songs
        from .common.canonical import file_sha256
        a = s.get("audio")
        if not a or not Path(a).exists():
            return False
        lyr = songs.get(file_sha256(Path(a))).get("lyrics") or {}
        return any(ln.get("words") for ln in lyr.get("lines", []))
    if name == "dictionary":
        from .music.phonemes import cmudict_path, settings
        srcs = settings().get("dictionaries", ["cmudict"])
        return any((cmudict_path(False) if x == "cmudict" else Path(str(x)).expanduser().exists()) for x in srcs)
    if name == "face_built":
        return bool(config.answer("built_faces")) or ran_ok
    if name == "face_in_layout":
        from .layout import store
        built = set(config.answer("built_faces") or {})
        try:
            lay = store.current()[0]
        except Exception:  # noqa: BLE001
            return False
        names = {f["name"] for p in lay["props"] for f in p.get("faces", []) if f.get("kind") == "images"}
        return bool(names & built) if built else bool(names)
    if name == "xsq":
        f = s.get("folder")
        return bool(f) and any(Path(f).glob("*.xsq"))
    return ran_ok


# ------------------------------------------------------------ placeholders
def fill(text: str) -> str:
    if "{" not in text:
        return text
    vals = {"prop": "MegaTree", "group": "Arches", "chorus": "@#3", "rerun": "run", "faceprop": "PROP", "face": "FACE"}
    try:                                                    # a prop that can show an image face, and a face
        from .layout import store
        lay = store.current()[0] if store.source_info() else None
        if lay:
            built = list(config.answer("built_faces") or {})
            withf = [p for p in lay["props"] if p.get("controllable", True) and
                     any(f.get("kind") == "images" for f in p.get("faces", []))]
            grid = [p for p in lay["props"] if p.get("controllable", True) and p.get("render_buffer")]
            pick = next((p for p in withf if any(f["name"] in built for f in p["faces"])), None) or \
                (withf[0] if withf else max(grid, key=lambda p: p["render_buffer"]["columns"] * p["render_buffer"]["rows"],
                                            default=None))
            if pick:
                vals["faceprop"] = pick["id"]
                names = [f["name"] for f in pick.get("faces", []) if f.get("kind") == "images"]
                vals["face"] = next((n for n in names if n in built), None) or (built[-1] if built else
                                                                                (names[0] if names else "FACE"))
    except Exception:  # noqa: BLE001
        pass
    s = _song()
    try:
        from .common.canonical import read_json
        if s.get("matchup"):
            m = read_json(s["matchup"])
            mf = Path(s["matchup"]).with_name(m["source"]["models"]["filename"])
            models = {x["id"]: x for x in read_json(mf)["models"]} if mf.exists() else {}
            planned = [p["target"] for p in m["plans"] if p["segments"] and not p.get("react")]
            props = [t for t in planned if models.get(t, {}).get("kind") == "model"] or planned
            groups = [t for t in planned if models.get(t, {}).get("kind") == "group"]
            if props:
                vals["prop"] = max(props, key=lambda t: (models.get(t, {}).get("node_count", 0), t))
            if groups:
                vals["group"] = groups[0]
            prof = Path(s["matchup"]).with_name(m["source"]["music_profile"]["filename"])
            if prof.exists():
                secs = read_json(prof)["sections"]
                ch = next((x for x in secs if x.get("type") == "chorus"), secs[len(secs) // 2])
                vals["chorus"] = f"@#{ch['index']}"
            if "seqtool-demo" in str(s["matchup"]):
                vals["rerun"] = "demo"
    except Exception:  # noqa: BLE001
        pass
    for k, v in vals.items():
        text = text.replace("{" + k + "}", v)
    return text


# -------------------------------------------------------------------- run
def _run_command(line: str) -> bool:
    from .__main__ import _expand, discover, dispatch
    try:
        from .common.args import split_line
        rc = dispatch(_expand(split_line(line)), discover())
        return rc in (0, None)
    except Cancelled:
        print("cancelled")
        return False
    except SystemExit as e:
        if e.code not in (0, None) and not isinstance(e.code, int):
            print(f"{{err}}{e.code}{{/}}")
        return e.code in (0, None)
    except Exception as e:  # noqa: BLE001
        print(f"{{err}}error: {e.__class__.__name__}: {e}{{/}}")
        return False


def run(name: str, restart: bool = False) -> int:
    tut = tutorials().get(name)
    if tut is None:
        raise SystemExit(f"no tutorial '{name}' - 'tutorial' lists them")
    steps = tut["steps"]
    from .common.prompt import interactive
    if not interactive():
        print(f"{{head}}{tut['title']}{{/}} - run it at the seqtool> prompt (or in the GUI) to be walked through it:")
        for k, st in enumerate(steps, 1):
            cmd = fill(st["do"]) if st.get("do") else fill(st.get("manual", ""))
            print(f"  {k}. {fill(st.get('say', ''))}" + (f"  {{do}}{cmd}{{/}}" if cmd else ""))
        return 0
    key = f"tutorial:{name}"
    i = 0 if restart else int(config.answer(key, 0) or 0)
    if i >= len(steps):
        i = 0
    skipped = set() if restart or i == 0 else set(config.answer(key + ":skipped") or [])

    def keep_skipped():
        config.remember(key + ":skipped", sorted(skipped))
    print(f"\n{{head}}{tut['title']}{{/}}  ({len(steps)} steps; Enter = run the suggestion, s = skip, b = back, q = stop)")
    while i < len(steps):
        st = steps[i]
        cmd = fill(st["do"]) if st.get("do") else ""
        cmd = cmd.replace("{rerun}", fill("{rerun}"))
        if cmd == "run":
            cmd = fill("{rerun}")
        print(f"\n{{head}}[{i + 1}/{len(steps)}]{{/}} {fill(st.get('say', ''))}")
        if cmd:
            print(f"      type: {{do}}{cmd}{{/}}   (or press Enter to run it)")
        elif st.get("manual"):
            print(f"      {{do}}{fill(st['manual'])}{{/}}, then press Enter")
        elif st.get("read"):                          # 0.24.14: a step that only explains
            print("      {note}(press Enter to go on){/}")
        else:
            print("      {do}type the command{/} (Enter checks again)")
        while True:
            try:
                ans = ask("tutorial>", "", show_default=False).strip()
            except Cancelled:
                ans = "q"
            low = ans.lower()
            if low in ("q", "quit", "exit"):
                config.remember(key, i)
                print(f"{{note}}stopped at step {i + 1};{{/}} {{do}}tutorial {name}{{/}} {{note}}resumes{{/}}")
                return 0
            if low == "s":
                skipped.add(i)
                keep_skipped()
                i += 1
                break
            if low == "b":
                i = max(0, i - 1)
                break
            if not ans:
                if cmd:
                    print(f"{{note}}$ seqtool {cmd}{{/}}")
                    ok = _run_command(cmd)
                elif st.get("manual") or st.get("read"):
                    ok = True
                else:
                    ok = False
            else:
                ok = _run_command(ans)
            if check(st.get("check"), ok):
                print("{ok}  ✓ done{/}")
                skipped.discard(i)
                keep_skipped()
                i += 1
                config.remember(key, i)
                break
            print("{warn}  not done yet{/} - " + ("try the suggested command, " if cmd else "")
                  + "or s to skip this step")
    config.remember(key, len(steps))
    keep_skipped()
    if skipped:                                       # the user's rule (0.19.9): skipped steps = not done
        nums = ", ".join(str(k + 1) for k in sorted(skipped))
        print(f"\n{{warn}}Tutorial '{name}' incomplete:{{/}} step(s) {nums} skipped - {{do}}tutorial {name}{{/}} "
              "goes through it again. Others: {do}tutorial{/}")
        return 0
    print(f"\n{{ok}}Tutorial '{name}' finished.{{/}} Others: {{do}}tutorial{{/}}")
    return 0


def listing() -> str:
    L = ["{head}Tutorials{/} (each walks you through a task, checking each step):", ""]
    for k, t in tutorials().items():
        done = int(config.answer(f"tutorial:{k}", 0) or 0)
        n = len(t["steps"])
        skip = config.answer(f"tutorial:{k}:skipped") or []
        prog = (f"{{warn}}incomplete{{/}}: step(s) {', '.join(str(x + 1) for x in skip)} skipped" if done >= n and skip
                else "{ok}done{/}" if done >= n else (f"{{warn}}step {done + 1}/{n}{{/}}" if done else f"{n} steps"))
        L.append(f"  {{do}}{k:<11}{{/}} {t['title']}  ({prog})")
    L += ["", "  {do}tutorial NAME{/} to start or resume one; {do}tutorial NAME --restart{/} from the beginning"]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool tutorial", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", nargs="?")
    ap.add_argument("--restart", action="store_true")
    a = ap.parse_args(argv)
    if not a.name:
        print(listing())
        return 0
    names = list(tutorials())
    pick = next((n for n in names if n == a.name), None) or next((n for n in names if n.startswith(a.name)), None)
    if pick is None:
        raise SystemExit(f"no tutorial '{a.name}' - one of: {', '.join(names)} (e.g. 'tutorial {names[0]}')")
    return run(pick, a.restart)


if __name__ == "__main__":
    sys.exit(main())
