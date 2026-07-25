"""
Скрипт для поиска тестовых УИНов с фото в разных ценовых категориях
"""
import pandas as pd
import re
from pathlib import Path
from config.config import VIDEO_PRICE_THRESHOLD

# Пути к данным
BASE_DIR = Path(__file__).parent / 'database' / 'data'
ITEMS_FILE = BASE_DIR / 'items_out.csv'
RMP_FILE = BASE_DIR / 'rmp_out.csv'

def extract_price_regular(description):
    """Извлечь цену БЕЗ скидки из HTML Description"""
    if pd.isna(description):
        return None
    # Ищем цену, учитывая разделители (пробелы, точки, запятые): "5 390", "28.380", "100,500"
    match = re.search(r'Цена без учета скидки:\s*([\d\s.,]+)', str(description))
    if match:
        # Убираем все разделители (пробелы, точки, запятые)
        price_str = match.group(1).replace(' ', '').replace('.', '').replace(',', '').strip()
        if price_str.isdigit():
            return int(price_str)
    return None

def find_test_uins():
    """Найти УИНы с фото в разных ценовых категориях"""
    
    # Загрузка данных
    df_items = pd.read_csv(ITEMS_FILE)
    df_rmp = pd.read_csv(RMP_FILE)
    
    # Извлекаем цены БЕЗ скидки из rmp_out.csv
    df_rmp['PriceRegular'] = df_rmp['Description'].apply(extract_price_regular)
    
    # Объединяем данные
    df_merged = df_items.merge(df_rmp[['Id', 'PriceRegular']], on='Id', how='left')
    
    # Определяем цену для сравнения (приоритет у цены БЕЗ скидки)
    df_merged['ComparePrice'] = df_merged['PriceRegular'].fillna(df_merged['Price'])
    
    # Фильтруем только изделия с фото
    df_with_photos = df_merged[df_merged['Id'].isin(df_rmp['Id'].unique())]
    
    # Дешевые (до VIDEO_PRICE_THRESHOLD)
    cheap = df_with_photos[df_with_photos['ComparePrice'] < VIDEO_PRICE_THRESHOLD].sort_values('ComparePrice')
    
    # Дорогие (от VIDEO_PRICE_THRESHOLD)
    expensive = df_with_photos[df_with_photos['ComparePrice'] >= VIDEO_PRICE_THRESHOLD].sort_values('ComparePrice')
    
    print(f"Всего изделий: {len(df_items)}")
    print(f"Изделий с фото: {len(df_with_photos)}")
    print(f"Изделий для генерации видео: {len(expensive)}")
    print()
    
    print(f"=== ДЕШЕВЫЕ (< {VIDEO_PRICE_THRESHOLD:,}) ===")
    print(cheap[['UIN', 'Title', 'Price', 'PriceRegular']].head(10))
    print()
    
    print(f"=== ДОРОГИЕ (≥ {VIDEO_PRICE_THRESHOLD:,}) ===")
    print(expensive[['UIN', 'Title', 'Price', 'PriceRegular']].head(10))
    print()

if __name__ == "__main__":
    find_test_uins()
