#!/bin/bash
set -e

echo "=========================================="
echo "Photo & Video Generation Service"
echo "=========================================="

# Запуск планировщика обновления БД в фоне (06:05 МСК — БД, 06:10 МСК — обогащение)
echo "[ENTRYPOINT] Запуск планировщика обновления БД..."
python database/scheduler.py &
SCHEDULER_PID=$!
echo "[ENTRYPOINT] Планировщик запущен (PID: $SCHEDULER_PID)"

# Запуск Telegram бота в фоне
echo "[ENTRYPOINT] Запуск Telegram бота..."
python telegram_bot/bot.py &
BOT_PID=$!
echo "[ENTRYPOINT] Telegram бот запущен (PID: $BOT_PID)"

# Запуск FastAPI сервера на переднем плане
echo "[ENTRYPOINT] Запуск FastAPI сервера (порт 8080)..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8080 --log-level warning

# Если FastAPI упадет, останавливаем все процессы
echo "[ENTRYPOINT] FastAPI остановлен, завершаем все процессы..."
kill $SCHEDULER_PID $BOT_PID 2>/dev/null || true

