"""
Модуль для отслеживания сгенерированных фото и видео
Ведет CSV файл с УИНами и URL сгенерированных файлов

Формат photo_gen.csv:
Cabinet,UIN,Id,ImageUrls,LivePhoto
"""
import csv
import asyncio
import logging
import pandas as pd
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Путь к файлу отслеживания
PHOTO_GEN_CSV = Path("database/data/photo_gen.csv")
ITEMS_CSV = Path("database/data/items_out.csv")


COLUMNS = ['Cabinet', 'UIN', 'Id', 'ImageUrls', 'LivePhoto']


def _ensure_csv_exists():
    """Создает CSV файл с заголовками, если его нет"""
    if not PHOTO_GEN_CSV.exists():
        PHOTO_GEN_CSV.parent.mkdir(parents=True, exist_ok=True)
        with open(PHOTO_GEN_CSV, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(COLUMNS)
        logger.info(f"[PHOTO_GEN] Создан файл {PHOTO_GEN_CSV}")


def _get_cabinet_by_uin(uin: str) -> str:
    """Получить номер кабинета по УИН из items_out.csv"""
    try:
        if not ITEMS_CSV.exists():
            logger.error(f"[PHOTO_GEN] Файл {ITEMS_CSV} не найден")
            return ''
        
        df_items = pd.read_csv(ITEMS_CSV, dtype={'UIN': str, 'Cabinet': str})
        row = df_items[df_items['UIN'] == uin]
        if not row.empty:
            return str(row['Cabinet'].iloc[0])
        logger.warning(f"[PHOTO_GEN] Кабинет не найден для УИН {uin}")
        return ''
    except Exception as e:
        logger.error(f"[PHOTO_GEN] Ошибка получения кабинета для УИН {uin}: {e}")
        return ''


async def save_generated_file(photo_url: str, item_id: str, uin: str):
    """
    Сохраняет информацию о сгенерированном файле (фото или видео) в CSV
    
    НОВАЯ ЛОГИКА:
    - Одна строка на УИН
    - Может быть и фото И видео одновременно (для дорогих изделий ≥50,000₽)
    - Если запись существует, обновляем нужное поле (ImageUrls или LivePhoto)
    
    Args:
        photo_url: URL сгенерированного файла
        item_id: ID изделия в РМП (артикул, например "0652000117200001")
        uin: УИН изделия (16 цифр)
    """
    def _save_or_update():
        _ensure_csv_exists()
        
        # Получить Cabinet из items_out.csv
        cabinet = _get_cabinet_by_uin(uin)
        if not cabinet:
            logger.warning(f"[PHOTO_GEN] Не удалось определить кабинет для УИН {uin}, пропускаем")
            return
        
        # Определить тип файла
        is_photo = photo_url.endswith('.jpg') or photo_url.endswith('.jpeg')
        is_video = photo_url.endswith('.mp4')
        
        # Загрузить существующий CSV
        if PHOTO_GEN_CSV.exists() and PHOTO_GEN_CSV.stat().st_size > 0:
            df = pd.read_csv(PHOTO_GEN_CSV, dtype={'UIN': str, 'Cabinet': str, 'Id': str})
            if 'Id' not in df.columns:
                df['Id'] = ''
        else:
            df = pd.DataFrame(columns=COLUMNS)
        
        # Привести к нужному порядку колонок (если файл старый)
        for c in COLUMNS:
            if c not in df.columns:
                df[c] = ''
        df = df[COLUMNS]
        
        # Проверить, есть ли уже запись для этого УИН
        existing_row = df[df['UIN'] == uin]
        
        if not existing_row.empty:
            # Обновить существующую запись
            idx = existing_row.index[0]
            if is_photo:
                df.at[idx, 'ImageUrls'] = photo_url
                logger.info(f"[PHOTO_GEN] Обновлено фото для УИН {uin}: {photo_url}")
            elif is_video:
                df.at[idx, 'LivePhoto'] = photo_url
                logger.info(f"[PHOTO_GEN] Обновлено видео для УИН {uin}: {photo_url}")
            if item_id:
                df.at[idx, 'Id'] = str(item_id).strip()
        else:
            # Добавить новую запись: Cabinet, UIN, Id, ImageUrls, LivePhoto
            new_row = {
                'Cabinet': cabinet,
                'UIN': uin,
                'Id': str(item_id).strip() if item_id else '',
                'ImageUrls': photo_url if is_photo else '',
                'LivePhoto': photo_url if is_video else ''
            }
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            logger.info(f"[PHOTO_GEN] Добавлена новая запись: УИН={uin}, Cabinet={cabinet}, {'фото' if is_photo else 'видео'}={photo_url}")
        
        # Сохранить CSV в нужном порядке
        df[COLUMNS].to_csv(PHOTO_GEN_CSV, index=False)
    
    # Выполняем в отдельном потоке, чтобы не блокировать asyncio
    await asyncio.to_thread(_save_or_update)


def get_generated_files_by_uin(uin: str) -> dict[str, Optional[str]]:
    """
    Получает информацию о сгенерированных файлах для УИН
    
    Args:
        uin: УИН изделия (16 цифр)
    
    Returns:
        dict с полями photo_url, video_url или None
    """
    if not PHOTO_GEN_CSV.exists():
        return {'photo_url': None, 'video_url': None}
    
    try:
        df = pd.read_csv(PHOTO_GEN_CSV, dtype={'UIN': str})
        row = df[df['UIN'] == uin]
        
        if row.empty:
            return {'photo_url': None, 'video_url': None}
        
        photo_url = row['ImageUrls'].iloc[0] if pd.notna(row['ImageUrls'].iloc[0]) and row['ImageUrls'].iloc[0] else None
        video_url = row['LivePhoto'].iloc[0] if pd.notna(row['LivePhoto'].iloc[0]) and row['LivePhoto'].iloc[0] else None
        
        return {'photo_url': photo_url, 'video_url': video_url}
    except Exception as e:
        logger.error(f"[PHOTO_GEN] Ошибка чтения файла для УИН {uin}: {e}")
        return {'photo_url': None, 'video_url': None}


def _is_filled(val) -> bool:
    """Есть ли непустая ссылка в поле."""
    if pd.isna(val):
        return False
    return bool(str(val).strip())


def _clear_column_by_uin(uin: str, column: str, label: str) -> bool:
    """
    Обнулить колонку column для записи с данным UIN.
    Если после этого в строке не остаётся ни фото, ни видео — удалить строку целиком.
    Иначе оставить строку с оставшейся ссылкой (фото или видео).
    """
    if not PHOTO_GEN_CSV.exists():
        logger.warning(f"[PHOTO_GEN] Файл {PHOTO_GEN_CSV} не существует")
        return False
    df = pd.read_csv(PHOTO_GEN_CSV, dtype={'UIN': str})
    row_idx = df[df['UIN'] == uin].index
    if row_idx.empty:
        logger.warning(f"[PHOTO_GEN] Запись {label} для УИН {uin} не найдена")
        return False
    idx = row_idx[0]
    df.at[idx, column] = ''
    # Проверяем вторую колонку: осталось ли что-то (фото или видео)
    other = 'LivePhoto' if column == 'ImageUrls' else 'ImageUrls'
    has_other = _is_filled(df.at[idx, other])
    if not has_other:
        # Ни фото, ни видео не осталось — удаляем всю строку
        df = df.drop(index=idx).reset_index(drop=True)
        logger.info(f"[PHOTO_GEN] Строка для УИН {uin} удалена (удалено {label}, второго контента не было)")
    else:
        logger.info(f"[PHOTO_GEN] {label.capitalize()} удалено для УИН {uin}, строка сохранена с оставшейся ссылкой")
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = ''
    df[COLUMNS].to_csv(PHOTO_GEN_CSV, index=False)
    return True


async def delete_generated_video_by_uin(uin: str) -> bool:
    """
    Удаляет запись о сгенерированном видео из CSV и файл с РМП сервера
    
    Args:
        uin: УИН изделия (16 цифр)
    
    Returns:
        True если удалено успешно, False если ошибка
    """
    # Сначала удаляем файл с РМП сервера
    from app.services.file_storage import delete_generated_file
    deleted_from_rmp = await delete_generated_file(uin, "video")
    
    if not deleted_from_rmp:
        logger.warning(f"[PHOTO_GEN] Файл видео не удалён с РМП, но продолжаем удаление из CSV")
    return await asyncio.to_thread(_clear_column_by_uin, uin, 'LivePhoto', 'видео')


async def delete_generated_photo_by_uin(uin: str) -> bool:
    """
    Удаляет запись о сгенерированном фото из CSV и файл с РМП сервера
    
    Args:
        uin: УИН изделия (16 цифр)
    
    Returns:
        True если удалено успешно, False если ошибка
    """
    # Сначала удаляем файл с РМП сервера
    from app.services.file_storage import delete_generated_file
    deleted_from_rmp = await delete_generated_file(uin, "photo")
    
    if not deleted_from_rmp:
        logger.warning(f"[PHOTO_GEN] Файл фото не удалён с РМП, но продолжаем удаление из CSV")
    return await asyncio.to_thread(_clear_column_by_uin, uin, 'ImageUrls', 'фото')
