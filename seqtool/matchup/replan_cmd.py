# seqtool-command: replan | main | refine | make the plan again now (after changes made with --later): replan
"""seqtool replan [--if-pending]

Makes the plan again from your settings, as every change command does by itself (0.24.39).
Changes given '--later' (e.g. 'cue add @1:05 --later' - the GUI does that for cues tapped while
the song plays) only record the setting; 'replan' then makes the plan once for all of them.
The GUI runs it by itself a few seconds after the last such change (gui.replan_after).

    replan                 make it now
    replan --if-pending    only when a --later change is waiting for it
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..common import config
from ..common.log import good, info


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool replan", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--if-pending", action="store_true", help="only when a --later change waits for it")
    a = ap.parse_args(argv)
    if a.if_pending and not config.answer("replan_pending"):
        info("nothing waiting for a new plan")
        return 0
    from . import reroll
    from ..common.canonical import read_json
    old = None
    try:
        _, old_m, profile, _ = reroll._context()
        old = (old_m, profile)
    except SystemExit:
        pass
    reroll.rerun()
    config.remember("replan_pending", False)
    if old:
        new_m = read_json(Path(config.answer("last_matchup")))
        lines = reroll.diff(reroll.plan_columns(old[0], old[1]), reroll.plan_columns(new_m, old[1]), old[1])
        print("\n".join(lines) if lines else "  (no visible change)")
    good("the plan is made again")
    return 0


if __name__ == "__main__":
    sys.exit(main())
