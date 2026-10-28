"""Stale-artifact detection and the reuse / rebuild / ask policy.

An artifact is stale when any of these no longer hold:
  * it was produced by this tool's MAJOR.MINOR version (VERSION file)
  * the source files it derives from (lineage: audio, layout, preferences)
    still have the same sha256
  * the intermediate files it was built from still have the same content hash
  * the settings it was built with (e.g. frame_interval) still match

Policy (global --stale=... or SEQTOOL_STALE):
  ask     - prompt to rebuild on a terminal; rebuild when non-interactive (default)
  rebuild - always rebuild stale artifacts
  warn    - warn and reuse them anyway
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .. import __version__
from .canonical import content_sha256, read_json
from .log import info, warn

_mode = os.environ.get("SEQTOOL_STALE", "ask")


def set_mode(mode: str) -> None:
    global _mode
    if mode not in ("ask", "rebuild", "warn"):
        raise ValueError(f"--stale must be ask, rebuild or warn (got {mode!r})")
    _mode = mode


def _mm(v: str) -> tuple[int, int]:
    parts = (v.split(".") + ["0", "0"])[:2]
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return (-1, -1)


def reasons(doc: dict, *, lineage: dict[str, str] | None = None,
            inputs: dict[str, dict] | None = None, settings: dict | None = None,
            check=None) -> list[str]:
    """Return why `doc` is stale (empty list = fresh).

    lineage  : {name: current sha256 of the original source file}
    inputs   : {source key: current input document} - compared by content hash
    settings : {dotted.path.in.doc: expected value}
    check    : optional function(doc) -> [reasons], for derived files the artifact
               depends on (e.g. the vocal stem a music.json was measured from)
    """
    out = []
    made = doc.get("producer", {}).get("version", "0")
    if _mm(made) != _mm(__version__):
        out.append(made)                                   # e.g. "0.4.0"
    for name, sha in (lineage or {}).items():
        have = doc.get("lineage", {}).get(name)
        if have != sha:
            out.append(f"{name} changed" if have else f"no {name} record")
    for key, cur in (inputs or {}).items():
        ref = doc.get("source", {}).get(key, {})
        if ref.get("content_sha256") != content_sha256(cur):
            out.append(f"{key.replace('_', '-')}.json changed")
    for path, want in (settings or {}).items():
        node = doc
        for p in path.split("."):
            node = node.get(p) if isinstance(node, dict) else None
        if node != want:
            name = path.split(".")[-1]
            if name in ("edits", "lyrics"):                # checksums: say what changed, not the hashes
                out.append({"edits": "your section edits", "lyrics": "the lyrics"}[name] + " changed")
            else:
                out.append(f"{name} {node} -> {want}")
    if check is not None:
        out += check(doc)
    return out


def decide(path: Path, why: list[str]) -> bool:
    """True = rebuild. Reports the reasons either way."""
    if not why:
        return False
    warn(f"{path.name} is stale ({'; '.join(why)})")
    if _mode == "warn":
        info(f"  reusing it anyway (--stale=warn)")
        return False
    if _mode == "ask":
        from .prompt import ask
        if ask(f"  rebuild {path.name}? [Y/n]", "y", show_default=False).lower() in ("n", "no"):
            return False
    return True


def load_if_fresh(path: Path, note=None, **expect) -> dict | None:
    """Return the cached artifact when it is fresh (or the policy keeps it), else None.
    note: optional function(doc) -> text added to the 'reusing' line."""
    if not path.exists():
        return None
    try:
        doc = read_json(path)
    except Exception as e:  # unreadable cache = rebuild
        warn(f"{path.name} unreadable ({e}); rebuilding")
        return None
    if decide(path, reasons(doc, **expect)):
        return None
    extra = note(doc) if note else ""
    info(f"  reusing {path.name}" + (f"  ({extra})" if extra else ""))
    return doc


def check_inputs(consumer: str, **pairs: tuple[dict, dict | None]) -> list[str]:
    """For single-stage commands: warn when an input was built from a different
    upstream file than the one supplied, or by an older tool version.
    pairs: name=(doc, upstream_doc_or_None) where doc.source[name_of_upstream]..."""
    msgs = []
    for name, (doc, _) in pairs.items():
        made = doc.get("producer", {}).get("version", "0")
        if _mm(made) != _mm(__version__):
            msgs.append(f"{name} is stale ({made})")
    for m in msgs:
        warn(f"{consumer}: {m} - 'run' rebuilds stale files")
    return msgs


def consistency(doc: dict, key: str, upstream: dict, consumer: str) -> bool:
    ref = doc.get("source", {}).get(key)
    if ref and ref.get("content_sha256") != content_sha256(upstream):
        warn(f"{consumer}: {doc['schema'].split('.')[-1]} doesn't match this {key.replace('_', '-')} "
             "(stale or mismatched files)")
        return False
    return True
