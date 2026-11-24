#!/usr/bin/env bash
# Поднимает HTTPS-туннель и бота одной командой.
#
# Зачем: у Telegram Mini App должен быть https-адрес, а у нас нет домена.
# cloudflared quick tunnel даёт случайный https://*.trycloudflare.com.
# Адрес живёт только пока живёт процесс, поэтому сервис стартует туннель
# первым, вытаскивает URL из лога и передаёт его приложению через WEBAPP_URL.
#
# systemd перезапускает этот скрипт целиком — значит адрес всегда свежий,
# а кнопка Mini App в боте обновляется при старте (bot.set_chat_menu_button).

set -euo pipefail

cd "$(dirname "$0")/.."

PORT="${PORT:-8000}"
LOG="${TMPDIR:-/tmp}/cloudflared-crypta.log"
rm -f "$LOG"

cleanup() {
    for pid in "${APP_PID:-}" "${TUNNEL_PID:-}"; do
        [[ -n "$pid" ]] || continue
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    done
}
trap cleanup EXIT INT TERM

cloudflared tunnel --url "http://127.0.0.1:${PORT}" --no-autoupdate \
    --logfile "$LOG" --loglevel info &
TUNNEL_PID=$!

URL=""
for _ in $(seq 1 60); do
    URL="$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOG" 2>/dev/null | head -1 || true)"
    [[ -n "$URL" ]] && break
    if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
        echo "cloudflared упал, смотри $LOG" >&2
        exit 1
    fi
    sleep 1
done

if [[ -z "$URL" ]]; then
    echo "не дождались адреса туннеля за 60 секунд" >&2
    exit 1
fi

echo "Mini App: $URL"
export WEBAPP_URL="$URL"
export PORT

.venv/bin/python run.py &
APP_PID=$!
wait "$APP_PID"
