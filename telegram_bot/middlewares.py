"""
Middleware для Telegram бота
"""
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config.config import TELEGRAM_SESSION_TIMEOUT_MINUTES

logger = logging.getLogger(__name__)


class SessionTimeoutMiddleware(BaseMiddleware):
    """
    Middleware для автоматического закрытия сессий после 12 часов неактивности
    """
    
    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        state: FSMContext = data.get("state")
        
        if not state:
            return await handler(event, data)
        
        # Получаем текущие данные состояния
        state_data = await state.get_data()
        last_activity = state_data.get("last_activity")
        
        # Проверяем таймаут
        if last_activity:
            try:
                last_activity_time = datetime.fromisoformat(last_activity)
                time_passed = datetime.now() - last_activity_time
                
                if time_passed > timedelta(minutes=TELEGRAM_SESSION_TIMEOUT_MINUTES):
                    # Сессия истекла
                    logger.info(f"[SESSION] Сессия истекла для пользователя {event.from_user.id}, "
                               f"неактивность: {time_passed}")
                    
                    # Очищаем состояние молча
                    await state.clear()
            
            except (ValueError, TypeError) as e:
                logger.error(f"[SESSION] Ошибка парсинга времени активности: {e}")
        
        # Обновляем время последней активности
        await state.update_data(last_activity=datetime.now().isoformat())
        
        # Продолжаем обработку
        return await handler(event, data)

