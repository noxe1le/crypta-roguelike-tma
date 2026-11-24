"""Тесты ядра: генерация, ходы, бой, финал."""

from __future__ import annotations

import random

import pytest

from game import content, engine, render


def play_out(seed: int, policy=None, limit: int = 500) -> dict:
    """Прогоняет забег до финала простой политикой."""
    state = engine.new_run(seed=seed)
    for _ in range(limit):
        acts = engine.actions(state)
        if not acts:
            break
        ids = [a["id"] for a in acts]
        action = policy(state, ids) if policy else random.choice(ids)
        assert action in ids, f"политика вернула недоступный ход {action} в {state['phase']}"
        engine.apply(state, action)
        if state["phase"] in ("dead", "won"):
            break
    return state


def smart_policy(state: dict, ids: list[str]) -> str:
    if state["phase"] == "combat":
        if state["hp"] <= state["max_hp"] * 0.35 and "potion" in ids:
            return "potion"
        return "fight"
    if state["phase"] == "shrine":
        return "shrine:heal" if state["hp"] < state["max_hp"] * 0.7 else "shrine:power"
    if state["phase"] == "doors":
        return next(i for i in ids if i.startswith("door:"))
    return ids[0]


def test_new_run_is_deterministic():
    a = engine.new_run(seed=42)
    b = engine.new_run(seed=42)
    assert a == b
    assert a["seed"] == 42
    assert len(a["doors"]) == 2


def test_different_seeds_differ():
    a = engine.new_run(seed=1)
    b = engine.new_run(seed=2)
    assert a["doors"] != b["doors"]


def test_doors_phase_has_two_choices():
    state = engine.new_run(seed=7)
    acts = engine.actions(state)
    assert state["phase"] == "doors"
    assert [a["id"] for a in acts] == ["door:0", "door:1"]
    assert all(a["label"] for a in acts)


def test_entering_room_advances_or_fights():
    state = engine.new_run(seed=7)
    engine.apply(state, "door:0")
    assert state["phase"] in ("room", "combat", "shrine", "dead")
    assert state["room"] is not None


def test_full_run_terminates():
    for seed in range(50):
        state = play_out(seed)
        assert state["phase"] in ("dead", "won"), f"забег {seed} не завершился"


def test_combat_damages_both_sides():
    for seed in range(200):
        state = engine.new_run(seed=seed)
        door = next((d for d in state["doors"] if d["kind"] == "monster"), None)
        if door:
            engine.apply(state, f"door:{door['id']}")
            break
    else:
        pytest.fail("ни на одном сиде нет монстра в первой комнате")
    hp_before = state["hp"]
    mhp_before = state["monster"]["hp"]
    events = engine.apply(state, "fight")
    missed = any(e["t"] == "miss" for e in events)
    if not missed:
        assert state["monster"] is None or state["monster"]["hp"] < mhp_before
    assert any(e["t"] in ("hit", "miss") for e in events)
    assert state["hp"] <= hp_before


def test_potion_heals_and_consumes():
    state = engine.new_run(seed=11)
    state["hp"] = 10
    state["phase"] = "combat"
    state["monster"] = {"name": "Тест", "emoji": "🐀", "hp": 99, "max_hp": 99,
                        "atk": 0, "gold": 0, "line": "", "boss": False}
    potions = state["potions"]
    engine.apply(state, "potion")
    assert state["potions"] == potions - 1
    assert state["hp"] > 10


def test_descend_increases_floor_and_heals():
    state = engine.new_run(seed=5)
    state["phase"] = "stairs"
    state["hp"] = 10
    engine.apply(state, "down")
    assert state["floor"] == 2
    assert state["hp"] == 10 + engine.DESCEND_HEAL
    assert state["node"] == 0
    assert state["phase"] == "doors"


def test_boss_room_on_last_floor():
    state = engine.new_run(seed=5)
    state["floor"] = engine.MAX_FLOOR
    state["node"] = engine.NODES_PER_FLOOR - 1
    state["phase"] = "doors"
    engine._open_doors(state)
    assert all(d["kind"] == "boss" for d in state["doors"])
    assert all(d["hint"] in content.BOSS_HINTS for d in state["doors"])
    assert state["doors"][0]["hint"] != state["doors"][1]["hint"]


def test_no_flee_from_boss():
    state = engine.new_run(seed=5)
    state["phase"] = "combat"
    state["monster"] = {"name": "Король Крипты", "emoji": "👑", "hp": 10, "max_hp": 10,
                        "atk": 5, "gold": 100, "line": "", "boss": True}
    ids = [a["id"] for a in engine.actions(state)]
    assert "flee" not in ids
    assert "fight" in ids


def test_render_and_view_smoke():
    state = engine.new_run(seed=9)
    text = render.chat_text(state)
    assert "КРИПТА" in text
    assert len(text) < 4000
    v = render.view(state)
    assert v["title"] and v["emoji"]


def test_score_grows_with_depth():
    shallow = engine.new_run(seed=1)
    deep = engine.new_run(seed=1)
    deep["deepest"] = 5
    deep["kills"] = 7
    deep["gold"] = 50
    assert engine.score(deep)["points"] > engine.score(shallow)["points"]


def test_smart_policy_can_win_sometimes():
    wins = sum(1 for seed in range(300) if play_out(seed, smart_policy)["phase"] == "won")
    assert wins > 0, "игра непроходима — крути баланс"


def test_state_is_json_serializable():
    import json
    state = play_out(123, smart_policy)
    json.dumps(state, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Новые механики: телеграф, защита, разные боссы, живые подсказки
# ---------------------------------------------------------------------------
def _dummy_monster(**over) -> dict:
    monster = {
        "name": "Тест", "emoji": "🐀", "hp": 100, "max_hp": 100, "atk": 10,
        "gold": 0, "line": "", "boss": False, "final": False, "ability": None,
        "armor": 0, "dodge": 0.0, "taunts": [], "death": "", "enraged": False,
        "phase": 0, "turn": 0,
        "intent": {"kind": "heavy", "text": "Замахивается."},
    }
    monster.update(over)
    return monster


def _heavy_hit(guarded: bool) -> dict:
    state = engine.new_run(seed=3)
    state["phase"] = "combat"
    state["monster"] = _dummy_monster()
    state["guard"] = guarded
    state["turns"] = 1
    engine._monster_turn(state)
    return state


def test_door_hints_and_labels_are_unique():
    for seed in range(60):
        state = engine.new_run(seed=seed)
        for floor in (1, 4, 7, 10):
            state["floor"] = floor
            state["node"] = 0
            state["phase"] = "doors"
            engine._open_doors(state)
            hints = [d["hint"] for d in state["doors"]]
            labels = [a["label"] for a in engine.actions(state)]
            assert len(set(hints)) == 2, (seed, floor, hints)
            assert len(set(labels)) == 2, (seed, floor, labels)
            assert hints == labels


def test_combat_shows_intent_and_guard():
    state = engine.new_run(seed=3)
    state["phase"] = "combat"
    state["monster"] = _dummy_monster()
    intent = state["monster"]["intent"]
    assert intent["kind"] and intent["text"]
    ids = [a["id"] for a in engine.actions(state)]
    assert "fight" in ids and "guard" in ids


def test_guard_softens_heavy_and_counters():
    unguarded = _heavy_hit(False)
    guarded = _heavy_hit(True)
    assert guarded["hp"] > unguarded["hp"]
    assert guarded["monster"]["hp"] < guarded["monster"]["max_hp"]


def test_boss_pool_varies_and_has_phases():
    names = set()
    for seed in range(40):
        state = engine.new_run(seed=seed)
        state["floor"] = engine.MAX_FLOOR
        state["node"] = engine.NODES_PER_FLOOR - 1
        engine._open_doors(state)
        engine.apply(state, "door:0")
        monster = state["monster"]
        assert monster["boss"] and monster["phases"]
        names.add(monster["name"])
    assert len(names) >= 3, names


def test_floor_five_has_miniboss():
    state = engine.new_run(seed=8)
    state["floor"] = 5
    state["node"] = engine.NODES_PER_FLOOR - 1
    engine._open_doors(state)
    assert all(d["kind"] == "boss" for d in state["doors"])
    engine.apply(state, "door:0")
    assert state["monster"]["boss"] and not state["monster"]["final"]


def test_attack_labels_vary_with_weapon():
    state = engine.new_run(seed=2)
    state["phase"] = "combat"
    state["monster"] = _dummy_monster()
    state["weapon"] = {"name": "Кинжал", "atk": 3}
    labels = set()
    for turns in range(6):
        state["turns"] = turns
        labels.add(engine.actions(state)[0]["label"])
    assert len(labels) >= 2, labels


def test_boss_phases_switch_on_hp():
    state = engine.new_run(seed=11)
    state["floor"] = engine.MAX_FLOOR
    state["node"] = engine.NODES_PER_FLOOR - 1
    engine._open_doors(state)
    engine.apply(state, "door:0")
    monster = state["monster"]
    monster["hp"] = int(monster["max_hp"] * 0.2)
    monster["intent"] = engine._roll_intent(state, monster, engine._rng(state, "t"))
    assert monster["phase"] >= 1


def test_old_v1_run_migrates():
    import json

    state = engine.new_run(seed=5)
    state["v"] = 1
    state.pop("guard")
    state.pop("poison")
    state["phase"] = "combat"
    state["floor"] = engine.MAX_FLOOR
    state["monster"] = {
        "name": "Король Крипты", "emoji": "👑", "hp": 40, "max_hp": 85,
        "atk": 9, "gold": 250, "line": "", "boss": True,
    }
    engine.migrate(state)
    assert state["v"] == 2
    assert state["monster"]["phases"] and state["monster"]["intent"]
    assert state["guard"] is False and state["poison"] == 0
    engine.apply(state, "fight")
    json.dumps(state, ensure_ascii=False)
