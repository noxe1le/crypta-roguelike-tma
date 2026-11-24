"""Настройки из окружения. Один общий Store на процесс."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from game.storage import Store

# .env всегда рядом с проектом, независимо от текущей директории.
# Реальные переменные окружения имеют приоритет над файлом.
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
DB_PATH = os.getenv("DB_PATH", "crypta.db")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
DEV_MODE = os.getenv("DEV_MODE", "0") == "1"

_store: Store | None = None


def store() -> Store:
    global _store
    if _store is None:
        _store = Store(DB_PATH)
    return _store


def set_store(s: Store) -> None:
    """Подмена хранилища — для тестов."""
    global _store
    _store = s
