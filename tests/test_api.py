"""Тесты HTTP-слоя: Mini App ходит через те же правила, что и бот."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import config
import web
from game.storage import Store

H = {"X-Dev-Id": "5"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEV_MODE", True)
    monkeypatch.setattr(config, "BOT_TOKEN", "")
    config.set_store(Store(tmp_path / "test.db"))
    return TestClient(web.app)


def test_state_starts_new_run(client):
    r = client.get("/api/state", headers=H)
    assert r.status_code == 200
    data = r.json()
    assert data["state"]["phase"] == "doors"
    assert len(data["actions"]) == 2
    assert data["view"]["title"]
    assert data["state"]["hp"] == data["state"]["max_hp"]


def test_doors_do_not_leak_room_types(client):
    data = client.get("/api/state", headers=H).json()
    assert data["state"]["doors"], "двери должны быть"
    for door in data["state"]["doors"]:
        assert "kind" not in door, "тип комнаты нельзя отдавать клиенту"
        assert door["hint"]


def test_action_advances_turn(client):
    client.get("/api/state", headers=H)
    r = client.post("/api/action", json={"action": "door:0"}, headers=H)
    assert r.status_code == 200
    assert r.json()["state"]["turns"] == 1


def test_bad_action_rejected(client):
    client.get("/api/state", headers=H)
    r = client.post("/api/action", json={"action": "door:9"}, headers=H)
    assert r.status_code == 409


def test_unauthorized_without_dev_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEV_MODE", False)
    monkeypatch.setattr(config, "BOT_TOKEN", "123:abc")
    config.set_store(Store(tmp_path / "t2.db"))
    c = TestClient(web.app)
    assert c.get("/api/state").status_code == 401


def test_full_game_through_api(client):
    data = client.get("/api/state", headers=H).json()
    for _ in range(400):
        if not data["actions"]:
            break
        action = data["actions"][0]["id"]
        r = client.post("/api/action", json={"action": action}, headers=H)
        assert r.status_code == 200, r.text
        data = r.json()
        if data["state"]["phase"] in ("dead", "won"):
            break

    assert data["state"]["phase"] in ("dead", "won")
    assert data["score"] is not None
    assert data["score"]["points"] > 0

    top = client.get("/api/top", headers=H).json()
    assert top["rows"], "результат должен попасть в таблицу"
    assert top["rows"][0]["points"] > 0


def test_finished_run_survives_reload(client):
    data = client.get("/api/state", headers=H).json()
    for _ in range(400):
        if not data["actions"]:
            break
        data = client.post("/api/action", json={"action": data["actions"][0]["id"]},
                           headers=H).json()
        if data["state"]["phase"] in ("dead", "won"):
            break
    again = client.get("/api/state", headers=H).json()
    assert again["state"]["phase"] in ("dead", "won")
    assert again["score"] is not None


def test_new_run_resets(client):
    client.get("/api/state", headers=H)
    client.post("/api/action", json={"action": "door:0"}, headers=H)
    r = client.post("/api/new", json={"daily": True}, headers=H)
    st = r.json()["state"]
    assert st["floor"] == 1 and st["hp"] == st["max_hp"] and st["daily"] is True


def test_daily_runs_share_seed(client):
    a = client.post("/api/new", json={"daily": True}, headers={"X-Dev-Id": "1"}).json()["state"]
    b = client.post("/api/new", json={"daily": True}, headers={"X-Dev-Id": "2"}).json()["state"]
    assert a["seed"] == b["seed"]
    assert [d["hint"] for d in a["doors"]] == [d["hint"] for d in b["doors"]]


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "КРИПТА" in r.text
