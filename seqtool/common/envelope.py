"""Common envelope for every interchange file + version compatibility rules."""
from __future__ import annotations

import os
import time
from typing import Any

from .. import __version__

SCHEMAS = {
    "seqtool.music": "1.0",
    "seqtool.music-profile": "1.0",
    "seqtool.models": "1.0",
    "seqtool.matchup": "1.0",
    "seqtool.validation": "1.0",
    "seqtool.layout": "1.0",
}


class SchemaVersionError(ValueError):
    pass


def utc_now() -> str:
    # SOURCE_DATE_EPOCH gives byte-identical files for reproducibility tests.
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    t = int(epoch) if epoch else time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def envelope(schema: str, producer: str, source: dict[str, Any],
             lineage: dict[str, str] | None = None) -> dict[str, Any]:
    """lineage = sha256 of the ORIGINAL source data (audio, layout, preferences)
    this artifact ultimately derives from. Carried forward unchanged by every
    stage so any artifact can be checked against the files it came from."""
    doc = {
        "schema": schema,
        "schema_version": SCHEMAS[schema],
        "producer": {"name": producer, "version": __version__},
        "created_utc": utc_now(),
        "source": source,
    }
    if lineage:
        doc["lineage"] = dict(sorted(lineage.items()))
    return doc


def merge_lineage(*docs: dict, extra: dict[str, str] | None = None) -> dict[str, str]:
    out: dict[str, str] = {}
    for d in docs:
        for k, v in d.get("lineage", {}).items():
            if out.get(k, v) != v:
                raise SchemaVersionError(f"lineage conflict on {k!r}: inputs derive from different {k} files")
            out[k] = v
    out.update(extra or {})
    return out


def check_version(doc: dict[str, Any], expected_schema: str,
                  supported_majors: tuple[int, ...] = (1,)) -> None:
    """Accept any MINOR of a supported MAJOR; reject everything else loudly."""
    got = doc.get("schema")
    if got != expected_schema:
        raise SchemaVersionError(f"expected schema {expected_schema!r}, got {got!r}")
    ver = str(doc.get("schema_version", ""))
    try:
        major = int(ver.split(".")[0])
    except ValueError:
        raise SchemaVersionError(f"unparseable schema_version {ver!r}") from None
    if major not in supported_majors:
        raise SchemaVersionError(
            f"{expected_schema} major version {major} unsupported "
            f"(this tool supports {supported_majors})")
