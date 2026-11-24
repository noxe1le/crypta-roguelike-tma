"""Разовая настройка профиля бота через Bot API.

    python scripts/setup_bot.py

Меняет имя, описания и команды. Аватар через Bot API поставить нельзя —
только вручную в @BotFather (Edit Bot → Edit Botpic).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

TOKEN = os.environ.get("BOT_TOKEN", "")
NAME = "Крипта"
SHORT = "Рогалик на 10 этажей: двери, лут, босс. Кнопки в чате и Mini App."
DESC = (
    "🕯 Крипта — рогалик на 10 этажей.\n\n"
    "В каждой комнате две двери и только намёк, что за ними: монстр, золото, "
    "ловушка или алтарь. Внизу ждёт Король Крипты.\n\n"
    "Играть можно кнопками прямо в чате или в Mini App с картой и анимациями. "
    "Забег один на оба режима: начал в чате — продолжил в приложении.\n\n"
    "Жми /play."
)
COMMANDS = [
    {"command": "play", "description": "Продолжить или начать забег"},
    {"command": "top", "description": "Таблица лидеров"},
    {"command": "stats", "description": "Моя статистика"},
    {"command": "help", "description": "Как играть"},
]


def call(method: str, **params):
    if not TOKEN:
        raise SystemExit("BOT_TOKEN не найден в .env")
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    data = json.dumps(params).encode() if params else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode())


def main() -> None:
    print("getMe:", call("getMe")["result"]["username"])
    print("setMyName:", call("setMyName", name=NAME).get("ok"))
    print("setMyShortDescription:", call("setMyShortDescription",
                                         short_description=SHORT).get("ok"))
    print("setMyDescription:", call("setMyDescription", description=DESC).get("ok"))
    print("setMyCommands:", call("setMyCommands", commands=COMMANDS).get("ok"))

    # Аватар: у Bot API такого метода нет — проверяем и честно сообщаем.
    probe = call("setMyProfilePhoto", photo="")
    print("setMyProfilePhoto:", probe.get("ok"), probe.get("description", ""))

    print("итог:", call("getMyName")["result"]["name"],
          "|", call("getMyShortDescription")["result"]["short_description"])


if __name__ == "__main__":
    main()
