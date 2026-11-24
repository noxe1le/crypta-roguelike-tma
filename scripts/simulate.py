"""Балансировка: прогон тысяч забегов разными политиками.

    python scripts/simulate.py 3000
"""

from __future__ import annotations

import collections
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game import engine  # noqa: E402


def tactical(state, ids):
    """Читает телеграф: под тяжёлый удар уходит в защиту, лечится на низком HP."""
    if state["phase"] == "combat":
        monster = state.get("monster") or {}
        intent = (monster.get("intent") or {}).get("kind")
        hp_ratio = state["hp"] / max(1, state["max_hp"])
        if hp_ratio < 0.35 and "potion" in ids:
            return "potion"
        if intent == "heavy" and "guard" in ids:
            return "guard"
        if intent == "charge":
            return "fight"
        return "fight"
    if state["phase"] == "shrine":
        if "shrine:offer" in ids and state["hp"] < state["max_hp"] * 0.8:
            return "shrine:offer"
        return "shrine:heal" if state["hp"] < state["max_hp"] * 0.7 else "shrine:power"
    if state["phase"] == "doors":
        return next(i for i in ids if i.startswith("door:"))
    return ids[0]


def smart(state, ids):
    if state["phase"] == "combat":
        if state["hp"] <= state["max_hp"] * 0.35 and "potion" in ids:
            return "potion"
        return "fight"
    if state["phase"] == "shrine":
        if "shrine:offer" in ids and state["hp"] < state["max_hp"] * 0.8:
            return "shrine:offer"
        return "shrine:heal" if state["hp"] < state["max_hp"] * 0.7 else "shrine:power"
    if state["phase"] == "doors":
        return next(i for i in ids if i.startswith("door:"))
    return ids[0]


def random_policy(state, ids):
    import random as _r
    return _r.choice(ids)


def reckless(state, ids):
    if state["phase"] == "combat":
        return "fight"
    return smart(state, ids)


def cautious(state, ids):
    if state["phase"] == "combat":
        if state["hp"] < state["max_hp"] * 0.55 and "potion" in ids:
            return "potion"
        if state["hp"] < state["max_hp"] * 0.2 and "flee" in ids:
            return "flee"
        return "fight"
    if state["phase"] == "shrine":
        return "shrine:heal" if state["hp"] < state["max_hp"] * 0.9 else "shrine:power"
    return smart(state, ids)


def run(policy, n: int) -> dict:
    wins = 0
    depths = []
    turns = []
    deaths = collections.Counter()
    for seed in range(n):
        st = engine.new_run(seed=seed)
        for _ in range(600):
            acts = engine.actions(st)
            if not acts:
                break
            engine.apply(st, policy(st, [a["id"] for a in acts]))
            if st["phase"] in ("dead", "won"):
                break
        depths.append(st["deepest"])
        turns.append(st["turns"])
        if st["phase"] == "won":
            wins += 1
        else:
            deaths[st["deepest"]] += 1
    return {
        "win": wins / n,
        "avg_depth": statistics.mean(depths),
        "median_depth": statistics.median(depths),
        "avg_turns": statistics.mean(turns),
        "deaths": deaths,
    }


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    for name, policy in (("tactical", tactical), ("smart", smart),
                         ("cautious", cautious), ("reckless", reckless),
                         ("random", random_policy)):
        r = run(policy, n)
        print(f"\n{name}: побед {r['win']:.1%} · средняя глубина {r['avg_depth']:.1f}"
              f" · медиана {r['median_depth']:.0f} · ходов {r['avg_turns']:.0f}")
        hot = ", ".join(f"э{f}:{c}" for f, c in sorted(r["deaths"].items()) if c)
        print(f"  смерти по этажам: {hot}")


if __name__ == "__main__":
    main()
