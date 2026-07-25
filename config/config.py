import os
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()

# Файлы и сеть
MAX_FILE_SIZE_MB = 20

# Утилиты
BYTES_TO_MB_DIVISOR = 1024 * 1024

# Сервис
SERVICE_NAME = "photo-generation-service"

# Ограничение одновременных задач генерации фото и видео
MAX_CONCURRENT_PHOTO_TASKS = int(os.getenv("MAX_CONCURRENT_PHOTO_TASKS"))
MAX_CONCURRENT_VIDEO_TASKS = int(os.getenv("MAX_CONCURRENT_VIDEO_TASKS"))

# OpenRouter API - Banana (Gemini для генерации фото)
OPENROUTER_BANANA_CONFIG: Dict[str, Any] = {
    "api_key": os.getenv("OPENROUTER_API_KEY_BANANA"),
    "model_name": "google/gemini-2.5-flash-image",  # Stable version (не preview)
    "max_tokens": 2048,
    "temperature": 0.5,
    "max_long_side": 3000,
    "site_url": os.getenv("OPENROUTER_SITE_URL"),  # Опционально
    "site_name": os.getenv("OPENROUTER_SITE_NAME", "Content Generator"),
}

# OpenRouter API — Claude Sonnet 4.5 (для генерации промптов для видео)
OPENROUTER_PROMPT_CONFIG: Dict[str, Any] = {
    "api_key": os.getenv("OPENROUTER_API_KEY_PROMPT"),
    "model_name": "anthropic/claude-sonnet-4.5",
    "max_tokens": 8192,
    "temperature": 0.3,
    "max_long_side": 2200,
    "site_url": os.getenv("OPENROUTER_SITE_URL"),  # Опционально
    "site_name": os.getenv("OPENROUTER_SITE_NAME", "Content Generator"),
}

# Генерация фото
PHOTO_GENERATION_CONFIG: Dict[str, Any] = {
    "min_photos": 1,
    "max_photos": 10,
    "supported_formats": [".jpg", ".jpeg", ".png", ".webp"],
}

# Alibaba Wan Video API
ALIBABA_WAN_CONFIG: Dict[str, Any] = {
    "api_key": os.getenv("API_KEY_WAN2.2_I2V_PLUS"),
    "model": "wan2.2-i2v-plus",
    "base_url": "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis",
    "resolution": "480P",
    "max_polling_time": 300,
    "max_image_size": 1024,
}

# Telegram Bot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_SESSION_TIMEOUT_MINUTES = int(os.getenv("TELEGRAM_SESSION_TIMEOUT_MINUTES"))

# API для Telegram бота
API_HOST = os.getenv("API_HOST")
API_PORT = int(os.getenv("API_PORT"))

# Credentials для доступа к серверам (1C/РМП)
USER = os.getenv("USER")
PASSWORD = os.getenv("PASSWORD")

# Порог цены для генерации видео
VIDEO_PRICE_THRESHOLD = int(os.getenv("VIDEO_PRICE_THRESHOLD"))

# Базовый URL для сгенерированных файлов
GENERATED_FILES_BASE_URL = os.getenv("GENERATED_FILES_BASE_URL")

