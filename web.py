"""HTTP-часть: раздаёт Mini App и API к тому же игровому ядру."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from auth import validate_init_data
from game import content, engine, render

log = logging.getLogger(__name__)
WEBAPP_DIR = Path(__file__).parent / "webapp"

app = FastAPI(title="Крипта — Mini App", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=WEBAPP_DIR), name="static")


def current_user(request: Request) -> dict:
    init_data = request.headers.get("X-Init-Data", "")
    if init_data:
        user = validate_init_data(init_data, config.BOT_TOKEN)
        if not user:
            raise HTTPException(status_code=401, detail="Подпись initData неверна")
        return user

    if config.DEV_MODE:
        raw = request.headers.get("X-Dev-Id") or request.query_params.get("dev_id", "1")
        try:
            uid = int(raw)
        except ValueError:
            uid = 1
        return {"id": uid, "first_name": "Dev"}

    raise HTTPException(status_code=401, detail="Открой игру через Telegram")


def _public_state(state: dict) -> dict:
    """Состояние для клиента: без типов дверей — иначе их видно в сетевой панели."""
    out = dict(state)
    if state.get("doors"):
        out["doors"] = [{"id": d["id"], "hint": d["hint"]} for d in state["doors"]]
    return out


def _payload(state: dict, events: list[dict] | None = None) -> dict:
    finished = state["phase"] in ("dead", "won")
    return {
        "state": _public_state(state),
        "view": render.view(state),
        "actions": engine.actions(state),
        "score": engine.score(state) if finished else None,
        "floor_name": content.FLOOR_NAMES.get(state["floor"], ""),
        "max_floor": engine.MAX_FLOOR,
        "events": events or [],
    }


def _current(user: dict) -> dict:
    """Забег пользователя. Новый создаём только если забега нет вовсе:
    экран итогов после смерти должен дожить до перезагрузки приложения."""
    store = config.store()
    state = store.load_run(user["id"])
    if state is None:
        state = engine.new_run()
        store.save_run(user["id"], state)
    return state


class ActionIn(BaseModel):
    action: str


class NewIn(BaseModel):
    daily: bool = False


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEBAPP_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "dev": config.DEV_MODE, "bot": bool(config.BOT_TOKEN)}


@app.get("/api/state")
async def get_state(request: Request) -> JSONResponse:
    user = current_user(request)
    return JSONResponse(_payload(_current(user)), headers={"Cache-Control": "no-store"})


@app.post("/api/action")
async def post_action(body: ActionIn, request: Request) -> dict:
    user = current_user(request)
    store = config.store()
    state = store.load_run(user["id"])
    if state is None:
        raise HTTPException(status_code=409, detail="Забег не найден")

    if body.action not in {a["id"] for a in engine.actions(state)}:
        raise HTTPException(status_code=409, detail="Этот ход недоступен")

    events = engine.apply(state, body.action)

    if state["phase"] in ("dead", "won") and not state.get("scored"):
        name = user.get("first_name") or user.get("username") or f"Игрок {user['id']}"
        store.add_score(user["id"], name, state)
        state["scored"] = True

    store.save_run(user["id"], state)
    return _payload(state, events)


@app.post("/api/new")
async def post_new(body: NewIn, request: Request) -> dict:
    user = current_user(request)
    state = engine.new_run(daily=body.daily)
    config.store().save_run(user["id"], state)
    return _payload(state)


@app.get("/api/top")
async def get_top(request: Request, daily: bool = False) -> dict:
    current_user(request)
    rows = config.store().top(daily=daily, limit=10)
    return {"rows": rows, "daily": daily}


@app.get("/api/me")
async def get_me(request: Request) -> dict:
    user = current_user(request)
    return config.store().stats(user["id"])
