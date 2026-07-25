import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.updater import run_full_update
from database.enricher import enrich_all_cabinets

# Логи в stdout для Docker
# Настраиваем логгер после импорта updater.py, чтобы перезаписать его настройки
logger = logging.getLogger(__name__)
# Устанавливаем отдельный обработчик для планировщика
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter('[SCHEDULER] %(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)
logger.setLevel(logging.INFO)
# Отключаем распространение на root logger, чтобы избежать дублирования
logger.propagate = False


async def daily_update_at_3am():
    """
    Планировщик обновления базы данных и обогащения файлов
    
    Расписание (боевое):
    - 03:05 UTC (06:05 МСК) - обновление БД (items_out.csv, rmp_out.csv)
    - 03:10 UTC (06:10 МСК) - обогащение файлов по кабинетам (<cab>_out.csv)
    
    Запускается автоматически в Docker контейнере через entrypoint.sh
    """
    logger.info("=" * 80)
    logger.info("Планировщик запущен")
    logger.info("Обновление БД: 06:05 МСК (03:05 UTC)")
    logger.info("Обогащение файлов по кабинетам: 06:10 МСК (03:10 UTC)")
    logger.info("=" * 80)
    
    # Запуск первого обновления при старте (если база пустая)
    base_dir = Path(__file__).parent / 'data'
    items_file = base_dir / 'items_out.csv'
    rmp_file = base_dir / 'rmp_out.csv'
    
    if not items_file.exists() or not rmp_file.exists():
        logger.info("База данных не найдена. Запуск первоначального обновления...")
        try:
            run_full_update()
        except Exception as e:
            logger.exception(f"Ошибка первоначального обновления: {e}")
    
    # Флаг выполнения обновления БД
    db_updated_today = False
    
    while True:
        now = datetime.now(timezone.utc)
        
        # Этап 1: Обновление БД в 06:05 МСК = 03:05 UTC
        if now.hour == 3 and now.minute == 5 and not db_updated_today:
            logger.info("=" * 80)
            logger.info(f"[06:05 МСК] Начало обновления базы данных: {now}")
            logger.info("=" * 80)
            
            try:
                success_db = run_full_update()
                if success_db:
                    logger.info("Обновление базы завершено успешно")
                    db_updated_today = True
                else:
                    logger.error("Обновление базы завершилось с ошибками")
            except Exception as e:
                logger.exception(f"Ошибка при обновлении базы: {e}")
            
            # Ждем 60 секунд
            await asyncio.sleep(60)
        
        # Этап 2: Обогащение файлов по кабинетам в 06:10 МСК = 03:10 UTC
        elif now.hour == 3 and now.minute == 10 and db_updated_today:
            logger.info("=" * 80)
            logger.info(f"[06:10 МСК] Начало обогащения файлов по кабинетам: {now}")
            logger.info("=" * 80)
            
            try:
                enrichment_result = await enrich_all_cabinets()
                logger.info(f"Создание файлов завершено: {enrichment_result}")
            except Exception as e:
                logger.exception(f"Ошибка при создании файлов: {e}")
            
            # Сбрасываем флаг для следующего дня
            db_updated_today = False
            
            # Ждем 60 секунд
            await asyncio.sleep(60)
        
        # Сбрасываем флаг в полночь для нового дня
        elif now.hour == 0 and now.minute == 0:
            db_updated_today = False
            await asyncio.sleep(60)
        
        # Проверяем каждую минуту
        await asyncio.sleep(60)


if __name__ == "__main__":
    try:
        asyncio.run(daily_update_at_3am())
    except KeyboardInterrupt:
        logger.info("Планировщик остановлен пользователем")
