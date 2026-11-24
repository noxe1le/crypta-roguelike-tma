"""Ядро «Крипты»: генерация подземелья, бой, прогресс.

Модуль чистый — только стандартная библиотека и никакой связи с Telegram.
Состояние забега — обычный dict, который целиком лежит в JSON.
Одна и та же функция `apply` крутит и чат в боте, и Mini App.

Бой построен на телеграфе: монстр заранее показывает, что сделает.
Обычный удар можно пережить, тяжёлый — только под защитой.
"""

from __future__ import annotations

import random
import time

from . import content

MAX_FLOOR = 10
NODES_PER_FLOOR = 4
BOSS_FLOORS = (5, MAX_FLOOR)

START_HP = 30
START_ATK = 5
START_POTIONS = 2

POTION_HEAL = 0.45     # доля максимального HP
DESCEND_HEAL = 8       # лечение за спуск на этаж
MAX_HP_PER_FLOOR = 2   # прибавка к максимуму HP за этаж
OFFER_COST = 30        # подношение алтарю
FLEE_GOLD_LOSS = 0.25
CRIT_CHANCE = 0.15
CRIT_MULT = 1.6
MAX_LOG = 6

HEAVY_MULT = 1.9       # тяжёлый удар монстра
GUARD_CUT = 0.45       # сколько урона проходит под защитой
HEAVY_GUARD_CUT = 0.2  # тяжёлый удар под защитой
COUNTER_MULT = 0.8     # ответный удар после защищённого тяжёлого
GUARD_HEAL = 0         # защита не лечит: иначе можно бесконечно стоять в блоке

KIND_WEIGHTS = [("monster", 45), ("treasure", 18), ("trap", 15),
                ("shrine", 10), ("empty", 12)]


# --------------------------------------------------------------------------
# Утилиты
# --------------------------------------------------------------------------
def today_key() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def daily_seed(day: str | None = None) -> int:
    day = day or today_key()
    return int(day.replace("-", ""))


def _rng(state: dict, *salt) -> random.Random:
    """Детерминированный ГПСЧ: один и тот же забег всегда даёт одно подземелье."""
    key = ":".join(str(p) for p in (state["seed"], state["floor"], state["node"], *salt))
    return random.Random(key)


def _log(state: dict, text: str) -> None:
    state["log"].append(text)
    del state["log"][:-MAX_LOG]


def _recalc(state: dict) -> None:
    state["atk"] = START_ATK + state["weapon"]["atk"] + state["atk_bonus"]
    state["def"] = state["armor"]["def"]


def _roll(rng: random.Random, power: int) -> tuple[int, bool]:
    power = max(1, power)
    dmg = max(1, round(power * rng.uniform(0.8, 1.2)))
    crit = rng.random() < CRIT_CHANCE
    if crit:
        dmg = max(1, round(dmg * CRIT_MULT))
    return dmg, crit


def _weighted(rng: random.Random, pairs: list[tuple[str, int]]) -> str:
    total = sum(w for _, w in pairs)
    r = rng.uniform(0, total)
    acc = 0.0
    for key, w in pairs:
        acc += w
        if r <= acc:
            return key
    return pairs[-1][0]


def _rotate(pool: list[str], turns: int, step: int = 2) -> str:
    return pool[(turns // step) % len(pool)]


# --------------------------------------------------------------------------
# Создание забега
# --------------------------------------------------------------------------
def new_run(seed: int | None = None, daily: bool = False) -> dict:
    if daily:
        seed = daily_seed()
    if seed is None:
        seed = random.randrange(1, 10 ** 9)

    state = {
        "v": 2,
        "seed": int(seed),
        "daily": bool(daily),
        "day": today_key() if daily else None,
        "floor": 1,
        "node": 0,
        "phase": "doors",
        "hp": START_HP,
        "max_hp": START_HP,
        "atk": START_ATK,
        "def": 0,
        "atk_bonus": 0,
        "weapon": {"name": "Кулаки", "atk": 0},
        "armor": {"name": "Лохмотья", "def": 0},
        "gold": 0,
        "potions": START_POTIONS,
        "kills": 0,
        "turns": 0,
        "monster": None,
        "room": None,
        "doors": None,
        "log": [],
        "status": "alive",
        "deepest": 1,
        "guard": False,
        "poison": 0,
    }
    _recalc(state)
    _open_doors(state)
    _log(state, "Факел едва горит. Где-то внизу капает вода.")
    _log(state, content.FLOOR_INTROS[1])
    return state


# --------------------------------------------------------------------------
# Двери и комнаты
# --------------------------------------------------------------------------
def _pick_kind(rng: random.Random) -> str:
    return _weighted(rng, KIND_WEIGHTS)


def _hint_for(state: dict, kind: str, rng: random.Random) -> str:
    hint = rng.choice(content.HINTS[kind])
    accents = content.FLOOR_ACCENTS.get(state["floor"])
    if accents and rng.random() < 0.4:
        accent = rng.choice(accents)
        if len(hint) + len(accent) < 64:
            hint = f"{hint}. {accent}"
    return hint


def _make_door(state: dict, idx: int, attempt: int = 0) -> dict:
    rng = _rng(state, "door", idx, attempt)
    if state["floor"] in BOSS_FLOORS and state["node"] >= NODES_PER_FLOOR - 1:
        return {"id": idx, "kind": "boss", "hint": rng.choice(content.BOSS_HINTS)}
    kind = _pick_kind(rng)
    return {"id": idx, "kind": kind, "hint": _hint_for(state, kind, rng)}


def migrate(state: dict) -> dict:
    """Подтягивает забег старого формата (v1) до текущей схемы.

    В проде могли остаться забеги, начатые до телеграфа и боссов. Терять их
    прогресс не хочется, поэтому недостающие поля добираются на месте.
    """
    if state.get("v", 1) >= 2:
        return state
    state.setdefault("guard", False)
    state.setdefault("poison", 0)

    monster = state.get("monster")
    if monster:
        if monster.get("boss") and "phases" not in monster:
            ratio = monster["hp"] / max(1, monster["max_hp"])
            fresh = _boss_monster(state, content.BOSSES[0])
            fresh["hp"] = max(1, round(fresh["max_hp"] * ratio))
            fresh["intent"] = _roll_intent(state, fresh, _rng(state, "migrate"))
            state["monster"] = fresh
        else:
            monster.setdefault("boss", False)
            monster.setdefault("final", False)
            monster.setdefault("ability", None)
            monster.setdefault("armor", 0)
            monster.setdefault("dodge", 0.0)
            monster.setdefault("taunts", [])
            monster.setdefault("death", "")
            monster.setdefault("last_taunt", None)
            monster.setdefault("enraged", False)
            monster.setdefault("phase", 0)
            monster.setdefault("phase_turn", 0)
            monster.setdefault("turn", 0)
            if not monster.get("intent"):
                monster["intent"] = _roll_intent(state, monster, _rng(state, "migrate"))
    state["v"] = 2
    return state


def _open_doors(state: dict) -> None:
    """Две двери. Подсказки гарантированно разные — даже при одном типе комнаты."""
    doors: list[dict] = []
    seen: set[str] = set()
    for idx in (0, 1):
        door = None
        for attempt in range(16):
            cand = _make_door(state, idx, attempt)
            if cand["hint"] not in seen:
                door = cand
                break
        if door is None:
            door = cand
        seen.add(door["hint"])
        doors.append(door)
    state["doors"] = doors
    state["room"] = None
    state["phase"] = "doors"


def _scale_monster(state: dict, base: dict) -> dict:
    floor = state["floor"]
    hp = base["hp"] + floor * 2
    return {
        "name": base["name"],
        "emoji": base["emoji"],
        "hp": hp,
        "max_hp": hp,
        "atk": base["atk"] + floor // 3,
        "gold": base["gold"] + floor * 2,
        "line": base["line"],
        "boss": False,
        "final": False,
        "ability": base.get("ability"),
        "armor": base.get("armor", 0),
        "dodge": base.get("dodge", 0.0),
        "taunts": list(base.get("taunts") or []),
        "death": base.get("death", ""),
        "last_taunt": None,
        "enraged": False,
        "phase": 0,
        "turn": 0,
        "intent": None,
    }


def _boss_monster(state: dict, base: dict) -> dict:
    return {
        "name": base["name"],
        "emoji": base["emoji"],
        "hp": base["hp"],
        "max_hp": base["hp"],
        "atk": base["atk"],
        "gold": base["gold"],
        "line": base["line"],
        "boss": True,
        "final": state["floor"] == MAX_FLOOR,
        "ability": None,
        "armor": base.get("armor", 0),
        "dodge": base.get("dodge", 0.0),
        "taunts": list(base.get("taunts") or []),
        "death": base.get("death", ""),
        "last_taunt": None,
        "phases": base["phases"],
        "enraged": False,
        "phase": 0,
        "phase_turn": 0,
        "turn": 0,
        "intent": None,
    }


def _monster_for(state: dict, rng: random.Random, boss: bool = False) -> dict:
    if boss:
        pool = content.MINIBOSSES if state["floor"] < MAX_FLOOR else content.BOSSES
        return _boss_monster(state, rng.choice(pool))
    floor = state["floor"]
    tier = 1 if floor <= 3 else 2 if floor <= 6 else 3
    return _scale_monster(state, rng.choice(content.MONSTERS[tier]))


def _random_item(state: dict, rng: random.Random) -> dict | None:
    floor = state["floor"]
    pool = [("weapon", w) for w in content.WEAPONS if w["min_floor"] <= floor]
    pool += [("armor", a) for a in content.ARMOR if a["min_floor"] <= floor]
    if not pool:
        return None
    kind, item = rng.choice(pool)
    return {"kind": kind, **item}


def _equip_or_sell(state: dict, item: dict) -> str:
    if item["kind"] == "weapon":
        if item["atk"] > state["weapon"]["atk"]:
            state["weapon"] = {"name": item["name"], "atk": item["atk"]}
            _recalc(state)
            return f"Ты берёшь {item['name']} (+{item['atk']} к атаке)."
        state["gold"] += 10
        return f"{item['name']} хуже твоего оружия — продаёшь за 10 золота."
    if item["def"] > state["armor"]["def"]:
        state["armor"] = {"name": item["name"], "def": item["def"]}
        _recalc(state)
        return f"Ты надеваешь {item['name']} (+{item['def']} к защите)."
    state["gold"] += 10
    return f"{item['name']} хуже твоей брони — продаёшь за 10 золота."


def _enter(state: dict, door: dict) -> list[dict]:
    """Заходим в комнату и сразу её разрешаем (кроме боя и алтаря)."""
    rng = _rng(state, "room", door["id"])
    kind = door["kind"]
    events: list[dict] = []
    state["room"] = {"kind": kind, "entered": True}
    state["guard"] = False
    state["poison"] = 0
    _log(state, "Дверь открывается.")

    if kind in ("monster", "boss"):
        boss = kind == "boss"
        # Босс один на этаж: обе двери ведут к нему, поэтому сид не зависит от двери.
        monster = _monster_for(state, _rng(state, "boss") if boss else rng, boss=boss)
        state["monster"] = monster
        state["room"]["title"] = monster["name"]
        state["room"]["emoji"] = monster["emoji"]
        state["room"]["text"] = monster["line"]
        state["phase"] = "combat"
        monster["intent"] = _roll_intent(state, monster, rng)
        _log(state, f"За дверью — {monster['name']}.")
        events.append({"t": "encounter", "monster": monster["name"],
                       "boss": boss})
        return events

    if kind == "treasure":
        gold = rng.randint(6, 14) + state["floor"] * 3
        state["gold"] += gold
        text = rng.choice(content.TREASURE_LINES)
        item = _random_item(state, rng) if rng.random() < 0.4 else None
        if item:
            text += " " + _equip_or_sell(state, item)
        state["room"].update(title="Сокровищница", emoji="💰",
                             text=f"{text} (+{gold} золота)")
        _log(state, f"В комнате — {gold} золота.")
        events.append({"t": "loot", "gold": gold, "item": item["name"] if item else None})

    elif kind == "trap":
        dmg = rng.randint(3, 6) + state["floor"]
        state["hp"] = max(0, state["hp"] - dmg)
        state["room"].update(title="Ловушка", emoji="🪤",
                             text=f"{rng.choice(content.TRAP_LINES)} (−{dmg} HP)")
        _log(state, f"Ловушка: −{dmg} HP.")
        events.append({"t": "hit", "who": "player", "dmg": dmg, "crit": False})

    elif kind == "shrine":
        state["room"].update(title="Алтарь", emoji="🕯",
                             text=rng.choice(content.SHRINE_LINES))
        _log(state, "Ты входишь в комнату с алтарём.")
        state["phase"] = "shrine"
        return events

    else:
        state["room"].update(title="Пустая комната", emoji="🌫",
                             text=rng.choice(content.EMPTY_LINES))
        _log(state, "Пустая комната. Только пыль.")

    if state["hp"] <= 0:
        _die(state, rng.choice(content.DEATH_LINES))
        return events

    state["phase"] = "room"
    return events


# --------------------------------------------------------------------------
# Интенты монстров
# --------------------------------------------------------------------------
def _intent(kind: str, text: str) -> dict:
    return {"kind": kind, "text": text}


def _pick_taunt(monster: dict, rng: random.Random) -> str:
    """Реплика монстра без повтора предыдущей — иначе телеграф заедает."""
    taunts = monster.get("taunts") or ["Оно готовится к удару."]
    if len(taunts) > 1:
        options = [t for t in taunts if t != monster.get("last_taunt")] or taunts
        line = rng.choice(options)
    else:
        line = taunts[0]
    monster["last_taunt"] = line
    return line


def _intent_for_kind(kind: str, monster: dict, rng: random.Random) -> dict:
    if kind == "attack":
        return _intent("attack", _pick_taunt(monster, rng))
    if kind == "heavy":
        return _intent("heavy", "Замахивается. Удар придёт сразу — прикройся.")
    if kind == "poison":
        return _intent("poison", "Плюётся едкой дрянью. Прикройся или готовься к яду.")
    if kind == "guard":
        return _intent("guard", "Прикрывается и зализывает раны.")
    if kind == "drain":
        return _intent("drain", "Тянется к тебе, чтобы выпить тепло.")
    if kind == "charge":
        return _intent("charge", "Копит силы. Сейчас не ударит — но следующий удар будет сокрушительным.")
    if kind == "enrage":
        return _intent("enrage", "Рёв. Оно стало злее.")
    return _intent("attack", _pick_taunt(monster, rng))


def _boss_intent(monster: dict, rng: random.Random) -> dict:
    ratio = monster["hp"] / max(1, monster["max_hp"])
    phases = monster["phases"]
    idx = 0
    for i, phase in enumerate(phases):
        if ratio <= phase.get("at", 1.0):
            idx = i
    taunt = None
    if idx > monster.get("phase", 0):
        monster["phase"] = idx
        monster["phase_turn"] = 0
        taunt = phases[idx].get("taunt")
    pattern = phases[idx]["pattern"]
    step = monster.get("phase_turn", 0)
    intent = _intent_for_kind(pattern[step % len(pattern)], monster, rng)
    if taunt:
        intent["taunt"] = taunt
    return intent


def _roll_intent(state: dict, monster: dict, rng: random.Random) -> dict:
    if monster.get("boss"):
        return _boss_intent(monster, rng)

    ability = monster.get("ability")
    ratio = monster["hp"] / max(1, monster["max_hp"])
    if ability == "enrage" and ratio < 0.45 and not monster.get("enraged"):
        monster["enraged"] = True
        monster["atk"] = max(1, round(monster["atk"] * 1.3))
        return _intent("enrage", "Оно ревёт, и мышцы наливаются злостью.")

    weights = [("attack", 58)]
    if ability == "heavy":
        weights.append(("heavy", 22))
    if ability == "poison":
        weights.append(("poison", 20))
    if ability == "guard":
        weights.append(("guard", 18))
    if ability == "drain":
        weights.append(("drain", 20))
    return _intent_for_kind(_weighted(rng, weights), monster, rng)


# --------------------------------------------------------------------------
# Продвижение
# --------------------------------------------------------------------------
def _advance(state: dict) -> None:
    state["node"] += 1
    state["monster"] = None
    state["guard"] = False
    state["poison"] = 0
    if state["node"] >= NODES_PER_FLOOR:
        state["room"] = None
        state["doors"] = None
        state["phase"] = "stairs"
        _log(state, "Впереди ступени, уходящие в темноту.")
    else:
        _open_doors(state)


def _descend(state: dict) -> None:
    state["floor"] += 1
    state["node"] = 0
    state["deepest"] = max(state["deepest"], state["floor"])
    state["max_hp"] += MAX_HP_PER_FLOOR
    state["hp"] = min(state["max_hp"], state["hp"] + DESCEND_HEAL)
    state["monster"] = None
    state["guard"] = False
    state["poison"] = 0
    _open_doors(state)
    name = content.FLOOR_NAMES.get(state["floor"], "Глубже")
    _log(state, f"Этаж {state['floor']}: {name}.")
    intro = content.FLOOR_INTROS.get(state["floor"])
    if intro:
        _log(state, intro)


def _die(state: dict, reason: str) -> None:
    state["phase"] = "dead"
    state["status"] = "dead"
    state["monster"] = None
    state["guard"] = False
    _log(state, reason)


def _win(state: dict, monster: dict) -> None:
    state["phase"] = "won"
    state["status"] = "won"
    state["monster"] = None
    _log(state, f"{monster['name']} падает. Ты выходишь наверх с полным мешком золота.")


def _kill(state: dict, rng: random.Random) -> list[dict]:
    monster = state["monster"]
    gold = monster["gold"]
    state["gold"] += gold
    state["kills"] += 1
    events = [{"t": "kill", "gold": gold, "name": monster["name"]}]
    text = monster.get("death") or f"{monster['emoji']} {monster['name']} падает."
    text += f" (+{gold} золота)"

    if monster.get("final"):
        state["monster"] = None
        state["room"] = {"kind": "boss", "title": "Тронный зал", "emoji": "🏆",
                         "text": "Тишина. Только твоё дыхание и звон монет."}
        _win(state, monster)
        return events + [{"t": "win"}]

    loot_chance = 1.0 if monster.get("boss") else 0.35
    item = _random_item(state, rng) if rng.random() < loot_chance else None
    if item:
        text += " " + _equip_or_sell(state, item)
        events.append({"t": "loot", "gold": 0, "item": item["name"]})
    if rng.random() < (0.6 if monster.get("boss") else 0.3):
        state["potions"] += 1
        text += " " + rng.choice(content.POTION_FOUND_LINES)
    state["monster"] = None
    state["phase"] = "room"
    state["guard"] = False
    state["poison"] = 0
    state["room"] = {"kind": "cleared", "emoji": "🩸",
                     "title": rng.choice(content.CLEARED_TITLES), "text": text}
    return events


# --------------------------------------------------------------------------
# Действия
# --------------------------------------------------------------------------
def actions(state: dict) -> list[dict]:
    """Список доступных ходов. Один и тот же для бота и Mini App."""
    phase = state["phase"]
    if phase == "doors":
        return [{"id": f"door:{d['id']}", "label": d["hint"], "emoji": "🚪",
                 "kind": "door"} for d in state["doors"]]
    if phase == "room":
        return [{"id": "next", "label": _rotate(content.NEXT_LABELS, state["turns"]),
                 "emoji": "➡️", "kind": "next"}]
    if phase == "shrine":
        out = [
            {"id": "shrine:heal",
             "label": f"Выпить из чаши (+{round(state['max_hp'] * POTION_HEAL)} HP)",
             "emoji": "🧪", "kind": "shrine"},
            {"id": "shrine:power", "label": "Коснуться алтаря (+2 к атаке)",
             "emoji": "🔥", "kind": "shrine"},
        ]
        if state["gold"] >= OFFER_COST:
            out.append({"id": "shrine:offer",
                        "label": f"Подношение {OFFER_COST} золота — зелье в дорогу",
                        "emoji": "💰", "kind": "shrine"})
        return out
    if phase == "combat":
        weapon = (state.get("weapon") or {}).get("name", "")
        verbs = content.ATTACK_VERBS.get(weapon, content.DEFAULT_ATTACK_VERBS)
        out = [
            {"id": "fight", "label": _rotate(verbs, state["turns"]),
             "emoji": "⚔️", "kind": "fight"},
            {"id": "guard", "label": _rotate(content.GUARD_LABELS, state["turns"], 3),
             "emoji": "🛡", "kind": "guard"},
        ]
        if state["potions"] > 0:
            out.append({"id": "potion",
                        "label": f"{_rotate(content.POTION_LABELS, state['turns'], 3)} ({state['potions']})",
                        "emoji": "🧪", "kind": "potion"})
        if not (state["monster"] or {}).get("boss"):
            out.append({"id": "flee", "label": _rotate(content.FLEE_LABELS, state["turns"], 3),
                        "emoji": "🏃", "kind": "flee"})
        return out
    if phase == "stairs":
        return [{"id": "down", "label": _rotate(content.DOWN_LABELS, state["turns"]),
                 "emoji": "🕳", "kind": "down"}]
    return []


def apply(state: dict, action: str) -> list[dict]:
    """Применяет ход. Мутирует state, возвращает события для анимаций."""
    state["turns"] += 1
    phase = state["phase"]

    if phase == "doors" and action.startswith("door:"):
        idx = int(action.split(":")[1])
        door = next((d for d in state["doors"] if d["id"] == idx), None)
        if door is None:
            return []
        return _enter(state, door)

    if phase == "room" and action == "next":
        _advance(state)
        return []

    if phase == "stairs" and action == "down":
        _descend(state)
        return []

    if phase == "shrine" and action in ("shrine:heal", "shrine:power", "shrine:offer"):
        if action == "shrine:heal":
            heal = min(state["max_hp"] - state["hp"], round(state["max_hp"] * POTION_HEAL))
            state["hp"] += heal
            _log(state, f"Ты пьёшь из чаши. (+{heal} HP)")
            ev = [{"t": "heal", "amount": heal}]
        elif action == "shrine:power":
            state["atk_bonus"] += 2
            _recalc(state)
            _log(state, "Алтарь забирает немного тепла и отдаёт силу. (+2 к атаке)")
            ev = [{"t": "buff", "amount": 2}]
        else:
            state["gold"] -= OFFER_COST
            state["potions"] += 1
            _log(state, "Монеты исчезают в чаше. В руке остаётся зелье.")
            ev = [{"t": "loot", "gold": -OFFER_COST, "item": "зелье"}]
        state["room"] = {"kind": "shrine", "title": "Алтарь", "emoji": "🕯",
                         "text": "Руны гаснут. Комната снова обычная."}
        state["phase"] = "room"
        return ev

    if phase == "combat":
        if action == "fight":
            return _fight(state)
        if action == "guard":
            return _guard(state)
        if action == "potion" and state["potions"] > 0:
            state["potions"] -= 1
            heal = min(state["max_hp"] - state["hp"], round(state["max_hp"] * POTION_HEAL))
            state["hp"] += heal
            ev = [{"t": "heal", "amount": heal}]
            _log(state, f"Зелье. (+{heal} HP)")
            return ev + _monster_turn(state)
        if action == "flee":
            return _flee(state)

    return []


def _fight(state: dict) -> list[dict]:
    rng = _rng(state, "fight", state["turns"])
    monster = state["monster"]
    events: list[dict] = []

    if monster.get("dodge") and rng.random() < monster["dodge"]:
        _log(state, f"{monster['name']} уходит в сторону. Ты бьёшь по пустоте.")
        events.append({"t": "miss", "who": "monster"})
    else:
        dmg, crit = _roll(rng, state["atk"])
        if monster.get("armor"):
            dmg = max(1, dmg - monster["armor"])
        if (monster.get("intent") or {}).get("kind") == "guard":
            dmg = max(1, dmg // 2)
        monster["hp"] = max(0, monster["hp"] - dmg)
        pool = content.PLAYER_CRIT_LINES if crit else content.PLAYER_HIT_LINES
        _log(state, rng.choice(pool).format(name=monster["name"], dmg=dmg))
        events.append({"t": "hit", "who": "monster", "dmg": dmg, "crit": crit})

    if monster["hp"] <= 0:
        return events + _kill(state, rng)
    return events + _monster_turn(state)


def _guard(state: dict) -> list[dict]:
    state["guard"] = True
    heal = min(GUARD_HEAL, state["max_hp"] - state["hp"])
    state["hp"] += heal
    text = "Ты прикрываешься и ловишь дыхание."
    if heal:
        text += f" (+{heal} HP)"
    _log(state, text)
    events: list[dict] = [{"t": "guard"}]
    if heal:
        events.append({"t": "heal", "amount": heal})
    return events + _monster_turn(state)


def _monster_turn(state: dict) -> list[dict]:
    monster = state["monster"]
    if not monster:
        return []
    rng = _rng(state, "monster", state["turns"])
    intent = monster.get("intent") or _intent("attack", "")
    kind = intent.get("kind", "attack")
    guarded = bool(state.get("guard"))
    poison_before = state.get("poison", 0)
    events: list[dict] = []

    if intent.get("taunt") and not intent.get("said"):
        _log(state, intent["taunt"])
        intent["said"] = True
        events.append({"t": "taunt", "text": intent["taunt"]})

    if kind in ("attack", "heavy", "drain", "poison"):
        mult = {"heavy": HEAVY_MULT, "poison": 0.6, "drain": 0.9}.get(kind, 1.0)
        dmg, _ = _roll(rng, max(1, round(monster["atk"] * mult) - state["def"]))
        if guarded:
            dmg = max(0, round(dmg * (HEAVY_GUARD_CUT if kind == "heavy" else GUARD_CUT)))
        heal = 0
        if kind == "poison":
            state["poison"] = max(poison_before, 2)
        elif kind == "drain":
            heal = max(1, round(dmg * 0.6))
            monster["hp"] = min(monster["max_hp"], monster["hp"] + heal)
        state["hp"] = max(0, state["hp"] - dmg)
        events.append({"t": "hit", "who": "player", "dmg": dmg,
                       "crit": kind == "heavy"})
        if kind == "heavy":
            if guarded:
                counter = max(1, round(state["atk"] * COUNTER_MULT))
                monster["hp"] = max(0, monster["hp"] - counter)
                events.append({"t": "hit", "who": "monster", "dmg": counter, "crit": False})
                text = f"Ты принимаешь удар на щит и бьёшь в ответ: −{counter}. Сам держишься (−{dmg})."
            else:
                text = f"{monster['name']} обрушивает тяжёлый удар: −{dmg}."
        elif kind == "poison":
            text = f"Яд обжигает: −{dmg}. Он ещё будет жечь."
        elif kind == "drain":
            text = f"{monster['name']} вытягивает из тебя тепло: −{dmg}, себе +{heal}."
        else:
            pool = content.MONSTER_GUARDED_LINES if guarded else content.MONSTER_HIT_LINES
            text = rng.choice(pool).format(name=monster["name"], dmg=dmg)
        _log(state, text)

    elif kind == "guard":
        heal = max(1, round(monster["max_hp"] * 0.05))
        monster["hp"] = min(monster["max_hp"], monster["hp"] + heal)
        _log(state, f"{monster['name']} прикрывается и переводит дыхание (+{heal}).")
        events.append({"t": "guard_monster"})
    elif kind == "charge":
        _log(state, f"{monster['name']} собирается с силами. Следующий удар будет сокрушительным.")
        events.append({"t": "charge"})
    elif kind == "enrage":
        _log(state, f"{monster['name']} ревёт. Оно стало злее.")
        events.append({"t": "buff", "amount": 0})

    if monster["hp"] <= 0:
        state["guard"] = False
        return events + _kill(state, rng)

    if poison_before > 0:
        pdmg = max(1, 1 + state["floor"] // 4)
        state["poison"] = poison_before - 1
        state["hp"] = max(0, state["hp"] - pdmg)
        events.append({"t": "hit", "who": "player", "dmg": pdmg,
                       "crit": False, "poison": True})
        _log(state, f"Яд делает своё дело: −{pdmg}.")

    state["guard"] = False
    if state["hp"] <= 0:
        _die(state, rng.choice(content.DEATH_LINES))
        events.append({"t": "death"})
        return events

    monster["turn"] = monster.get("turn", 0) + 1
    if monster.get("boss"):
        monster["phase_turn"] = monster.get("phase_turn", 0) + 1
    monster["intent"] = _roll_intent(state, monster, rng)
    if monster["intent"].get("taunt"):
        _log(state, monster["intent"]["taunt"])
        monster["intent"]["said"] = True
    return events


def _flee(state: dict) -> list[dict]:
    lost = int(state["gold"] * FLEE_GOLD_LOSS)
    state["gold"] -= lost
    monster = state["monster"]
    events = [{"t": "flee", "gold": lost}]
    state["monster"] = None
    state["poison"] = 0
    # Монстр бьёт в спину один раз.
    rng = _rng(state, "flee", state["turns"])
    dmg, _ = _roll(rng, monster["atk"] - state["def"])
    state["hp"] = max(0, state["hp"] - dmg)
    events.append({"t": "hit", "who": "player", "dmg": dmg, "crit": False})
    if state["hp"] <= 0:
        _die(state, "Ты почти ушёл. Почти.")
        events.append({"t": "death"})
        return events
    state["room"] = {"kind": "fled", "title": "Отступление", "emoji": "🏃",
                     "text": f"Ты уходишь в другой коридор. В спину прилетает −{dmg}."}
    state["phase"] = "room"
    return events


# --------------------------------------------------------------------------
# Итоги
# --------------------------------------------------------------------------
def score(state: dict) -> dict:
    return {
        "floor": state["deepest"],
        "kills": state["kills"],
        "gold": state["gold"],
        "won": state["status"] == "won",
        "points": state["deepest"] * 100 + state["kills"] * 15 + state["gold"] // 2
                  + (500 if state["status"] == "won" else 0),
    }
