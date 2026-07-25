"""
Проверка обогащения: для каждого Id из photo_gen по кабинету проверяем:
1. В _out.csv у этого Id есть наша ссылка на фото в ImageUrls.
2. Если в photo_gen у этого Id заполнен LivePhoto (видео), то в _out.csv в столбце LivePhoto
   тоже должна быть эта ссылка.

Не требуем видео у всех: если цена < 50000, генерируется только фото — проверяем только то,
что есть в photo_gen.

Запуск: python check_enrichment.py
Файлы в корне: 111446793_rmp_out.csv, 111446793_out.csv
photo_gen: database/data/photo_gen_local.csv (или photo_gen.csv)
"""
import pandas as pd
from pathlib import Path

BASE = Path(__file__).parent
CABINET = '111446793'
RMP_PATH = BASE / f'{CABINET}_rmp_out.csv'
OUT_PATH = BASE / f'{CABINET}_out.csv'
PHOTO_GEN_PATH = BASE / 'database' / 'data' / 'photo_gen_local.csv'
if not PHOTO_GEN_PATH.exists():
    PHOTO_GEN_PATH = BASE / 'database' / 'data' / 'photo_gen.csv'


def norm_id(x) -> str:
    """Нормализация Id для сравнения (строка, без пробелов)."""
    if pd.isna(x):
        return ''
    return str(x).strip()


def main():
    print('=== ПРОВЕРКА ОБОГАЩЕНИЯ (по Id из photo_gen) ===')
    print(f'Кабинет: {CABINET}')
    print(f'RMP: {RMP_PATH.name}, OUT: {OUT_PATH.name}, photo_gen: {PHOTO_GEN_PATH.name}')
    print('Правила: у каждого Id в OUT должно быть наше фото с суффиксом _10 в ImageUrls;')
    print('         в OUT должна быть колонка LivePhoto; если в photo_gen у Id есть видео — в OUT должен быть LivePhoto.')
    print()

    if not RMP_PATH.exists() or not OUT_PATH.exists():
        print('Ошибка: файлы _rmp_out.csv или _out.csv не найдены в корне проекта.')
        return
    if not PHOTO_GEN_PATH.exists():
        print('Ошибка: photo_gen не найден:', PHOTO_GEN_PATH)
        return

    rmp = pd.read_csv(RMP_PATH, dtype={'Id': str}, low_memory=False)
    out = pd.read_csv(OUT_PATH, dtype={'Id': str}, low_memory=False)
    gen = pd.read_csv(PHOTO_GEN_PATH, dtype={'Id': str, 'Cabinet': str})

    if 'Id' not in rmp.columns or 'Id' not in out.columns:
        print('Ошибка: в RMP или OUT нет колонки Id.')
        return

    # Проверка: в OUT обязательно должна быть колонка с видео
    if 'LivePhoto' not in out.columns:
        print('Ошибка: в OUT нет колонки LivePhoto (колонка с видео обязательна).')
        return
    print('Колонка LivePhoto в OUT: есть')
    print()

    gen_cab = gen[gen['Cabinet'] == CABINET]
    out['_id'] = out['Id'].fillna('').astype(str).str.strip()

    print(f'Строк в RMP: {len(rmp)}, в OUT: {len(out)}')
    print(f'В photo_gen для кабинета {CABINET}: {len(gen_cab)} записей')
    print()

    ok = 0
    fail = 0
    missing_in_out = []
    # Список для вывода: Id, ссылка на фото, ссылка на видео (если есть) из OUT
    out_rows = []

    for _, row in gen_cab.iterrows():
        id_val = norm_id(row['Id'])
        if not id_val:
            continue
        expected_img = str(row.get('ImageUrls') or '').strip()
        expected_live = str(row.get('LivePhoto') or '').strip()
        has_video_in_gen = bool(expected_live and 'future.lombardlombard' in expected_live)

        row_out = out[out['_id'] == id_val]
        if row_out.empty:
            missing_in_out.append(id_val)
            fail += 1
            print(f'  FAIL Id={id_val}: записи нет в OUT')
            continue

        img_out = str(row_out['ImageUrls'].iloc[0] or '')
        live_out = str(row_out['LivePhoto'].iloc[0] or '')

        # Фото должно быть с суффиксом _10 (наше сгенерированное: ..._10.jpg)
        has_our_photo = 'media.example.com' in img_out and '_10.jpg' in img_out
        has_our_video_in_out = 'media.example.com' in live_out and '_10.mp4' in live_out

        # 1) У каждого Id должно быть наше фото с суффиксом _10 в OUT
        if not has_our_photo:
            fail += 1
            if 'media.example.com' in img_out and '_10.jpg' not in img_out:
                print(f'  FAIL Id={id_val}: в OUT есть наша ссылка на фото, но без суффикса _10 в ImageUrls')
            else:
                print(f'  FAIL Id={id_val}: в OUT нет нашей ссылки на фото (_10.jpg) в ImageUrls')
            continue

        # 2) Если в photo_gen у этого Id есть видео — в OUT должен быть LivePhoto
        if has_video_in_gen and not has_our_video_in_out:
            fail += 1
            print(f'  FAIL Id={id_val}: в photo_gen есть видео, в OUT столбец LivePhoto пуст или без нашей ссылки')
            continue

        ok += 1
        if has_video_in_gen:
            print(f'  OK Id={id_val}: в OUT есть наше фото и видео')
        else:
            print(f'  OK Id={id_val}: в OUT есть наше фото (видео в photo_gen нет — так и должно быть)')

        # Достаём нашу ссылку на фото (_10.jpg) и видео (_10.mp4) из OUT
        photo_url = ''
        for part in img_out.split('|'):
            part = part.strip()
            if 'media.example.com' in part and '_10.jpg' in part:
                photo_url = part
                break
        video_url = ''
        if live_out and 'media.example.com' in live_out and '_10.mp4' in live_out:
            video_url = live_out.strip()
        out_rows.append((id_val, photo_url, video_url))

    print()
    print('=== КАК В НАШЕМ ФАЙЛЕ (из 111446793_out.csv) ===')
    print('Id, ссылка на фото, ссылка на видео (если есть)')
    print()
    for id_val, photo_url, video_url in out_rows:
        print(id_val)
        print('  фото:', photo_url)
        print('  видео:', video_url if video_url else '(нет)')
        print()

    print('=== ИТОГ ===')
    print(f'Совпадений: {ok}, расхождений: {fail}')
    if missing_in_out:
        print(f'Id из photo_gen, которых нет в OUT: {missing_in_out[:10]}' + ('...' if len(missing_in_out) > 10 else ''))
    if fail == 0 and not missing_in_out:
        print('Запись обогащения корректна.')
    else:
        print('Есть расхождения — проверьте сопоставление по Id (RMP/OUT и photo_gen).')


if __name__ == '__main__':
    main()
