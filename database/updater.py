import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config.config import USER, PASSWORD

# Настройка логирования
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / 'data'

# Логи в stdout для Docker
logging.basicConfig(
    level=logging.INFO,
    format='[DB_UPDATER] %(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


# URLs
PACH_IN_OLD = 'https://data.example.com/'  # Выгрузка из 1С
PACH_HTTP = 'https://media.example.com/'  # Выгрузка РМП


def get_cabinets_list():
    """Получить список кабинетов из avito_cabinets.xlsx"""
    try:
        cabinets_path = DATA_DIR / 'avito_cabinets.xlsx'
        df_cabinets = pd.read_excel(cabinets_path, header=None)
        cabinets_list = list(set(df_cabinets[0]))
        logger.info(f"Загружено кабинетов: {len(cabinets_list)}")
        return cabinets_list
    except Exception as e:
        logger.error(f"Ошибка чтения avito_cabinets.xlsx: {e}")
        return []


def download_and_process_items_data():
    """
    Скачать и обработать данные из 1С (items_out.csv).
    Принимаются только файлы с Last-Modified = сегодня (UTC).
    """
    logger.info("=" * 80)
    logger.info("Начало обновления items_out.csv (данные из 1С)")
    logger.info("=" * 80)
    
    cabinets = get_cabinets_list()
    if not cabinets:
        logger.error("Список кабинетов пуст!")
        return False
    
    list_df_all = []
    list_df_cabinets = []
    today_utc = datetime.now(timezone.utc).date()
    
    session = requests.Session()
    
    for cab in cabinets:
        try:
            url = f'{PACH_IN_OLD}{cab}_in.csv'
            logger.info(f"Загрузка: {url}")
            
            r = session.get(url, timeout=30)
            
            if r.status_code != 200:
                logger.error(f"Не удалось получить файл {cab}_in.csv - HTTP {r.status_code}")
                continue
            
            last_modified = r.headers.get('last-modified')
            if not last_modified:
                logger.error(f"Нет заголовка Last-Modified у файла: {cab}_in.csv")
                continue
            dt = pd.to_datetime(last_modified, errors='coerce')
            if pd.isna(dt):
                logger.error(f"Не удалось распознать дату Last-Modified у файла: {cab}_in.csv ({last_modified})")
                continue
            if dt.date() != today_utc:
                logger.info(f"Файл {cab}_in.csv не за сегодня ({dt.date()} != {today_utc}), пропуск")
                continue
            
            # Сохраняем сырой файл в data/items_in/ для просмотра
            items_in_dir = DATA_DIR / 'items_in'
            items_in_dir.mkdir(parents=True, exist_ok=True)
            (items_in_dir / f'{cab}_in.csv').write_text(r.text, encoding='utf-8')
            
            df = pd.read_csv(StringIO(r.text))
            logger.info(f"Файл {cab}_in.csv загружен: {df.shape[0]} строк")
            
            # Отбираем нужные столбцы
            columns_needed = ['ImageUrls', 'Title', 'Weight', 'Price', 'Id']
            missing_cols = [col for col in columns_needed if col not in df.columns]
            if missing_cols:
                logger.error(f"Отсутствуют столбцы в {cab}_in.csv: {missing_cols}")
                continue
            
            df = df[columns_needed].copy()
            
            # Создание столбца с УИН (из ImageUrls)
            # Формат: https://data.example.com/0764000262700004_63895698918250.jpg
            #                                                  ^^^^^^^^^^^^^^^^ УИН (16 цифр)
            try:
                df['UIN'] = df['ImageUrls'].apply(lambda x: x[28:44] if isinstance(x, str) and len(x) > 44 else '')
            except Exception as e:
                logger.error(f"Ошибка извлечения УИН из {cab}_in.csv: {e}")
                df['UIN'] = ''
            
            # Добавляем номер кабинета
            df['Cabinet'] = cab
            
            # Удаляем ImageUrls (не нужен в items_out)
            df.drop('ImageUrls', axis=1, inplace=True)
            
            # Упорядочиваем колонки: Id, UIN, Cabinet, Title, Weight, Price
            df = df[['Id', 'UIN', 'Cabinet', 'Title', 'Weight', 'Price']]
            
            list_df_all.append(df)
            list_df_cabinets.append(cab)
            
        except Exception as e:
            logger.exception(f"Ошибка обработки кабинета {cab}: {e}")
            continue
    
    logger.info(f"Успешно загружены кабинеты: {list_df_cabinets}")
    
    if not list_df_all:
        logger.warning("Нет данных для сохранения в items_out.csv")
        return False
    
    # Объединяем все кабинеты
    try:
        df_all = pd.concat(list_df_all, ignore_index=True)
        logger.info(f"Объединено строк: {df_all.shape[0]}")
        
        # Сохраняем в items_out.csv
        output_path = DATA_DIR / 'items_out.csv'
        df_all.to_csv(output_path, index=False)
        logger.info(f"Файл сохранён: {output_path} ({df_all.shape[0]} строк)")
        
        return True
        
    except Exception as e:
        logger.exception(f"Ошибка объединения/сохранения items_out.csv: {e}")
        return False


def download_and_process_rmp_data():
    """
    Скачать и обработать данные РМП (rmp_out.csv).
    Принимаются только файлы с Last-Modified = сегодня (UTC).
    """
    logger.info("=" * 80)
    logger.info("Начало обновления rmp_out.csv (данные РМП)")
    logger.info("=" * 80)
    
    cabinets = get_cabinets_list()
    if not cabinets:
        logger.error("Список кабинетов пуст!")
        return False
    
    list_df_all = []
    list_df_cabinets = []
    today_utc = datetime.now(timezone.utc).date()
    
    session = requests.Session()
    
    for cab in cabinets:
        try:
            filename = f'{cab}_rmp_out.csv'
            url = f'{PACH_HTTP}{filename}'
            logger.info(f"Загрузка: {url}")
            
            r = session.get(url, auth=(USER, PASSWORD), timeout=30)
            
            if r.status_code != 200:
                logger.error(f"Не удалось получить файл {filename} - HTTP {r.status_code}")
                continue
            
            last_modified = r.headers.get('last-modified')
            if not last_modified:
                logger.error(f"Нет заголовка Last-Modified у файла: {filename}")
                continue
            dt = pd.to_datetime(last_modified, errors='coerce')
            if pd.isna(dt):
                logger.error(f"Не удалось распознать дату Last-Modified у файла: {filename} ({last_modified})")
                continue
            if dt.date() != today_utc:
                logger.info(f"Файл {filename} не за сегодня ({dt.date()} != {today_utc}), пропуск")
                continue
            
            rmp_dir = DATA_DIR / 'rmp'
            rmp_dir.mkdir(parents=True, exist_ok=True)
            rmp_path = rmp_dir / filename
            rmp_path.write_text(r.text, encoding='utf-8')
            logger.info(f"Сохранено: {rmp_path.resolve()}")
            
            # Парсим CSV
            df = pd.read_csv(StringIO(r.text))
            logger.info(f"Кабинет {cab}: загружено {df.shape[0]} строк")
            
            # Отбираем нужные столбцы (Price — полная цена со скидкой из РМП, для бота)
            columns_needed = ['Id', 'ImageUrls', 'Description', 'Gender', 'Price']
            missing_cols = [col for col in columns_needed if col not in df.columns]
            if missing_cols:
                logger.error(f"Отсутствуют столбцы в {filename}: {missing_cols}")
                continue
            
            df = df[columns_needed].copy()
            
            list_df_all.append(df)
            list_df_cabinets.append(cab)
            
        except Exception as e:
            logger.exception(f"Ошибка обработки кабинета {cab}: {e}")
            continue
    
    logger.info(f"Успешно загружены кабинеты: {list_df_cabinets}")
    
    if not list_df_all:
        logger.warning("Нет данных для сохранения в rmp_out.csv")
        return False
    
    # Объединяем все кабинеты
    try:
        df_all = pd.concat(list_df_all, ignore_index=True)
        logger.info(f"Объединено строк: {df_all.shape[0]}")
        
        # Сохраняем в rmp_out.csv
        output_path = DATA_DIR / 'rmp_out.csv'
        df_all.to_csv(output_path, index=False)
        logger.info(f"Файл сохранён: {output_path} ({df_all.shape[0]} строк)")
        
        return True
        
    except Exception as e:
        logger.exception(f"Ошибка объединения/сохранения rmp_out.csv: {e}")
        return False


def run_full_update():
    """Полное обновление базы данных"""
    logger.info("=" * 80)
    logger.info(f"ЗАПУСК ПОЛНОГО ОБНОВЛЕНИЯ БД: {datetime.now()}")
    logger.info("=" * 80)
    
    success_items = download_and_process_items_data()
    success_rmp = download_and_process_rmp_data()
    
    logger.info("=" * 80)
    if success_items and success_rmp:
        logger.info("Обновление БД завершено успешно!")
    elif success_items:
        logger.warning("Обновление завершено частично: items_out.csv OK, rmp_out.csv FAILED")
    elif success_rmp:
        logger.warning("Обновление завершено частично: items_out.csv FAILED, rmp_out.csv OK")
    else:
        logger.error("Обновление БД провалилось!")
    logger.info("=" * 80)
    
    return success_items and success_rmp


if __name__ == "__main__":
    print("Запуск обновления базы данных...")
    print(f"Данные будут сохранены в: {DATA_DIR}")
    print("Принимаются только файлы с Last-Modified = сегодня (UTC)")
    print("-" * 80)
    
    result = run_full_update()
    
    if result:
        print("\nОбновление завершено успешно!")
        print(f"Проверьте файлы:")
        print(f"  - {DATA_DIR / 'items_out.csv'}")
        print(f"  - {DATA_DIR / 'rmp_out.csv'}")
    else:
        print("\nОбновление завершилось с ошибками!")
        print("Смотрите логи выше")

