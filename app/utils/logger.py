import logging
import sys
from datetime import datetime


class FastAPIFormatter(logging.Formatter):
    """Formatter с префиксом [FASTAPI] для FastAPI логов"""
    
    def format(self, record: logging.LogRecord) -> str:
        # Форматируем время вручную для единообразия
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')
        # Добавляем префикс [FASTAPI] и временную метку
        return f"[FASTAPI] {timestamp} - {record.levelname} - {record.getMessage()}"


def get_logger(name: str) -> logging.Logger:
    """Создает логгер с префиксом [FASTAPI] для FastAPI приложения"""
    logger = logging.getLogger(name)
    
    # Избегаем дублирования handlers
    if logger.hasHandlers():
        return logger
        
    logger.setLevel(logging.INFO)
    
    # Консольный handler для Docker
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    formatter = FastAPIFormatter()
    console_handler.setFormatter(formatter)
    
    logger.addHandler(console_handler)

    logger.propagate = False
    
    return logger