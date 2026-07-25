# Photo / Video Generation

Генерация lifestyle-фото и видео ювелирных изделий для Avito: FastAPI + Telegram-бот + ежедневный updater CSV.

## Stack

- Python 3.10, FastAPI, Uvicorn, aiogram 3, Pillow, pandas, zxing-cpp
- OpenRouter: фото `google/gemini-2.5-flash-image`; промпт видео `anthropic/claude-sonnet-4.5`
- Alibaba DashScope: `wan2.2-i2v-plus` (image→video)
- S3-совместимое хранилище (aioboto3) / HTTP выгрузки РМП
- Docker (`entrypoint.sh`: scheduler + bot + API `:8080`)

## Pipeline

1. Scheduler обновляет CSV изделий из внешних выгрузок.
2. В Telegram: УИН / DataMatrix → запрос генерации.
3. Фото через OpenRouter → сохранение URL.
4. Видео через Wan I2V → polling статуса.
5. Enricher дописывает ссылки обратно в выгрузки.

## Run

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=... \
       OPENROUTER_API_KEY_BANANA=... OPENROUTER_API_KEY_PROMPT=... \
       API_KEY_WAN2.2_I2V_PLUS=... GENERATED_FILES_BASE_URL=...
# database/data с CSV монтируется отдельно
./entrypoint.sh
# или uvicorn app.main:app --port 8080
```

## Config

| Variable | Required | Notes |
|----------|----------|-------|
| `TELEGRAM_BOT_TOKEN` | yes | |
| `OPENROUTER_API_KEY_BANANA` | yes | фото |
| `OPENROUTER_API_KEY_PROMPT` | yes | промпт видео |
| `API_KEY_WAN2.2_I2V_PLUS` | yes | DashScope |
| `GENERATED_FILES_BASE_URL` | yes | публичный base URL файлов |
| `MAX_CONCURRENT_PHOTO_TASKS` / `MAX_CONCURRENT_VIDEO_TASKS` | yes | |

## Notes

- CSV/каталоги `database/data` в репозиторий не входят.
- API: `POST /GeneratePhoto`, `POST /GenerateVideo`, `GET /VideoStatus/{task_id}`, `GET /health`.
