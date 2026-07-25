"""
Модуль для сохранения сгенерированных файлов на РМП сервер через HTTP PUT
Использует тот же метод, что и код от руководителя в photo_and_price/main.py
"""
import asyncio
import os
from pathlib import Path
from typing import Tuple
import logging
import pandas as pd
import requests

from config.config import GENERATED_FILES_BASE_URL, USER, PASSWORD

logger = logging.getLogger(__name__)


def get_item_id_by_uin(uin: str) -> str:
    """
    Получить артикул РМП (Id) по УИН из items_out.csv
    
    Args:
        uin: УИН изделия (16 цифр)
    
    Returns:
        Id из items_out.csv (например "0652000117200001")
    """
    try:
        items_file = Path("database/data/items_out.csv")
        if not items_file.exists():
            logger.error(f"Файл не найден: {items_file}")
            return uin  # Возвращаем УИН как fallback
        
        df = pd.read_csv(items_file)
        uin_int = int(uin)
        
        item = df[df['UIN'] == uin_int]
        if not item.empty:
            item_id = item.iloc[0]['Id']
            logger.info(f"[STORAGE] УИН {uin} -> Id {item_id}")
            return item_id
        else:
            logger.warning(f"[STORAGE] УИН {uin} не найден, используем УИН как Id")
            return uin
    except Exception as e:
        logger.error(f"[STORAGE] Ошибка получения Id по УИН {uin}: {e}")
        return uin


async def save_generated_file(
    file_data: bytes,
    uin: str,
    file_type: str  # "photo" or "video"
) -> Tuple[str, str]:
    """
    Сохраняет сгенерированный файл на сервер
    
    Args:
        file_data: Байты файла
        uin: УИН изделия (16 цифр)
        file_type: "photo" или "video"
    
    Returns:
        Tuple[url, item_id]: URL файла и артикул РМП
    """
    # Определяем расширение
    extension = "jpg" if file_type == "photo" else "mp4"
    
    # Формируем имя файла: {УИН}_10.{extension}
    filename = f"{uin}_10.{extension}"
    
    # Формируем URL
    file_url = f"{GENERATED_FILES_BASE_URL}/{filename}"
    
    # Получаем артикул РМП по УИН
    item_id = get_item_id_by_uin(uin)
    
    # Сохраняем файл на РМП сервер через HTTP PUT
    def _write_to_rmp():
        try:
            logger.info(f"[STORAGE] Попытка записи файла {filename} на РМП сервер...")
            
            response = requests.put(
                file_url,
                data=file_data,
                auth=(USER, PASSWORD),
                timeout=30
            )
            
            if not response.ok:
                error_msg = f"HTTP {response.status_code} — {response.text}"
                logger.error(f"[STORAGE] Файл не записан! {error_msg}")
                raise Exception(error_msg)
            
            logger.info(f"[STORAGE] Файл {filename} успешно записан на РМП: {file_url}")
        
        except Exception as e:
            logger.error(f"[STORAGE] Ошибка записи на РМП: {e}")
            raise
    
    # Выполняем запись в отдельном потоке
    await asyncio.to_thread(_write_to_rmp)
    
    logger.info(f"[STORAGE] URL: {file_url}, Id: {item_id}")
    
    return file_url, item_id


async def delete_generated_file(
    uin: str,
    file_type: str  # "photo" or "video"
) -> bool:
    """
    Удаляет сгенерированный файл с РМП сервера через HTTP DELETE
    
    Args:
        uin: УИН изделия (16 цифр)
        file_type: "photo" или "video"
    
    Returns:
        True если удалено успешно, False если ошибка
    """
    # Определяем расширение
    extension = "jpg" if file_type == "photo" else "mp4"
    
    # Формируем имя файла и URL
    filename = f"{uin}_10.{extension}"
    file_url = f"{GENERATED_FILES_BASE_URL}/{filename}"
    
    # Удаляем файл с РМП сервера через HTTP DELETE
    def _delete_from_rmp():
        try:
            logger.info(f"[STORAGE] Удаление файла {filename} с РМП сервера...")
            
            response = requests.delete(
                file_url,
                auth=(USER, PASSWORD),
                timeout=30
            )
            
            # Успешные коды: 200 (OK), 204 (No Content), 404 (Not Found - уже удалён)
            if response.status_code in [200, 204, 404]:
                logger.info(f"[STORAGE] Файл {filename} удалён с РМП: {file_url}")
                return True
            else:
                error_msg = f"HTTP {response.status_code} — {response.text}"
                logger.error(f"[STORAGE] Файл не удалён! {error_msg}")
                return False
        
        except Exception as e:
            logger.error(f"[STORAGE] Ошибка удаления с РМП: {e}")
            return False
    
    # Выполняем удаление в отдельном потоке
    return await asyncio.to_thread(_delete_from_rmp)

