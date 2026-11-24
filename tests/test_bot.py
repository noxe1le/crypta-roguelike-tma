"""Тесты бота: хендлеры дёргаются напрямую, Telegram подменён моками.

Настоящий токен не нужен — проверяем, что кнопки ведут туда, куда должны,
а тексты и callback_data валидны для Telegram.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User

import bot
import config
from game import engine
from game.storage import Store


def make_cb(data: str, uid: int = 5) -> CallbackQuery:
    user = User(id=uid, is_bot=False, first_name="Тест")
    chat = Chat(id=uid, type="private")
    msg = Message(message_id=1, date=1_700_000_000, chat=chat, from_user=user, text="x")
    return CallbackQuery(id="cb1", from_user=user, chat_instance="ci", message=msg, data=data)


def call(coro):
    return asyncio.run(coro)


def callbacks(kb) -> list[str]:
    return [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data]


@pytest.fixture()
def fresh_store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEV_MODE", True)
    monkeypatch.setattr(config, "BOT_TOKEN", "")
    monkeypatch.setattr(config, "WEBAPP_URL", "https://example.com/app")
    config.set_store(Store(tmp_path / "bot.db"))
    return config.store()


def test_screen_for_every_phase(fresh_store):
    seen = set()
    for seed in range(40):
        state = engine.new_run(seed=seed)
        for _ in range(300):
            seen.add(state["phase"])
            text, kb = bot.screen(state)
            assert "КРИПТА" in text or state["phase"] in ("dead", "won")
            for data in callbacks(kb):
                assert len(data.encode()) <= 64, f"callback_data слишком длинный: {data}"
            acts = engine.actions(state)
            if not acts:
                break
            engine.apply(state, acts[0]["id"])
            if state["phase"] in ("dead", "won"):
                break
    assert {"doors", "combat", "room", "stairs"} <= seen


def test_door_buttons_match_actions(fresh_store):
    state = engine.new_run(seed=4)
    _, kb = bot.screen(state)
    got = {d[2:] for d in callbacks(kb) if d.startswith("a:")}
    assert got == {a["id"] for a in engine.actions(state)}


def test_finished_screen_offers_new_run(fresh_store):
    state = engine.new_run(seed=4)
    state["phase"] = "dead"
    state["status"] = "dead"
    text, kb = bot.screen(state)
    assert "Ты погиб" in text
    assert "new:random" in callbacks(kb)
    assert "new:daily" in callbacks(kb)


def test_webapp_button_present_when_url_set(fresh_store):
    state = engine.new_run(seed=4)
    _, kb = bot.screen(state)
    buttons = [b for row in kb.inline_keyboard for b in row]
    assert any(b.web_app and b.web_app.url == "https://example.com/app" for b in buttons)


def test_webapp_button_hidden_without_url(fresh_store, monkeypatch):
    monkeypatch.setattr(config, "WEBAPP_URL", "")
    state = engine.new_run(seed=4)
    _, kb = bot.screen(state)
    buttons = [b for row in kb.inline_keyboard for b in row]
    assert not any(b.web_app for b in buttons)


def test_play_and_action_flow(fresh_store):
    cb = make_cb("play:chat")
    with patch.object(Message, "edit_text", new=AsyncMock()) as edit, \
         patch.object(CallbackQuery, "answer", new=AsyncMock()):
        call(bot.on_play(cb))
        assert edit.await_count == 1
        assert "КРИПТА" in edit.await_args.args[0]

        cb2 = make_cb("a:door:0")
        call(bot.on_action(cb2))
        assert edit.await_count == 2
        assert "КРИПТА" in edit.await_args.args[0]

    state = fresh_store.load_run(5)
    assert state["turns"] == 1
    assert state["phase"] in ("room", "combat", "shrine", "dead")


def test_action_cannot_be_replayed_out_of_turn(fresh_store):
    with patch.object(Message, "edit_text", new=AsyncMock()), \
         patch.object(CallbackQuery, "answer", new=AsyncMock()) as ans:
        call(bot.on_play(make_cb("play:chat")))  # создаём забег
        call(bot.on_action(make_cb("a:fight")))
        assert any("недоступен" in str(c.args) for c in ans.await_args_list)


def test_new_run_resets_state(fresh_store):
    with patch.object(Message, "edit_text", new=AsyncMock()), \
         patch.object(CallbackQuery, "answer", new=AsyncMock()):
        call(bot.on_play(make_cb("play:chat")))
        call(bot.on_action(make_cb("a:door:0")))
        call(bot.on_new(make_cb("new:random")))
    state = fresh_store.load_run(5)
    assert state["floor"] == 1 and state["turns"] == 0


def test_daily_run_has_daily_seed(fresh_store):
    with patch.object(Message, "edit_text", new=AsyncMock()), \
         patch.object(CallbackQuery, "answer", new=AsyncMock()):
        call(bot.on_new(make_cb("new:daily", uid=9)))
    state = fresh_store.load_run(9)
    assert state["daily"] is True
    assert state["seed"] == engine.daily_seed()


def test_score_saved_once_on_death(fresh_store):
    state = engine.new_run(seed=4)
    state["phase"] = "dead"
    state["status"] = "dead"
    fresh_store.save_run(5, state)
    with patch.object(Message, "edit_text", new=AsyncMock()), \
         patch.object(CallbackQuery, "answer", new=AsyncMock()):
        call(bot.on_top(make_cb("top")))
    assert fresh_store.top() == []


def test_leaderboard_renders_rows(fresh_store):
    state = engine.new_run(seed=4)
    state["phase"] = "dead"
    state["status"] = "dead"
    fresh_store.add_score(5, "Тест", state)
    text, kb = bot._leaderboard(daily=False)
    assert "Тест" in text
    assert "top:daily" in callbacks(kb)


def test_toast_summarizes_events(fresh_store):
    events = [{"t": "hit", "who": "monster", "dmg": 7, "crit": False},
              {"t": "kill", "gold": 12, "name": "Крыса"}]
    out = bot._toast(events)
    assert "монстр" in out and "12" in out
