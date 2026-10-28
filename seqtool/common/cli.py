# seqtool-command: check | main | stages | schema-validate seqtool JSON files
"""seqtool-check FILE... : validate interchange files against their schemas."""
from __future__ import annotations

import argparse
import sys

from .canonical import read_json
from .envelope import SchemaVersionError, check_version
from .schemas import ValidationError, validate


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool-check", description=__doc__)
    ap.add_argument("files", nargs="+")
    args = ap.parse_args(argv)
    bad = 0
    for f in args.files:
        try:
            doc = read_json(f)
            check_version(doc, doc.get("schema", "?"))
            validate(doc)
            print(f"OK    {f}  ({doc['schema']} {doc['schema_version']})")
        except (ValidationError, SchemaVersionError, ValueError, KeyError) as e:
            bad += 1
            print(f"FAIL  {f}\n  " + str(e).replace("\n", "\n  "))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
