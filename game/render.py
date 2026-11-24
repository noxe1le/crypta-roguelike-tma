"""Текст для чата: одна и та же игра, но без графики."""

from __future__ import annotations

from . import content, engine

BAR_WIDTH = 10

INTENT_ICON = {
    "attack": "⚡",
    "heavy": "⚠️",
    "poison": "☠️",
    "guard": "🛡",
    "drain": "🩸",
    "charge": "💥",
    "enrage": "🔥",
}


def hp_bar(cur: int, mx: int, width: int = BAR_WIDTH) -> str:
    mx = max(1, mx)
    filled = max(0, min(width, round(width * cur / mx)))
    return "█" * filled + "░" * (width - filled)


def _header(state: dict) -> str:
    name = content.FLOOR_NAMES.get(state["floor"], "")
    return (f"🕯 <b>КРИПТА</b> · этаж {state['floor']}/{engine.MAX_FLOOR}"
            f"{' · ' + name if name else ''}")


def _stats(state: dict) -> str:
    return (f"❤️ <b>{state['hp']}</b>/{state['max_hp']}   ⚔️ {state['atk']}   "
            f"🛡 {state['def']}   💰 {state['gold']}   🧪 {state['potions']}")


def _player_status(state: dict) -> str:
    bits = []
    if state.get("guard"):
        bits.append("🛡 в защите")
    if state.get("poison"):
        bits.append(f"☠ яд ({state['poison']})")
    return "   ".join(bits)


def _monster_intent(monster: dict) -> str:
    intent = monster.get("intent") or {}
    text = intent.get("text") or ""
    if not text:
        return ""
    return f"{INTENT_ICON.get(intent.get('kind'), '⚡')} <i>{text}</i>"


def chat_text(state: dict) -> str:
    """Основной экран игры для чата."""
    lines = [_header(state), "", _stats(state), hp_bar(state["hp"], state["max_hp"]), ""]

    if state["phase"] == "dead":
        reason = state["log"][-1] if state["log"] else "Крипта не отпускает никого."
        lines += _result_block(state, "💀 <b>Ты погиб</b>", reason)
        return "\n".join(lines)
    if state["phase"] == "won":
        reason = state["log"][-1] if state["log"] else "Король мёртв, ты — нет."
        lines += _result_block(state, "🏆 <b>Крипта пройдена</b>", reason)
        return "\n".join(lines)

    if state["phase"] == "combat" and state["monster"]:
        m = state["monster"]
        title = m["name"]
        if m.get("boss") and m.get("phases"):
            title += f" · фаза {m.get('phase', 0) + 1}/{len(m['phases'])}"
        lines += [
            f"{m['emoji']} <b>{title}</b>",
            f"❤️ {m['hp']}/{m['max_hp']}   ⚔️ {m['atk']}",
            hp_bar(m["hp"], m["max_hp"]),
            f"<i>{m['line']}</i>",
            _monster_intent(m),
        ]
        status = _player_status(state)
        if status:
            lines.append(status)
    elif state["phase"] == "stairs":
        nxt = content.FLOOR_NAMES.get(state["floor"] + 1, "тьма")
        lines += ["🕳 <b>Лестница вниз</b>",
                  f"<i>Ступени уходят во тьму. Внизу — {nxt.lower()}.</i>"]
    elif state["room"]:
        r = state["room"]
        lines += [f"{r['emoji']} <b>{r['title']}</b>", f"<i>{r['text']}</i>"]
    elif state["phase"] == "doors":
        lines += ["🚪 <b>Две двери</b>", "<i>Куда пойдёшь? Намёк — единственная подсказка.</i>"]

    tail = state["log"][-2:]
    if tail:
        lines += ["", "─" * 14] + [f"<i>{t}</i>" for t in tail]
    return "\n".join(lines)


def _result_block(state: dict, title: str, subtitle: str) -> list[str]:
    sc = engine.score(state)
    return [
        title, f"<i>{subtitle}</i>", "",
        f"Глубина: <b>{sc['floor']}</b> из {engine.MAX_FLOOR}",
        f"Убито: <b>{sc['kills']}</b>   Золото: <b>{sc['gold']}</b>",
        f"Очки: <b>{sc['points']}</b>",
        "",
        "Можно начать новый забег или попробовать забег дня — одинаковое подземелье для всех.",
    ]


def short_status(state: dict) -> str:
    return (f"этаж {state['floor']}/{engine.MAX_FLOOR} · ❤️ {state['hp']}/{state['max_hp']}"
            f" · 💰 {state['gold']} · убито {state['kills']}")


def view(state: dict) -> dict:
    """Что показать на главном экране Mini App. Единый источник правды для UI."""
    if state["phase"] == "dead":
        return {"emoji": "💀", "title": "Ты погиб",
                "text": state["log"][-1] if state["log"] else "Крипта не отпускает никого."}
    if state["phase"] == "won":
        return {"emoji": "🏆", "title": "Крипта пройдена",
                "text": state["log"][-1] if state["log"] else "Король мёртв, ты — нет."}
    if state["phase"] == "combat" and state["monster"]:
        m = state["monster"]
        out = {
            "emoji": m["emoji"],
            "title": m["name"],
            "text": m["line"],
            "monster": {"hp": m["hp"], "max_hp": m["max_hp"]},
            "intent": m.get("intent") or {},
            "status": _player_status(state),
            "boss": bool(m.get("boss")),
        }
        if m.get("boss") and m.get("phases"):
            out["phase"] = f"фаза {m.get('phase', 0) + 1}/{len(m['phases'])}"
        return out
    if state["phase"] == "stairs":
        nxt = content.FLOOR_NAMES.get(state["floor"] + 1, "тьма")
        return {"emoji": "🕳", "title": "Лестница вниз",
                "text": f"Ступени уходят во тьму. Внизу — {nxt.lower()}."}
    if state["room"]:
        r = state["room"]
        return {"emoji": r["emoji"], "title": r["title"], "text": r["text"]}
    if state["phase"] == "doors":
        return {"emoji": "🚪", "title": "Две двери",
                "text": "Куда пойдёшь? Намёк — единственная подсказка."}
    return {"emoji": "🕯", "title": "Крипта", "text": ""}
