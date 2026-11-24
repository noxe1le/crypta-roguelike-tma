"""Тесты подписи initData — без неё Mini App пустила бы кого угодно."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from auth import validate_init_data

TOKEN = "123456:TEST-TOKEN"


def make_init_data(token: str = TOKEN, user: dict | None = None, auth_date: int | None = None) -> str:
    user = user or {"id": 42, "first_name": "Сергей", "username": "sergey"}
    data = {
        "user": json.dumps(user, separators=(",", ":"), ensure_ascii=False),
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
    }
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def test_valid_signature():
    user = validate_init_data(make_init_data(), TOKEN)
    assert user and user["id"] == 42
    assert user["first_name"] == "Сергей"


def test_wrong_token_rejected():
    assert validate_init_data(make_init_data(), "999:OTHER") is None


def test_tampered_data_rejected():
    init = make_init_data()
    tampered = init.replace("42", "43")
    assert validate_init_data(tampered, TOKEN) is None


def test_expired_rejected():
    old = int(time.time()) - 60 * 60 * 48
    assert validate_init_data(make_init_data(auth_date=old), TOKEN) is None


def test_garbage_rejected():
    assert validate_init_data("", TOKEN) is None
    assert validate_init_data("hash=abc", TOKEN) is None
    assert validate_init_data("not a query string", TOKEN) is None
