"""Temporal continuity as a global optimisation (Viterbi), not a greedy loop.

For one target we choose an effect per window maximising

    sum_t static[t][k_t]  +  sum_t transition(k_{t-1} -> k_t, window t)

transition(j -> j)  = +persistence_bonus
transition(j -> k)  = -change_penalty * inertia(j) * family_factor
                        * (1 - transition_relief * transition_strength(t))

Hysteresis falls out naturally: a challenger must beat the incumbent by more
than the change cost, and that cost collapses at strong section boundaries.
Ties break on effect order, so results are deterministic.
"""
from __future__ import annotations


def transition_value(prev: str, cur: str, fam: dict[str, str], inertia: dict[str, float],
                     ts: float, cfg: dict) -> float:
    if prev == cur:
        return cfg["persistence_bonus"]
    factor = cfg["same_family_factor"] if fam[prev] == fam[cur] else 1.0
    relief = max(0.0, 1.0 - cfg["transition_relief"] * ts)
    return -cfg["change_penalty"] * inertia.get(prev, 0.7) * factor * relief


def viterbi(static: list[dict[str, float]], effects: list[str], fam: dict[str, str],
            inertia: dict[str, float], ts: list[float], cfg: dict) -> list[str]:
    if not static:
        return []
    best = {k: static[0][k] for k in effects}
    back: list[dict[str, str]] = []
    for t in range(1, len(static)):
        nxt, bp = {}, {}
        for k in effects:
            cand_val, cand_prev = None, None
            for j in effects:           # effects order = deterministic tie-break
                v = best[j] + transition_value(j, k, fam, inertia, ts[t], cfg)
                if cand_val is None or v > cand_val + 1e-12:
                    cand_val, cand_prev = v, j
            nxt[k] = cand_val + static[t][k]
            bp[k] = cand_prev
        best = nxt
        back.append(bp)
    last = max(effects, key=lambda k: (best[k], -effects.index(k)))
    path = [last]
    for bp in reversed(back):
        path.append(bp[path[-1]])
    return path[::-1]
