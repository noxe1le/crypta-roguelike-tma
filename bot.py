"""Телеграм-бот «Крипты»: та же игра, но кнопками в чате."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           Message, WebAppInfo)

import config
from game import engine, render

log = logging.getLogger(__name__)
router = Router()

WELCOME = (
    "🕯 <b>КРИПТА</b>\n\n"
    "Подземелье на 10 этажей. Каждый забег генерируется заново: комнаты, "
    "монстры, лут и один очень уставший король внизу.\n\n"
    "Играть можно двумя способами — и это <b>одна и та же игра</b>:\n"
    "• <b>в чате</b> — кнопками прямо здесь;\n"
    "• <b>в Mini App</b> — с картой этажа, анимациями и инвентарём.\n\n"
    "Начал в чате — открыл приложение и продолжил с того же места. "
    "Прогресс общий.\n\n"
    "Дверей всегда две, а подсказки — единственное, что ты знаешь о комнате за ними."
)


# --------------------------------------------------------------------------
# Клавиатуры
# --------------------------------------------------------------------------
def _kb(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _app_row() -> list[list[InlineKeyboardButton]]:
    if not config.WEBAPP_URL:
        return []
    return [[InlineKeyboardButton(text="🎮 Открыть Mini App",
                                  web_app=WebAppInfo(url=config.WEBAPP_URL))]]


def _start_kb() -> InlineKeyboardMarkup:
    rows = _app_row()
    rows.append([InlineKeyboardButton(text="⚔️ Играть в чате", callback_data="play:chat")])
    rows.append([
        InlineKeyboardButton(text="🏆 Топ", callback_data="top"),
        InlineKeyboardButton(text="📊 Профиль", callback_data="me"),
    ])
    return _kb(rows)


def _game_kb(state: dict) -> InlineKeyboardMarkup:
    if state["phase"] in ("dead", "won"):
        rows = [
            [InlineKeyboardButton(text="🔁 Новый забег", callback_data="new:random")],
            [InlineKeyboardButton(text="📅 Забег дня", callback_data="new:daily")],
        ]
        rows += _app_row()
        rows.append([
            InlineKeyboardButton(text="🏆 Топ", callback_data="top"),
            InlineKeyboardButton(text="📊 Профиль", callback_data="me"),
        ])
        return _kb(rows)

    rows = [[InlineKeyboardButton(text=f"{a['emoji']} {a['label']}", callback_data=f"a:{a['id']}")]
            for a in engine.actions(state)]
    rows += _app_row()
    rows.append([InlineKeyboardButton(text="🏆 Топ", callback_data="top")])
    return _kb(rows)


def screen(state: dict) -> tuple[str, InlineKeyboardMarkup]:
    return render.chat_text(state), _game_kb(state)


# --------------------------------------------------------------------------
# Вспомогательное
# --------------------------------------------------------------------------
def _name(user) -> str:
    return (getattr(user, "full_name", None) or getattr(user, "first_name", None)
            or f"Игрок {user.id}")


def _toast(events: list[dict]) -> str:
    parts = []
    for e in events:
        if e["t"] == "hit":
            who = "ты" if e["who"] == "player" else "монстр"
            parts.append(f"{who} −{e['dmg']}")
        elif e["t"] == "heal":
            parts.append(f"+{e['amount']} HP")
        elif e["t"] == "kill":
            parts.append(f"убит +{e['gold']}💰")
        elif e["t"] == "buff":
            parts.append(f"+{e['amount']}⚔️")
        elif e["t"] == "win":
            parts.append("победа!")
        elif e["t"] == "miss":
            parts.append("мимо")
        elif e["t"] == "charge":
            parts.append("готовит удар!")
        elif e["t"] == "guard":
            parts.append("защита")
    return " · ".join(parts[:3])


async def _edit(cb: CallbackQuery, state: dict, toast: str | None = None) -> None:
    text, kb = screen(state)
    try:
        await cb.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            log.warning("edit failed: %s", e)
    await cb.answer(toast or "")


async def _finish_if_needed(user_id: int, name: str, state: dict) -> None:
    if state["phase"] in ("dead", "won") and not state.get("scored"):
        config.store().add_score(user_id, name, state)
        state["scored"] = True


def _leaderboard(daily: bool) -> tuple[str, InlineKeyboardMarkup]:
    rows = config.store().top(daily=daily, limit=10)
    title = "🏆 <b>Топ забега дня</b>" if daily else "🏆 <b>Топ всех времён</b>"
    lines = [title, ""]
    if not rows:
        lines.append("<i>Пока пусто. Первое место свободно.</i>")
    else:
        medals = ["🥇", "🥈", "🥉"]
        for i, r in enumerate(rows):
            mark = medals[i] if i < 3 else f"{i + 1}."
            crown = " 👑" if r.get("won") else ""
            lines.append(f"{mark} <b>{r['name']}</b>{crown} — {r['points']} очк. "
                         f"(этаж {r['floor']}, убито {r['kills']})")
    kb = _kb([
        [InlineKeyboardButton(text="🌍 Общий", callback_data="top"),
         InlineKeyboardButton(text="📅 Дня", callback_data="top:daily")],
        [InlineKeyboardButton(text="⬅️ К игре", callback_data="back")],
    ])
    return "\n".join(lines), kb


# --------------------------------------------------------------------------
# Хендлеры
# --------------------------------------------------------------------------
@router.message(CommandStart())
async def cmd_start(msg: Message) -> None:
    config.store().touch_user(msg.from_user.id, _name(msg.from_user))
    await msg.answer(WELCOME, reply_markup=_start_kb())


@router.message(Command("help"))
async def cmd_help(msg: Message) -> None:
    await msg.answer(WELCOME, reply_markup=_start_kb())


@router.message(Command("play"))
async def cmd_play(msg: Message) -> None:
    state = config.store().load_run(msg.from_user.id)
    if state is None or state["phase"] in ("dead", "won"):
        state = engine.new_run()
        config.store().save_run(msg.from_user.id, state)
    text, kb = screen(state)
    await msg.answer(text, reply_markup=kb)


@router.message(Command("top"))
async def cmd_top(msg: Message) -> None:
    text, kb = _leaderboard(daily=False)
    await msg.answer(text, reply_markup=kb)


@router.message(Command("stats"))
async def cmd_stats(msg: Message) -> None:
    st = config.store().stats(msg.from_user.id)
    state = config.store().load_run(msg.from_user.id)
    lines = [f"📊 <b>{_name(msg.from_user)}</b>", "",
             f"Забегов: <b>{st['runs']}</b>",
             f"Лучшая глубина: <b>{st['best_floor']}</b>",
             f"Лучший результат: <b>{st['best_points']}</b> очков"]
    if state:
        lines += ["", f"Текущий забег: {render.short_status(state)}"]
    await msg.answer("\n".join(lines))


@router.callback_query(F.data == "play:chat")
async def on_play(cb: CallbackQuery) -> None:
    state = config.store().load_run(cb.from_user.id)
    if state is None or state["phase"] in ("dead", "won"):
        state = engine.new_run()
        config.store().save_run(cb.from_user.id, state)
    await _edit(cb, state, "Вниз.")


@router.callback_query(F.data.startswith("new:"))
async def on_new(cb: CallbackQuery) -> None:
    mode = cb.data.split(":", 1)[1]
    state = engine.new_run(daily=(mode == "daily"))
    config.store().save_run(cb.from_user.id, state)
    await _edit(cb, state, "Забег дня" if mode == "daily" else "Новый забег")


@router.callback_query(F.data.startswith("a:"))
async def on_action(cb: CallbackQuery) -> None:
    action = cb.data[2:]
    state = config.store().load_run(cb.from_user.id)
    if state is None:
        await cb.answer("Забег не найден — начни новый")
        return

    if action not in {a["id"] for a in engine.actions(state)}:
        await cb.answer("Этот ход уже недоступен")
        await _edit(cb, state)
        return

    events = engine.apply(state, action)
    await _finish_if_needed(cb.from_user.id, _name(cb.from_user), state)
    config.store().save_run(cb.from_user.id, state)
    await _edit(cb, state, _toast(events))


@router.callback_query(F.data.in_({"top", "top:daily"}))
async def on_top(cb: CallbackQuery) -> None:
    text, kb = _leaderboard(daily=cb.data.endswith("daily"))
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass
    await cb.answer()


@router.callback_query(F.data == "back")
async def on_back(cb: CallbackQuery) -> None:
    state = config.store().load_run(cb.from_user.id)
    if state is None:
        await cb.message.edit_text(WELCOME, reply_markup=_start_kb())
        await cb.answer()
        return
    await _edit(cb, state)


@router.callback_query(F.data == "me")
async def on_me(cb: CallbackQuery) -> None:
    st = config.store().stats(cb.from_user.id)
    state = config.store().load_run(cb.from_user.id)
    lines = [f"📊 <b>{_name(cb.from_user)}</b>", "",
             f"Забегов: <b>{st['runs']}</b>",
             f"Лучшая глубина: <b>{st['best_floor']}</b>",
             f"Лучший результат: <b>{st['best_points']}</b>"]
    if state:
        lines += ["", f"Текущий забег: {render.short_status(state)}"]
    await cb.message.edit_text("\n".join(lines), reply_markup=_kb(
        [[InlineKeyboardButton(text="⬅️ К игре", callback_data="back")]]))
    await cb.answer()
