# seqtool-command: prefer | main | refine | effects a prop or group likes or avoids: prefer Arches twinkle=like fire=avoid | prefer Arches
"""seqtool prefer TARGET [EFFECT=like|avoid|neutral ...]

What a prop or group should get more often (like) or rarely (avoid) - for every song.
The GUI's layout panel sets these with its effect wheel (0.21.8).

    prefer Arches                      what Arches likes and avoids now
    prefer Arches twinkle=like         chosen more often (score x1.6)
    prefer Arches fire=avoid chase=avoid
                                       chosen rarely (x0.3) - 'dark' or a pin still forces anything
    prefer Arches twinkle=neutral      back to normal
    prefer Arches twinkle=1.3          a weight: 1 = neutral, 2 = twice as likely, 0.5 = half (0.05-3)

They are kept in models.json targets.TARGET.effect_preferences (any number there works
too: 'pref models/targets/Arches/effect_preferences/twinkle = 1.2'); name rules
('rules add ... prefer=') do the same for every name a pattern matches.
"""
from __future__ import annotations

import argparse
import sys

from ..common import config
from ..common.log import good, info
from ..common.vocab import canon

LEVELS = {"like": 1.6, "avoid": 0.3}


def word(v) -> str:
    if v is None or v == 1:
        return "neutral"
    return "like" if v > 1 else "avoid"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool prefer", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target")
    ap.add_argument("choices", nargs="*", metavar="EFFECT=like|avoid|neutral")
    a = ap.parse_args(argv)
    from .react_cmd import _song_layout_ids
    from ..layout import store
    cur = store.current()
    ids = ([m["id"] for m in cur[1]["models"]] if cur else []) + _song_layout_ids()
    name = next((i for i in ids if i.lower() == a.target.lower()), None)
    if ids and name is None:
        from ..common.suggest import suggest
        raise SystemExit(f"no prop or group '{a.target}'" + suggest(a.target, ids) + " - 'models' / 'groups' list them")
    name = name or a.target
    effects = config.load("effects")["effects"]
    ep = dict(config.load("models").get("targets", {}).get(name, {}).get("effect_preferences") or {})
    if not a.choices:
        likes = [e for e, v in ep.items() if v > 1]
        avoids = [e for e, v in ep.items() if v < 1]
        print(f"{name}: likes {', '.join(likes) or 'nothing in particular'}; avoids {', '.join(avoids) or 'nothing'}")
        return 0
    said = []
    for c in a.choices:
        if "=" not in c:
            raise SystemExit(f"'{c}': EFFECT=like|avoid|neutral, e.g. 'prefer {name} twinkle=like'")
        e, lv = (x.strip() for x in c.split("=", 1))
        e = canon(e)
        if e not in effects:
            raise SystemExit(f"unknown effect '{e}' - 'effects' lists them")
        try:                                         # a weight (the GUI's wheel, 0.21.9): 1 = neutral
            num = float(lv)
        except ValueError:
            num = None
        if num is not None:
            if not 0.05 <= num <= 3:
                raise SystemExit(f"'{lv}': a weight between 0.05 (almost never) and 3 (much more often); 1 = neutral")
            lv = "neutral" if abs(num - 1) < 0.03 else lv
        elif lv not in ("like", "avoid", "neutral"):
            raise SystemExit(f"'{lv}': like, avoid, neutral or a weight (0.05-3, 1 = neutral)")
        if lv == "neutral":
            config.unset("models", ["targets", name, "effect_preferences", e])
        else:
            config.update("models", {"targets": {name: {"effect_preferences": {e: LEVELS.get(lv) or round(float(lv), 2)}}}})
        said.append(f"{e} {lv}")
    good(f"{name}: " + ", ".join(said))
    info("run again to update the plan ('run' reuses the analysis)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
