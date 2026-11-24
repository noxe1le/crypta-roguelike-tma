"""Живой прогон бота без настоящего токена.

Поднимаем локальный «Telegram API» (aiohttp), отдаём ему один апдейт /start,
запускаем настоящий polling aiogram и смотрим, что бот реально отправил.
Так проверяется вся связка: роутер, хендлер, клавиатура, сериализация.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiohttp import web

import bot as bot_module
import config
from game.storage import Store

TOKEN = "123456:TEST-TOKEN"


def _bot_info() -> dict:
    """getMe в Bot API 9.x требует кучу полей — собираем их из самой модели aiogram."""
    from aiogram.types import BotFullInfo

    out: dict = {}
    for name, field in BotFullInfo.model_fields.items():
        if field.is_required():
            out[name] = {"bool": False, "int": 0, "str": ""}.get(
                getattr(field.annotation, "__name__", ""), None)
    out.update(id=123456, is_bot=True, first_name="Крипта",
               username="crypta_test_bot", can_join_groups=True)
    return out


class FakeTelegram:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.updates_served = 0
        self._update = {
            "update_id": 1,
            "message": {
                "message_id": 10,
                "date": 1_700_000_000,
                "chat": {"id": 5, "type": "private", "first_name": "Сергей"},
                "from": {"id": 5, "is_bot": False, "first_name": "Сергей"},
                "text": "/start",
                "entities": [{"type": "bot_command", "offset": 0, "length": 6}],
            },
        }

    async def handle(self, request: web.Request) -> web.Response:
        try:
            return await self._handle(request)
        except Exception:  # noqa: BLE001 — в тесте полезно увидеть причину
            import traceback
            traceback.print_exc()
            raise

    async def _handle(self, request: web.Request) -> web.Response:
        method = request.match_info["method"]
        if method == "getMe":
            return web.json_response({"ok": True, "result": _bot_info()})
        if method == "getUpdates":
            if self.updates_served == 0:
                self.updates_served += 1
                return web.json_response({"ok": True, "result": [self._update]})
            await asyncio.sleep(0.05)
            return web.json_response({"ok": True, "result": []})
        if method in ("sendMessage", "editMessageText"):
            if request.content_type.startswith("application/json"):
                payload = await request.json()
            else:  # локальный API иногда шлёт form-data
                payload = dict(await request.post())
            self.sent.append({"method": method, **payload})
            return web.json_response({"ok": True, "result": {
                "message_id": 11, "date": 1_700_000_001,
                "chat": {"id": payload.get("chat_id", 5), "type": "private"},
                "text": payload.get("text", ""),
            }})
        return web.json_response({"ok": True, "result": True})


@pytest.fixture()
def fake(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEV_MODE", True)
    monkeypatch.setattr(config, "BOT_TOKEN", TOKEN)
    monkeypatch.setattr(config, "WEBAPP_URL", "https://example.com/app")
    config.set_store(Store(tmp_path / "e2e.db"))
    return FakeTelegram()


def test_bot_answers_start_with_menu(fake):
    async def scenario() -> FakeTelegram:
        app = web.Application()
        app.router.add_post("/bot{token}/{method}", fake.handle)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]

        api = TelegramAPIServer.from_base(f"http://127.0.0.1:{port}", is_local=True)
        session = AiohttpSession(api=api)
        bot = Bot(TOKEN, session=session)
        dp = Dispatcher()
        dp.include_router(bot_module.router)

        poller = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
        try:
            for _ in range(200):
                if fake.sent:
                    break
                await asyncio.sleep(0.05)
        finally:
            if dp._running_lock.locked():  # polling мог не успеть стартовать
                await dp.stop_polling()
            poller.cancel()
            await asyncio.gather(poller, return_exceptions=True)
            await bot.session.close()
            await runner.cleanup()
        return fake

    fake = asyncio.run(scenario())

    assert fake.sent, "бот не отправил ни одного сообщения"
    msg = fake.sent[0]
    assert msg["method"] == "sendMessage"
    assert int(msg["chat_id"]) == 5
    assert "КРИПТА" in msg["text"]

    markup = json.loads(msg["reply_markup"]) if isinstance(msg["reply_markup"], str) else msg["reply_markup"]
    buttons = [b for row in markup["inline_keyboard"] for b in row]
    datas = [b.get("callback_data") for b in buttons]
    assert "play:chat" in datas
    assert any("web_app" in b and b["web_app"]["url"] == "https://example.com/app" for b in buttons)

    assert config.store().load_run(5) is None, "забег создаётся по кнопке, а не по /start"
