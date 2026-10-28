"""Schema loading and validation.

Uses the `jsonschema` package (MIT) when installed; otherwise falls back to a
small built-in validator covering the subset of Draft 2020-12 the seqtool schemas
use: type, required, properties, additionalProperties, items, enum, const,
minimum, maximum, minItems, pattern, $ref (local and cross-file by $id), anyOf.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"
FILES = {
    "seqtool.music": "music-1.schema.json",
    "seqtool.music-profile": "music-profile-1.schema.json",
    "seqtool.models": "models-1.schema.json",
    "seqtool.matchup": "matchup-1.schema.json",
    "seqtool.validation": "validation-1.schema.json",
    "seqtool.layout": "layout-1.schema.json",
}


class ValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("\n".join(errors[:20]) + ("\n..." if len(errors) > 20 else ""))
        self.errors = errors


@lru_cache(maxsize=None)
def _registry() -> dict[str, dict]:
    reg = {}
    for p in sorted(SCHEMA_DIR.glob("*.schema.json")):
        s = json.loads(p.read_text(encoding="utf-8"))
        reg[s["$id"]] = s
    return reg


def load_schema(schema_name: str) -> dict:
    return json.loads((SCHEMA_DIR / FILES[schema_name]).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- fallback --
_TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool, "null": type(None),
}


def _is_type(v: Any, t: str) -> bool:
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return isinstance(v, _TYPES[t])


def _resolve(ref: str, root: dict) -> tuple[dict, dict]:
    base, _, frag = ref.partition("#")
    doc = _registry()[base] if base else root
    node = doc
    for part in [p for p in frag.split("/") if p]:
        node = node[part]
    return node, doc


def _check(v: Any, s: dict, root: dict, path: str, errs: list[str]) -> None:
    if "$ref" in s:
        target, troot = _resolve(s["$ref"], root)
        _check(v, target, troot, path, errs)
    if "anyOf" in s:
        if not any(not _collect(v, sub, root, path) for sub in s["anyOf"]):
            errs.append(f"{path}: does not match any allowed form")
    if "type" in s:
        ts = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(_is_type(v, t) for t in ts):
            errs.append(f"{path}: expected {'/'.join(ts)}, got {type(v).__name__}")
            return
    if "const" in s and v != s["const"]:
        errs.append(f"{path}: must equal {s['const']!r}")
    if "enum" in s and v not in s["enum"]:
        errs.append(f"{path}: {v!r} not in {s['enum']}")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "minimum" in s and v < s["minimum"]:
            errs.append(f"{path}: {v} < minimum {s['minimum']}")
        if "maximum" in s and v > s["maximum"]:
            errs.append(f"{path}: {v} > maximum {s['maximum']}")
    if isinstance(v, str) and "pattern" in s and not re.search(s["pattern"], v):
        errs.append(f"{path}: {v!r} does not match {s['pattern']}")
    if isinstance(v, dict):
        for r in s.get("required", []):
            if r not in v:
                errs.append(f"{path}: missing required field {r!r}")
        props = s.get("properties", {})
        addl = s.get("additionalProperties", True)
        for k, sub in v.items():
            if k in props:
                _check(sub, props[k], root, f"{path}.{k}", errs)
            elif isinstance(addl, dict):
                _check(sub, addl, root, f"{path}.{k}", errs)
            elif addl is False:
                errs.append(f"{path}: unexpected field {k!r}")
    if isinstance(v, list):
        if "minItems" in s and len(v) < s["minItems"]:
            errs.append(f"{path}: needs at least {s['minItems']} items")
        if "items" in s:
            for i, item in enumerate(v):
                _check(item, s["items"], root, f"{path}[{i}]", errs)


def _collect(v, s, root, path) -> list[str]:
    e: list[str] = []
    _check(v, s, root, path, e)
    return e


def validate(doc: dict, schema_name: str | None = None) -> None:
    """Raise ValidationError if doc does not conform to its schema."""
    name = schema_name or doc.get("schema")
    if name not in FILES:
        raise ValidationError([f"unknown schema {name!r}"])
    schema = load_schema(name)
    try:
        import jsonschema  # type: ignore
        from referencing import Registry, Resource  # type: ignore
        reg = Registry().with_resources(
            (sid, Resource.from_contents(s)) for sid, s in _registry().items())
        v = jsonschema.Draft202012Validator(schema, registry=reg)
        errs = [f"$.{'.'.join(map(str, e.absolute_path))}: {e.message}"
                for e in sorted(v.iter_errors(doc), key=lambda e: list(map(str, e.path)))]
    except ImportError:
        errs = _collect(doc, schema, schema, "$")
    if errs:
        raise ValidationError(errs)
