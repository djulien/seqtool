# seqtool-command: layout | main | setup | ingest the show layout once (xlights_rgbeffects.xml); show it
# seqtool-inspect: layout | inspect_layout | the ingested show layout: source file, dates, models, groups
"""The show layout, ingested once.

    seqtool layout path/to/xlights_rgbeffects.xml    ingest (or re-ingest) the show layout
    seqtool layout ~/xLights/OtherShow               use another layout: the same command with the
                                                     other show folder (or its xlights_rgbeffects.xml)
                                                     replaces the stored one
    seqtool layout                                   show what is stored
    seqtool layout --forget                          clear it: seqtool has no layout until the next
                                                     'layout PATH' (the old copy is kept aside, in
                                                     seqtool-prefs/layout-forgotten-DATE/)

Your group roles, rules, pins and other preferences are not part of the stored layout:
they stay in seqtool-prefs/ and apply by name to whichever layout is stored ('pref
changed' lists them). Songs planned with the old layout are planned again on their
next run.

The imported layout and its model analysis are kept in
seqtool-prefs/layout/ together with the source file's path and checksum.
Later runs use them directly; if the source file has changed since, the
layout is reported stale and re-ingested according to --stale.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from ..common import config, freshness
from ..common.canonical import content_sha256, file_sha256, read_json, write_json
from ..common.log import good, info, warn
from ..common.paths import show
from ..common.paths import arg as paths_arg

def find_rgbeffects(path: Path) -> Path:
    """Accept the file itself or the show folder that contains it."""
    if path.is_dir():
        f = path / "xlights_rgbeffects.xml"
        if not f.exists():
            raise SystemExit(f"no xlights_rgbeffects.xml in {path} - give the show folder, e.g. 'layout ~/xLights/show'")
        return f
    if not path.exists():
        raise SystemExit(f"no such file or folder: {path} - e.g. 'layout ~/xLights/show' (globs ok)")
    return path


def folder() -> Path:
    return config.user_dir() / "layout"


def source_info() -> dict | None:
    f = folder() / "source.json"
    return read_json(f) if f.exists() else None


def added_props() -> list[dict]:
    """Props added to the stored layout with prop-wizard (not in xlights_rgbeffects.xml)."""
    f = folder() / "layout.json"
    try:
        return [p for p in read_json(f)["props"] if (p.get("origin") or {}).get("adapter") == "wizard"] \
            if f.exists() else []
    except Exception:  # noqa: BLE001
        return []


def review_shadow_followers(lay: dict, pref_dir: Path | None = None) -> bool:
    """Models whose start channel follows a shadow model: ask whether each is a shadow model
    too (the user's rule, 0.20.3), remember the answers. True when something changed."""
    todo = (lay.get("import_report") or {}).get("shadow_followers") or []
    if not todo:
        return False
    from ..common.prompt import ask, interactive
    if not interactive():
        names = ", ".join(x["model"] for x in todo[:4]) + (" ..." if len(todo) > 4 else "")
        warn(f"{len(todo)} model(s) start right after a shadow model ({names}) - planned for now; to treat one "
             f"as a shadow model too: 'pref xlights/shadow_followers/{todo[0]['model']} = true'")
        return False
    answers = {}
    for x in todo:
        a = ask(f"{x['model']} starts right after shadow model {x['shadow']} (start channel '{x['start']}'): "
                f"treat it as a shadow model too (left out, like {x['shadow']})? [Y/n]", "y", show_default=False)
        answers[x["model"]] = a.lower() not in ("n", "no")
    config.update("xlights", {"shadow_followers": answers}, pref_dir)
    good(f"remembered for {len(answers)} model(s) ('pref xlights.shadow_followers' shows them)")
    return any(answers.values())


def ingest(rgbeffects: Path, pref_dir: Path | None = None, keep_added: bool | None = None) -> tuple[dict, dict]:
    from ..adapters.xlights.import_layout import import_layout, review_overlaps
    from ..models.analyze import analyze as analyze_models
    extra = added_props()
    if extra and keep_added is None:                 # the user's rule (0.20.2): say before they go
        from ..common.prompt import ask
        names = ", ".join(p["id"] for p in extra[:5]) + (" ..." if len(extra) > 5 else "")
        warn(f"reading {rgbeffects.name} replaces the stored layout: {len(extra)} prop(s) you added with "
             f"prop-wizard ({names}) are not in it")
        keep_added = ask("keep them? [Y/n]  (n: they are dropped - add them in xLights to have them there)", "y",
                         show_default=False).lower() not in ("n", "no")
    lay = import_layout(rgbeffects, pref_dir)
    if review_overlaps(lay, pref_dir):
        lay = import_layout(rgbeffects, pref_dir)
    if review_shadow_followers(lay, pref_dir):
        lay = import_layout(rgbeffects, pref_dir)
    if extra and keep_added:
        have = {p["id"] for p in lay["props"]}
        kept = [p for p in extra if p["id"] not in have]
        lay["props"] += kept
        if len(kept) < len(extra):
            info(f"  {len(extra) - len(kept)} added prop(s) are now in xLights too - the xLights one is used")
        info(f"  kept {len(kept)} prop(s) added with prop-wizard")
    models = analyze_models(lay, "layout.json")
    d = folder()
    d.mkdir(parents=True, exist_ok=True)
    write_json(d / "layout.json", lay)
    write_json(d / "layout.models.json", models)
    st = rgbeffects.stat()
    (d / "source.json").write_text(json.dumps({
        "path": str(rgbeffects.resolve()), "sha256": file_sha256(rgbeffects),
        "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
        "ingested": time.strftime("%Y-%m-%d %H:%M"),
        "xlights_prefs_sha256": content_sha256(config.load("xlights", pref_dir)),
        "networks_sha256": _networks_sha(rgbeffects)}, indent=2) + "\n")
    return lay, models


def _networks_sha(rgbeffects: Path) -> str | None:
    """xlights_networks.xml beside the layout (0.24.32: it gives the absolute channels)."""
    from ..adapters.xlights.import_layout import NETWORKS_FILE
    f = Path(rgbeffects).parent / NETWORKS_FILE
    return file_sha256(f) if f.is_file() else None


def stale_reasons(pref_dir: Path | None = None) -> list[str] | None:
    """Why the stored layout is stale ([] = fresh, None = none stored); changes nothing."""
    src = source_info()
    if src is None:
        return None
    d = folder()
    path = Path(src["path"])
    why = []
    if path.exists() and file_sha256(path) != src["sha256"]:
        why.append(f"{path.name} changed")
    cur = _networks_sha(path) if path.exists() else src.get("networks_sha256")
    if cur != src.get("networks_sha256"):
        why.append("xlights_networks.xml changed" if src.get("networks_sha256") and cur else
                   "xlights_networks.xml not read yet (absolute channels)" if cur else "xlights_networks.xml is gone")
    if content_sha256(config.load("xlights", pref_dir)) != src.get("xlights_prefs_sha256"):
        why.append("xLights preferences changed")
    try:
        lay_doc = read_json(d / "layout.json")
        models = read_json(d / "layout.models.json")
    except Exception:  # noqa: BLE001
        return why + ["the stored copy is unreadable"]
    why += [w for w in freshness.reasons(lay_doc) if w not in why]
    why += [w for w in freshness.reasons(models, inputs={"layout": lay_doc}) if w not in why]
    from ..models.analyze import outdated
    why += [w for w in outdated(models) if w not in why]
    return why


def current(pref_dir: Path | None = None) -> tuple[dict, dict] | None:
    """The stored layout + models, re-ingested first if the source file or the
    xLights preferences changed (subject to the --stale policy)."""
    src = source_info()
    if src is None:
        return None
    d = folder()
    path = Path(src["path"])
    why = stale_reasons(pref_dir) or []
    lay_doc = read_json(d / "layout.json")
    models = read_json(d / "layout.models.json")
    if why and path.exists() and freshness.decide(d / "layout.json", why):
        info(f"  re-ingesting {show(path)}")
        return ingest(path, pref_dir, keep_added=True)   # props added with prop-wizard stay
    if not path.exists():
        warn(f"layout source {path} no longer exists; using the stored copy ('layout NEW/PATH' stores another)")
    return lay_doc, models


def describe() -> list[str]:
    src = source_info()
    if src is None:
        return ["no layout ingested yet - run: seqtool layout path/to/xlights_rgbeffects.xml"]
    lay = read_json(folder() / "layout.json")
    rep = lay.get("import_report", {})
    path = Path(src["path"])
    changed = path.exists() and file_sha256(path) != src["sha256"]
    kinds = ", ".join(f"{n} {k}" for k, n in rep.get("group_kinds", {}).items() if n)
    return [f"source:   {show(path)}" + ("  (CHANGED since ingest)" if changed else ""),
            f"modified: {src['modified']}   ingested: {src['ingested']}",
            f"models:   {rep.get('models', len(lay['props']))} ({rep.get('controllable', '?')} usable)"
            "   {note}('models' lists them, 'models --unused' the others and why){/}",
            f"groups:   {rep.get('groups', len(lay['groups']))} ({kinds})   {{note}}('groups' lists them){{/}}",
            f"default view: {lay.get('default_view', '-')}"] + _controllers_line(lay)


def _controllers_line(lay: dict) -> list[str]:
    cs = (lay.get("adapter") or {}).get("xlights", {}).get("controllers")
    if not cs:
        return ["controllers: {note}no xlights_networks.xml beside the layout - 'models' shows controller "
                "channels only (absolute ones, for fseqdump, need that file){/}"]
    tot = sum(c["channels"] for c in cs)
    inact = sum(not c["active"] for c in cs)
    ends = [int(p["origin"]["absolute"].split("-")[1]) for p in lay.get("props", [])
            if (p.get("origin") or {}).get("absolute")]
    top = max([tot] + ends)
    more = f"; props without a controller after them, up to {top}" if top > tot else ""
    return [f"controllers: {len(cs)}" + (f" ({inact} inactive)" if inact else "") + f", channels 1-{tot}{more} "
            f"{{note}}(from xlights_networks.xml; an .fseq of this show holds {top} channels - "
            "'models PROP' shows a prop's absolute channels){/}"]


def inspect_layout(args) -> list[str]:
    return describe()


def lay_is_xlights(d) -> bool:
    from ..common.canonical import read_json
    f = d / "layout.json"
    try:
        return f.exists() and read_json(f).get("units") == "xlights"
    except Exception:  # noqa: BLE001
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool layout", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rgbeffects", nargs="?", type=paths_arg, help="xlights_rgbeffects.xml, or the show folder containing it")
    ap.add_argument("--preferences", type=paths_arg, default=None)
    ap.add_argument("--forget", action="store_true", help="clear the stored layout (kept aside, not deleted)")
    a = ap.parse_args(argv)
    if a.forget:
        if source_info() is None and not folder().exists():
            print("no layout stored - 'layout PATH' stores one (e.g. 'layout ~/xLights/show')")
            return 0
        old = folder().with_name("layout-forgotten-" + time.strftime("%Y%m%d-%H%M%S"))
        folder().rename(old)
        good(f"forgot the stored layout (kept aside in {show(old)}) - 'layout PATH' stores another, "
             "e.g. 'layout ~/xLights/show'")
        return 0
    if a.rgbeffects:
        a.rgbeffects = find_rgbeffects(a.rgbeffects)
        ingest(a.rgbeffects, a.preferences)
        good(f"layout stored in {show(folder())}")
        try:
            from ..adapters.xlights import kit
            if lay_is_xlights(folder()):
                kit.offer("first export")
        except Exception:  # noqa: BLE001
            pass
    elif (stale_reasons() or []) and Path(source_info()["path"]).exists():
        current()                                    # stale: re-ingested now (as --stale says), then shown
    for line in describe():
        print(line)
    from ..common.prefcmd import uses
    from .groups import LAYOUT_PREFS
    for ln in uses(*LAYOUT_PREFS):
        print(ln)
    return 0


if __name__ == "__main__":
    sys.exit(main())
