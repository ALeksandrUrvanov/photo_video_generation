import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config.config import TELEGRAM_BOT_TOKEN, TELEGRAM_SESSION_TIMEOUT_MINUTES
from telegram_bot.handlers import router
from telegram_bot.middlewares import SessionTimeoutMiddleware

# Логи в stdout для Docker
logging.basicConfig(
    level=logging.INFO,
    format='[TELEGRAM_BOT] %(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


async def main():
    """Запуск Telegram бота"""
    
    # Инициализация бота
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Подключаем middleware для автоматического закрытия сессий
    dp.message.middleware(SessionTimeoutMiddleware())
    dp.callback_query.middleware(SessionTimeoutMiddleware())
    
    # Подключаем роутер с обработчиками
    dp.include_router(router)
    
    # Устанавливаем команды бота для Menu
    from aiogram.types import BotCommand
    await bot.set_my_commands([
        BotCommand(command="start", description="Начать работу"),
        BotCommand(command="help", description="Инструкция"),
    ])
    
    # Получаем информацию о боте
    bot_info = await bot.get_me()
    
    logger.info("=" * 80)
    logger.info("Telegram бот для генерации фото изделий запущен")
    logger.info(f"Бот ID: {bot_info.id}")
    logger.info(f"Username: @{bot_info.username}")
    logger.info(f"Таймаут сессии: {TELEGRAM_SESSION_TIMEOUT_MINUTES // 60} часов")
    logger.info("Ожидание сообщений от товароведов...")
    logger.info("=" * 80)
    
    # Запуск polling
    try:
        await dp.start_polling(bot, skip_updates=True)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Telegram бот остановлен пользователем")
