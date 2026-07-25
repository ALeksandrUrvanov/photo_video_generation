"""
Модуль обогащения файлов РМП сгенерированными фото/видео по кабинетам

Процесс:
1. Читает из database/data/rmp/ файлы <cab>_rmp_out.csv (сохранённые в 06:05)
2. Загружает photo_gen.csv (Cabinet,UIN,Id,ImageUrls,LivePhoto) — Id берём из photo_gen
3. Для каждого кабинета: обогащает ImageUrls (добавляет наше фото через |), добавляет столбец LivePhoto по Id
4. Сохраняет <cab>_out.csv на сервер (полный формат РМП + LivePhoto)

Запускается ежедневно в 3:10 UTC (6:10 МСК) после обновления БД
"""
import asyncio
import logging
import sys
from pathlib import Path
from typing import Dict

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.config import USER, PASSWORD

# Настройка логирования
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('[SCHEDULER] %(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    logger.propagate = False

# Пути и URL
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / 'data'
RMP_DIR = DATA_DIR / 'rmp'
PHOTO_GEN_CSV = DATA_DIR / 'photo_gen.csv'
RMP_SERVER_URL = 'https://media.example.com/'


def _enrich_cabinet_df(df_rmp: pd.DataFrame, id_to_photo: Dict[str, str], id_to_video: Dict[str, str]) -> pd.DataFrame:
    """
    Обогатить DataFrame РМП: добавить наши фото в ImageUrls, заполнить LivePhoto по Id (артикул).
    В выгрузке РМП колонка UIN пустая, сопоставление идёт по Id.
    """
    df = df_rmp.copy()
    if 'Id' not in df.columns:
        df['LivePhoto'] = ''
        return df

    # Нормализуем Id для сопоставления (строка, без пробелов)
    df['_id'] = df['Id'].fillna('').astype(str).str.strip()

    # Обогащаем ImageUrls
    def append_photo(existing: str, id_val: str) -> str:
        our = id_to_photo.get(id_val, '') if id_val else ''
        if not our:
            return existing if pd.notna(existing) and str(existing).strip() else ''
        existing = (existing if pd.notna(existing) and str(existing).strip() else '') or ''
        return f"{existing}|{our}" if existing else our

    df['ImageUrls'] = df.apply(
        lambda r: append_photo(r['ImageUrls'], r['_id']),
        axis=1
    )

    # Добавляем столбец LivePhoto
    df['LivePhoto'] = df['_id'].map(lambda i: id_to_video.get(i, '') if i else '')
    df.drop(columns=['_id'], inplace=True)

    return df


def save_to_server(df: pd.DataFrame, cabinet: str) -> bool:
    """Сохранить обогащённый файл <cab>_out.csv на сервер."""
    url = f'{RMP_SERVER_URL}{cabinet}_out.csv'
    try:
        csv_data = df.to_csv(index=False, encoding='utf-8')
        response = requests.put(
            url,
            data=csv_data.encode('utf-8'),
            auth=(USER, PASSWORD),
            headers={'Content-Type': 'text/csv; charset=utf-8'},
            timeout=60
        )
        response.raise_for_status()
        logger.info(f"Сохранён файл {cabinet}_out.csv на сервер")
        return True
    except Exception as e:
        logger.error(f"Ошибка сохранения {cabinet}_out.csv на сервер: {e}")
        return False


async def enrich_all_cabinets() -> Dict[str, int]:
    """
    Обогатить файлы РМП для всех кабинетов и выгрузить <cab>_out.csv на сервер.
    Читает _rmp_out.csv из database/data/rmp/ (сохранённые в 06:05).
    """
    logger.info("=" * 80)
    logger.info("НАЧАЛО ОБОГАЩЕНИЯ ФАЙЛОВ ПО КАБИНЕТАМ")
    logger.info("=" * 80)

    if not RMP_DIR.exists() or not list(RMP_DIR.glob('*_rmp_out.csv')):
        logger.warning("Папка rmp/ пуста или не найдена. Сначала выполните обновление БД (06:05).")
        return {'success': 0, 'failed': 0, 'total_photos': 0, 'total_videos': 0}

    # Список кабинетов по файлам в rmp/
    rmp_files = list(RMP_DIR.glob('*_rmp_out.csv'))
    cabinets = [f.stem.replace('_rmp_out', '') for f in rmp_files]
    logger.info(f"Кабинетов в rmp/: {len(cabinets)}")

    if not PHOTO_GEN_CSV.exists():
        logger.warning("Файл photo_gen.csv не найден. Обогащение только структурой РМП (без наших фото/видео).")
        df_gen = pd.DataFrame(columns=['Cabinet', 'UIN', 'Id', 'ImageUrls', 'LivePhoto'])
    else:
        df_gen = pd.read_csv(PHOTO_GEN_CSV, dtype={'UIN': str, 'Cabinet': str, 'Id': str})
        if 'Id' not in df_gen.columns:
            df_gen['Id'] = ''

    total_photos = (df_gen['ImageUrls'].fillna('').astype(str).str.strip() != '').sum()
    total_videos = (df_gen['LivePhoto'].fillna('').astype(str).str.strip() != '').sum()
    logger.info(f"Загружен photo_gen.csv: {len(df_gen)} записей (фото: {total_photos}, видео: {total_videos}), Id из photo_gen")

    success_count = 0
    failed_count = 0

    for cabinet in cabinets:
        rmp_path = RMP_DIR / f'{cabinet}_rmp_out.csv'
        if not rmp_path.exists():
            continue
        logger.info(f"Обработка кабинета {cabinet}...")

        try:
            # Читаем полный RMP-файл (все столбцы)
            df_rmp = await asyncio.to_thread(
                pd.read_csv,
                rmp_path,
                dtype={'UIN': str},
                low_memory=False,
                encoding='utf-8'
            )

            if 'Id' not in df_rmp.columns:
                logger.warning(f"  В файле {cabinet}_rmp_out.csv нет столбца Id, пропуск обогащения.")
                df_enriched = df_rmp.copy()
                df_enriched['LivePhoto'] = ''
            else:
                # Id берём из photo_gen.csv (Cabinet,UIN,Id,ImageUrls,LivePhoto)
                df_gen_cab = df_gen[df_gen['Cabinet'] == cabinet]
                id_to_photo = {}
                id_to_video = {}
                for _, row in df_gen_cab.iterrows():
                    id_val = (row.get('Id') or '')
                    if isinstance(id_val, float) and pd.isna(id_val):
                        id_val = ''
                    id_val = str(id_val).strip()
                    if not id_val:
                        continue
                    if row.get('ImageUrls') and str(row['ImageUrls']).strip():
                        id_to_photo[id_val] = str(row['ImageUrls']).strip()
                    if row.get('LivePhoto') and str(row['LivePhoto']).strip():
                        id_to_video[id_val] = str(row['LivePhoto']).strip()

                logger.info(f"  Строк в RMP: {len(df_rmp)}, обогащаем по Id из photo_gen: фото {len(id_to_photo)}, видео {len(id_to_video)}")

                df_enriched = await asyncio.to_thread(
                    _enrich_cabinet_df,
                    df_rmp,
                    id_to_photo,
                    id_to_video
                )

            saved = await asyncio.to_thread(save_to_server, df_enriched, cabinet)
            if saved:
                success_count += 1
            else:
                failed_count += 1

        except Exception as e:
            logger.exception(f"Ошибка обработки кабинета {cabinet}: {e}")
            failed_count += 1

    logger.info("=" * 80)
    logger.info("ИТОГОВАЯ СТАТИСТИКА:")
    logger.info("=" * 80)
    logger.info(f"Кабинетов обработано успешно: {success_count}")
    logger.info(f"Кабинетов с ошибками: {failed_count}")
    logger.info(f"Всего фото в реестре: {total_photos}")
    logger.info(f"Всего видео в реестре: {total_videos}")
    logger.info("=" * 80)

    return {
        'success': success_count,
        'failed': failed_count,
        'total_photos': total_photos,
        'total_videos': total_videos
    }


if __name__ == "__main__":
    print("Запуск обогащения файлов...")
    result = asyncio.run(enrich_all_cabinets())
    print(f"\nОбогащение завершено: {result}")
