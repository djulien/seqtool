# seqtool-command: direct | main | refine | plain-language direction, no connection needed: direct "make the chorus bigger and warmer" | direct --list
"""seqtool direct "WHAT YOU WANT" [--yes] [--dry-run] [--json] [--debug] | direct --list | direct --eval FILE

Turns plain-language direction into seqtool commands without a connection to Claude (0.24.33):
the text is matched against a list of intents (preferences/intents.json - what each one means,
the phrases that say it, the commands that do it and the commands that check it). It shows what
it understood, asks, runs it all as one batch (one re-plan, one undo step) and runs the checks.

    direct "make the chorus bigger"            feel intensity 0.8 @#2
    direct "a little calmer in the second verse, and warmer"
    direct "the arches flash on 'star' and 'night'"
    direct "dark until the vocals"
    direct "the spinners twinkle in the bridge"
    direct "too busy" --dry-run                 only show what it would do
    direct "..." --yes                          no question (scripts, unattended)
    direct --list                               what it understands
    direct --eval cases.txt                     how well it understands: each line
                                                'TEXT => CMD; CMD' (the commands you'd expect,
                                                e.g. Claude's with the seqtool-direction skill);
                                                says which come out the same

Sections by name ("the chorus" = every chorus, "the second chorus" = that one only), props and
groups by name ("the arches"), sung words in quotes, moments as 'at 1:05'. With no prop named,
the whole yard (the group holding the most props). Your own phrases or intents: copy one into
seqtool-prefs/intents.json under "intents". It knows only what the list says - for anything
else, ask Claude (the seqtool-direction skill) or use the commands themselves ('help').
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from ..common import config
from ..common.log import good, info, warn
from . import direct as D


def build_ctx() -> D.Ctx:
    """The current song's sections and the plan's targets (or the layout's props without a plan)."""
    from ..common.canonical import read_json
    ctx = D.Ctx(effects=list(config.load("effects")["effects"]))
    try:
        from .reroll import _context
        _, m, profile, _ = _context()
        ctx.sections = profile.get("sections", [])
        ctx.targets = list(dict.fromkeys(p["target"] for p in m["plans"]))
    except SystemExit:
        m = None
    try:
        from ..layout import store
        models = read_json(store.folder() / "layout.models.json")["models"]
    except Exception:  # noqa: BLE001
        models = []
    groups = {x["id"]: set(x.get("members", [])) for x in models if x.get("kind") == "group"}
    ctx.members = groups
    if not ctx.targets:
        ctx.targets = [x["id"] for x in models if x.get("kind") in ("model", "group")]

    def leaves(g, seen=()):
        out = set()
        for x in groups.get(g, ()):
            if x in groups and x not in seen:
                out |= leaves(x, seen + (g,))
            else:
                out.add(x)
        return out
    cand = [g for g in groups if g in ctx.targets] or list(groups)
    if cand:
        ctx.yard = max(cand, key=lambda g: (len(leaves(g)), -len(g)))
    from .explain import _plain, sung_words, vocals_start
    ctx.vocals_fn = vocals_start
    try:
        ctx.lyrics = sorted({_plain(w["text"]) for w in sung_words() if _plain(w["text"])})
    except Exception:  # noqa: BLE001
        ctx.lyrics = []
    return ctx


def prefs() -> dict:
    return config.load("intents")


def show(res: list[dict], debug: bool = False) -> tuple[list[str], dict]:
    """Lines to print, and {number: (clause index, commands)} for the other readings."""
    L, alts, n = [], {}, 1
    for k, r in enumerate(res, 1):
        head = f"  {k}. \"{r['text']}\""
        if not r["intent"]:
            L.append(head + " {warn}- not understood{/}")
        elif r["missing"]:
            L.append(head + f" -> {r['intent']} {{warn}}needs {', '.join(r['missing'])}{{/}} "
                     + _need_hint(r))
        else:
            L.append(head + f" -> {{head}}{r['intent']}{{/}}: {r['means']}")
            for c in r["commands"]:
                L.append(f"       {{do}}{c}{{/}}")
        for x in r["notes"]:
            L.append(f"       {{note}}({x}){{/}}")
        for o in r.get("others", []):
            n += 1
            alts[n] = (k - 1, o["commands"])
            L.append(f"       {{note}}or {n}) {o['intent']}: {'; '.join(o['commands'])}{{/}}")
        if debug:
            L.append("       {note}scores: " + ", ".join(f"{i} {s}" + (f" (needs {','.join(m)})" if m else "")
                                                for i, s, m in r.get("ranked", [])[:8]) + "{/}")
    return L, alts


def _need_hint(r: dict) -> str:
    ex = {"prop": "name the props, e.g. 'the arches'", "words": "put the sung words in quotes, e.g. 'star'",
          "time": "give the moment, e.g. 'at 1:05' or '@star' (where 'star' is sung)",
          "grow": "say by how much, e.g. 'by 2 bars', 'by 4 beats', 'by 3 s'",
          "shrink": "say by how much, e.g. 'by 2 bars', 'by 4 beats', 'by 3 s'", "where": "name a part this song has ('sections' lists them)", "effect": "name the effect ('effects' lists them)",
          "split_vocals": "the singing start isn't known - 'lyrics import' or a time, e.g. 'at 0:23.5'",
          "before_vocals": "the singing start isn't known - 'lyrics import' or a time, e.g. 'at 0:23.5'"}
    return "{note}- " + "; ".join(ex.get(m, m) for m in r["missing"]) + "{/}"


def run_commands(cmds: list[str]) -> int:
    from ..__main__ import discover, dispatch
    from .batch_cmd import NOT_IN_BATCH
    import shlex
    solo = [c for c in cmds if shlex.split(c)[0] in NOT_IN_BATCH]
    if solo:
        rc = 0
        for c in cmds:                                   # undo and the like: on their own, in order
            print(f"{{note}}>{{/}} {{do}}{c}{{/}}")
            rc = dispatch(shlex.split(c), discover()) or rc
        return rc
    if len(cmds) == 1:
        print(f"{{note}}>{{/}} {{do}}{cmds[0]}{{/}}")
        return dispatch(shlex.split(cmds[0]), discover())
    from . import batch_cmd
    return batch_cmd.main(["; ".join(cmds)])


def evaluate(files: list[Path], ctx: D.Ctx, pr: dict, as_json: bool) -> int:
    cases = []
    for f in files:
        for ln in f.read_text(encoding="utf-8").splitlines():
            if not ln.strip() or ln.lstrip().startswith("#"):
                continue
            if "=>" not in ln:
                warn(f"{f.name}: '{ln.strip()}' has no '=>' - each line: TEXT => CMD; CMD")
                continue
            text, want = ln.split("=>", 1)
            cases.append((text.strip(), [w.strip() for w in want.split(";") if w.strip()]))
    if not cases:
        raise SystemExit("direct --eval: no cases - each line: TEXT => CMD; CMD, e.g. "
                         "'make the chorus bigger => feel intensity 0.8 @#2'")
    out, same = [], 0
    for text, want in cases:
        got = [c for r in D.interpret(D.corrections(text, ctx, pr)["text"], ctx, pr) for c in r["commands"]]
        ok = sorted(map(D.normal, got)) == sorted(map(D.normal, want))
        same += ok
        out.append({"text": text, "want": want, "got": got, "same": ok})
    if as_json:
        print(json.dumps({"cases": out, "same": same, "of": len(out)}, indent=2))
        return 0
    for c in out:
        if c["same"]:
            print(f"{{ok}}same{{/}}     {c['text']}")
        else:
            print(f"{{warn}}differs{{/}}  {c['text']}\n           want: {'; '.join(c['want']) or '-'}\n"
                  f"           got:  {'; '.join(c['got']) or '(not understood)'}")
    print(f"{same} of {len(out)} the same ({100 * same // len(out)}%)"
          + ("" if same == len(out) else " - a phrase to add goes in seqtool-prefs/intents.json "
             "('direct --list' shows them; --debug the scores)"))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool direct", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("words", nargs="*", help="what you want, in plain words")
    ap.add_argument("--yes", "-y", action="store_true", help="run it without asking")
    ap.add_argument("--dry-run", action="store_true", help="show what it would do, change nothing")
    ap.add_argument("--json", action="store_true", help="what it understood, as JSON (changes nothing)")
    ap.add_argument("--list", action="store_true", help="what it understands")
    ap.add_argument("--eval", nargs="+", metavar="FILE", help="cases 'TEXT => CMD; CMD': which come out the same")
    ap.add_argument("--debug", action="store_true", help="show every intent's score")
    a = ap.parse_args(argv)
    pr = prefs()
    if a.list:
        print("{head}direct{/} understands (preferences/intents.json; your own: seqtool-prefs/intents.json):")
        for iid, it in pr["intents"].items():
            says = ", ".join(f"'{x}'" for x in it.get("say", [])[:5] if x != "{effect}")
            print(f"  {{head}}{iid:<18}{{/}} {it.get('means', '')}\n  {'':<18} {{note}}{says} ...  -> "
                  f"{'; '.join(it.get('do', []))}{{/}}")
        return 0
    ctx = build_ctx()
    if a.eval:
        from glob import glob
        import os
        files = [Path(h) for pat in a.eval for h in (sorted(glob(os.path.expanduser(pat))) or [pat])]
        bad = [f for f in files if not f.is_file()]
        if bad:
            raise SystemExit(f"direct --eval: no such file {bad[0]} - e.g. 'direct --eval cases.txt'")
        return evaluate(files, ctx, pr, a.json)
    text = " ".join(a.words).strip()
    if not text:
        raise SystemExit('direct: say what you want - e.g. direct "make the chorus bigger" (direct --list: what it understands)')
    fix = D.corrections(text, ctx, pr)
    asked = not a.yes and not a.json and not a.dry_run
    from ..common import prompt
    for w, best, sim in fix["unsure"]:                 # not close enough to take by itself: ask
        if asked and prompt.interactive() and best:
            ans = prompt.ask(f"'{w}' isn't a word direct knows - is it '{best}'? [Y/n, or the right word]", "y",
                             show_default=False).strip()
            if ans.lower() in ("", "y", "yes"):
                fix["near"].append((w, best, sim))
                fix["text"] = re.sub(rf"(?<![\w@]){re.escape(w)}(?!\w)", best, fix["text"], count=1)
            elif ans.lower() not in ("n", "no"):
                fix["near"].append((w, ans, 1.0))
                fix["text"] = re.sub(rf"(?<![\w@]){re.escape(w)}(?!\w)", ans, fix["text"], count=1)
    text = fix["text"]
    res = D.interpret(text, ctx, pr)
    if fix["near"]:
        res[0].setdefault("notes", []).insert(0, "read " + ", ".join(f"'{w}' as '{b}'" for w, b, _ in fix["near"]))
    left = [(w, b) for w, b, _ in fix["unsure"] if not any(w == n[0] for n in fix["near"])]
    if left:
        res[0].setdefault("notes", []).insert(0, "not sure about " + ", ".join(
            f"'{w}'" + (f" (the most likely: '{b}')" if b else "") for w, b in left)
            + " - say it again with the word put right")
    if a.json:
        print(json.dumps({"text": text, "clauses": res, "commands": [c for r in res for c in r["commands"]]}, indent=2))
        return 0
    lines, alts = show(res, a.debug)
    print(f"{{head}}direct{{/}}: understood as")
    print("\n".join(lines))
    cmds_by = [list(r["commands"]) if not r["missing"] else [] for r in res]
    if not any(cmds_by):
        print("{note}nothing to run - 'direct --list' shows what it understands; e.g. direct \"make the chorus bigger\"; "
              "for anything else ask Claude (the seqtool-direction skill) or use the commands ('help'){/}")
        return 1
    if a.dry_run:
        print("{note}(dry run: nothing changed - without --dry-run it asks, then runs it){/}")
        return 0
    if not a.yes:
        from ..common import prompt
        if not prompt.interactive():
            print(f"{{note}}(not run: no one to confirm it - add --yes, e.g. direct --yes \"{text}\"){{/}}")
            return 0
        q = "run it? [Y/n]" + (f"  (or the number of another reading: {', '.join(map(str, alts))})" if alts else "")
        ans = prompt.ask(q, "y", show_default=False).strip().lower()
        if ans in ("n", "no", "q"):
            info("not run")
            return 0
        for w in ans.replace(",", " ").split():
            if w.isdigit() and int(w) in alts:
                k, cmds = alts[int(w)]
                cmds_by[k] = list(cmds)
    cmds = [c for cs in cmds_by for c in cs]
    if not cmds:
        return 0
    rc = run_commands(cmds)
    if rc:
        warn("it didn't work - see above; nothing of it is kept ('direct --dry-run' shows the commands)")
        return rc
    checks = list(dict.fromkeys(c for r, cs in zip(res, cmds_by) if cs for c in r["check"]))
    if checks:
        from ..__main__ import discover, dispatch
        import shlex
        for c in checks:
            print(f"{{head}}check:{{/}} {{do}}{c}{{/}}")
            dispatch(shlex.split(c), discover())
    good("done - 'undo' takes it all back")
    return 0


if __name__ == "__main__":
    sys.exit(main())
