"""
Скачать {кабинет}_in.csv с сервера 1С и сохранить в database/data/
Чтобы локально посмотреть, откуда берётся колонка Price (цена со скидкой).

Запуск из корня проекта:
  python fetch_cabinet_in_csv.py

Требуется database/data/avito_cabinets.xlsx со списком кабинетов.
URL: https://data.example.com/{кабинет}_in.csv
"""
import sys
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / 'database' / 'data'
PACH_IN_OLD = 'https://data.example.com/'


def main():
    cabinets_path = DATA_DIR / 'avito_cabinets.xlsx'
    if not cabinets_path.exists():
        print(f"Ошибка: не найден {cabinets_path}")
        return 1

    df_cab = pd.read_excel(cabinets_path, header=None)
    cabinets = list(set(df_cab[0].astype(str).str.strip()))
    print(f"Кабинетов в avito_cabinets.xlsx: {len(cabinets)}")
    print(f"Сохраняем в: {DATA_DIR}")
    print("-" * 60)

    saved = []
    for cab in cabinets:
        url = f"{PACH_IN_OLD.rstrip('/')}/{cab}_in.csv"
        try:
            r = requests.get(url, timeout=30)
            if r.status_code != 200:
                print(f"  {cab}: HTTP {r.status_code} — пропуск")
                continue
            out_path = DATA_DIR / f"{cab}_in.csv"
            out_path.write_text(r.text, encoding='utf-8')
            n = len(r.text.splitlines()) - 1  # без заголовка
            print(f"  OK {cab}: {out_path.name} ({n} строк)")
            saved.append((cab, out_path))
        except Exception as e:
            print(f"  {cab}: ошибка — {e}")

    if saved:
        cab0, path0 = saved[0]
        df = pd.read_csv(path0)
        cols = list(df.columns)
        print("-" * 60)
        print(f"Колонки в {path0.name}: {cols}")
        if 'Price' in df.columns:
            print(f"Пример цен (Price), первые 5: {df['Price'].head().tolist()}")
        print()
        print("Цена со скидкой в боте берётся из колонки Price в этих файлах.")
        print("Откройте любой *_in.csv в database/data/ и проверьте значения.")
    else:
        print("Ни один файл не удалось скачать. Проверьте URL и доступ.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
