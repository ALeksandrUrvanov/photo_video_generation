import os
import sys
import pandas as pd
import re
from pathlib import Path
from typing import Optional, Dict, List
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.photo_gen_tracker import get_generated_files_by_uin

logger = logging.getLogger(__name__)

# Пути к данным
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / 'data'
ITEMS_FILE = DATA_DIR / 'items_out.csv'
RMP_FILE = DATA_DIR / 'rmp_out.csv'


def get_item_info(uin: str) -> Optional[Dict]:
    """
    Получить информацию об изделии по УИН
    
    Args:
        uin: УИН изделия (16 цифр)
        
    Returns:
        Словарь с информацией об изделии или None если не найдено
        {
            "uin": "6432400520931660",
            "item_type": "Подвеска с синтетическим камнем",
            "gender": "Женский",
            "weight": "3.05",
            "price_regular": "15000",
            "discount": "25",
            "price_sale": "11250",
            "item_photos": [
                "https://rmp.example.com/xxx_1.jpg",
                "https://rmp.example.com/xxx_2.jpg"
            ],
            "has_generated_photo": False,
            "has_generated_video": False
        }
    """
    try:
        # Проверка наличия файлов
        if not ITEMS_FILE.exists():
            logger.error(f"Файл не найден: {ITEMS_FILE}")
            return None
        
        if not RMP_FILE.exists():
            logger.error(f"Файл не найден: {RMP_FILE}")
            return None
        
        # Загрузка данных из items_out.csv
        df_items = pd.read_csv(ITEMS_FILE)
        
        # Конвертируем УИН в int для поиска (в CSV хранится как число)
        uin_int = int(uin)
        
        # Поиск по УИН
        item = df_items[df_items['UIN'] == uin_int]
        
        if item.empty:
            logger.warning(f"Изделие с УИН {uin} не найдено в items_out.csv")
            return None
        
        # Извлечение данных
        item_row = item.iloc[0]
        item_type = item_row['Title']
        weight = str(item_row['Weight'])
        item_id = item_row['Id']

        # Загрузка данных из rmp_out.csv
        df_rmp = pd.read_csv(RMP_FILE)
        rmp_item = df_rmp[df_rmp['Id'] == item_id]

        # Цена со скидкой только из РМП (полная цена). Цена без скидки — из Description (РМП). Без fallback на 1С.
        item_photos = []
        price_regular = None
        discount = None
        gender = None
        price_sale = None

        if not rmp_item.empty:
            rmp_row = rmp_item.iloc[0]
            # Цена со скидкой только из РМП
            if 'Price' in rmp_row.index and pd.notna(rmp_row.get('Price')):
                try:
                    ps = str(rmp_row['Price']).replace(' ', '').replace(',', '').strip()
                    if ps.isdigit():
                        price_sale = int(ps)
                except (ValueError, TypeError):
                    pass

            # Извлечение фото
            image_urls = rmp_row['ImageUrls']
            if pd.notna(image_urls):
                item_photos = [url.strip() for url in str(image_urls).split('|')]

            # Извлечение гендера
            gender_value = rmp_row.get('Gender', '')
            if pd.notna(gender_value) and str(gender_value).strip():
                gender_str = str(gender_value).strip().lower()
                if 'муж' in gender_str:
                    gender = 'Мужской'
                else:
                    gender = 'Женский'
            else:
                gender = 'Женский'

            # Цена без скидки из HTML Description (РМП)
            description = rmp_row.get('Description', '')
            if pd.notna(description):
                match = re.search(r'Цена без учета скидки:\s*([\d\s.,]+)', str(description))
                if match:
                    price_str = match.group(1).replace(' ', '').replace('.', '').replace(',', '').strip()
                    if price_str.isdigit():
                        price_regular = int(price_str)
                        if price_regular > 0 and price_sale is not None:
                            discount = int(((price_regular - price_sale) / price_regular) * 100)
        
        # Проверка возможности генерации (нужны исходные фото)
        can_generate_photo = len(item_photos) > 0
        
        # Проверка наличия сгенерированных фото/видео
        # Проверяем ТОЛЬКО в photo_gen.csv - это единственный источник правды о сгенерированных файлах
        # Сгенерированные файлы хранятся на media.example.com и НЕ попадают в rmp_out.csv
        # (в rmp_out.csv только исходные фото с rmp.example.com)
        
        generated_files = get_generated_files_by_uin(uin)
        has_generated_photo = bool(generated_files.get('photo_url'))
        has_generated_video = bool(generated_files.get('video_url'))
        
        result = {
            "uin": uin,
            "item_type": item_type,
            "gender": gender,
            "weight": weight,
            "price_regular": str(price_regular) if price_regular is not None else None,
            "discount": str(discount) if discount is not None else None,
            "price_sale": str(price_sale) if price_sale is not None else None,
            "item_photos": item_photos,
            "has_generated_photo": has_generated_photo,
            "has_generated_video": has_generated_video,
            "can_generate_photo": can_generate_photo
        }
        
        logger.info(f"Информация по УИН {uin} получена успешно")
        return result
        
    except Exception as e:
        logger.exception(f"Ошибка получения информации по УИН {uin}: {e}")
        return None

