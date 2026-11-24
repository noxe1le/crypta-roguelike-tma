"""Запуск всего: веб-сервер (Mini App) + бот в одном процессе.

    python run.py                # и то, и другое
    python run.py --no-bot       # только Mini App (для разработки)
    python run.py --no-web       # только бот
"""

from __future__ import annotations

import argparse
import asyncio
import logging

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo

import bot as bot_module
import config
import web

log = logging.getLogger("crypta")


async def run_bot() -> None:
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(bot_module.router)
    if config.WEBAPP_URL:
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
            text="Играть", web_app=WebAppInfo(url=config.WEBAPP_URL)))
    await bot.set_my_commands([
        BotCommand(command="play", description="Продолжить или начать забег"),
        BotCommand(command="top", description="Таблица лидеров"),
        BotCommand(command="stats", description="Моя статистика"),
        BotCommand(command="help", description="Как играть"),
    ])
    log.info("Бот запущен")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


async def main(args: argparse.Namespace) -> None:
    tasks = []
    if not args.no_web:
        server = uvicorn.Server(uvicorn.Config(
            web.app, host=config.HOST, port=config.PORT, log_level="info",
            proxy_headers=True, forwarded_allow_ips="*",
        ))
        tasks.append(asyncio.create_task(server.serve()))
        log.info("Mini App: http://%s:%s", config.HOST, config.PORT)

    if not args.no_bot:
        if not config.BOT_TOKEN:
            log.error("BOT_TOKEN не задан — бот не запустится (см. .env.example)")
        else:
            tasks.append(asyncio.create_task(run_bot()))

    if not tasks:
        log.error("Нечего запускать: и бот, и веб отключены")
        return

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Крипта")
    parser.add_argument("--no-bot", action="store_true", help="не запускать бота")
    parser.add_argument("--no-web", action="store_true", help="не запускать веб-сервер")
    try:
        asyncio.run(main(parser.parse_args()))
    except KeyboardInterrupt:
        print("\nПока.")
