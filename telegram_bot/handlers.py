import asyncio
import os
import sys
import tempfile
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, FSInputFile, URLInputFile
from aiogram.exceptions import TelegramAPIError

from telegram_bot.states import ItemStates
from telegram_bot.keyboards import (
    get_item_found_keyboard,
    get_photo_confirmation_keyboard,
    get_video_generation_keyboard,
    get_generate_photo_keyboard,
    get_video_confirmation_keyboard
)
from database.datamatrix_reader import decode_datamatrix
from database.item_info import get_item_info
from telegram_bot.api_client import api_client
from config.config import VIDEO_PRICE_THRESHOLD

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start - приветствие и инструкция"""
    await state.clear()
    
    await message.answer(
        "<b>Добро пожаловать!</b>\n\n"
        "Я бот для генерации контента компании <b>Ломбард</b>.\n\n"
        "<b>Начните работу прямо сейчас:</b>\n"
        "Отправьте фото бирки с DataMatrix кодом\n"
        "или введите УИН (16 цифр) вручную\n\n"
        "<b>Пример УИН:</b> <code>6432400463289151</code>\n\n"
        "Используйте /help для подробной инструкции",
        parse_mode="HTML"
    )
    await state.set_state(ItemStates.waiting_datamatrix)


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    await message.answer(
        "<b>Пошаговая инструкция:</b>\n\n"
        "<b>1.</b> Отправьте фото бирки с DataMatrix кодом или введите УИН (16 цифр) вручную\n\n"
        "<b>2.</b> Проверьте информацию об изделии (тип, вес, цена, наличие фото в РМП)\n\n"
        "<b>3.</b> Нажмите кнопку <b>Генерация</b> для начала работы\n\n"
        "<b>4.</b> Система загрузит исходные фото из РМП и покажет их вам\n\n"
        "<b>5.</b> Если ИИ фото уже существует - система покажет его автоматически\n"
        "Если нет - будет предложено сгенерировать новое\n\n"
        "<b>6.</b> После генерации фото вы можете:\n"
        "- <b>Утвердить</b> - сохранить результат и перейти к видео\n"
        "- <b>Перегенерировать</b> - создать новый вариант\n"
        "- <b>Удалить</b> - удалить сгенерированное фото с сервера\n\n"
        "<b>7.</b> После утверждения фото для дорогих изделий (≥50,000₽) будет предложена генерация видео\n\n"
        "<b>8.</b> Генерация видео происходит на основе утвержденного фото\n"
        "После завершения вы можете утвердить, перегенерировать или удалить видео\n\n"
        "<b>Важно:</b> Для генерации фото и видео исходные фото изделия должны быть загружены в РМП!",
        parse_mode="HTML"
    )


@router.message(ItemStates.waiting_datamatrix, F.photo | F.document)
async def handle_datamatrix_photo(message: Message, state: FSMContext, bot: Bot):
    """Обработчик получения фото бирки с DataMatrix"""
    
    status_msg = await message.answer("Распознаю DataMatrix код...")
    
    try:
        # Определяем тип файла (photo или document)
        if message.photo:
            photo = message.photo[-1]
            photo_file = await bot.get_file(photo.file_id)
        elif message.document:
            # Проверяем, что это изображение
            if not message.document.mime_type or not message.document.mime_type.startswith('image/'):
                await status_msg.edit_text(
                    "Пожалуйста, отправьте изображение (JPG, PNG)."
                )
                return
            photo_file = await bot.get_file(message.document.file_id)
        else:
            await status_msg.edit_text(
                "Не удалось обработать файл."
            )
            return
        
        # Сохраняем временно
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_file:
            await bot.download_file(photo_file.file_path, tmp_file.name)
            tmp_path = tmp_file.name
        
        # Распознаём DataMatrix (в отдельном потоке для асинхронности)
        uin = await asyncio.to_thread(decode_datamatrix, tmp_path)
        
        # Удаляем временный файл
        Path(tmp_path).unlink()
        
        if not uin:
            await status_msg.edit_text(
                "DataMatrix код не найден на фото.\n\n"
                "Убедитесь, что:\n"
                "- Бирка чёткая и без бликов\n"
                "- DataMatrix код (квадратный 2D) виден полностью\n\n"
                "Попробуйте ещё раз!"
            )
            return
        
        await status_msg.edit_text(f"УИН распознан: `{uin}`\n\nИщу в базе данных...", parse_mode="Markdown")
        
        # Получаем информацию из БД (в отдельном потоке для асинхронности)
        info = await asyncio.to_thread(get_item_info, uin)
        
        if not info:
            await status_msg.edit_text(
                f"Изделие с УИН `{uin}` не найдено в базе.\n\n"
                "Попробуйте другое изделие!",
                parse_mode="Markdown"
            )
            return
        
        # Формируем ответ с информацией об изделии
        response = (
            f"<b>Изделие найдено!</b>\n\n"
            f"УИН: <code>{info['uin']}</code>\n"
            f"Тип: {info['item_type']}\n"
            f"Вес: {info['weight']} г\n"
        )
        
        # Цена: со скидкой из РМП (если есть), иначе только цена без скидки из Description
        if info.get('price_sale') is not None:
            if info.get('price_regular') is not None and info.get('discount') is not None:
                response += (
                    f"Цена: {info['price_regular']} руб\n"
                    f"Скидка: {info['discount']}%\n"
                    f"Цена со скидкой: <b>{info['price_sale']} руб</b>\n"
                )
            else:
                response += f"Цена со скидкой: <b>{info['price_sale']} руб</b>\n"
        elif info.get('price_regular') is not None:
            response += f"Цена: <b>{info['price_regular']} руб</b>\n"
        
        response += f"Фото в РМП: {len(info['item_photos'])}\n"
        
        # Добавляем информацию о сгенерированном фото, если есть
        if info.get('has_generated_photo', False):
            response += f"Фото ИИ: 1\n"
        
        # Добавляем информацию о сгенерированном видео, если есть
        if info.get('has_generated_video', False):
            response += f"Видео ИИ: 1\n"
        
        await status_msg.edit_text(
            response,
            reply_markup=get_item_found_keyboard(uin),
            parse_mode="HTML"
        )
        
        # Сохраняем данные в state
        await state.update_data(
            uin=uin,
            item_info=info
        )
        await state.set_state(ItemStates.waiting_confirmation)
        
    except (TelegramAPIError, httpx.HTTPError, asyncio.TimeoutError, 
            ValueError, KeyError, AttributeError, OSError) as e:
        await status_msg.edit_text(
            f" Произошла ошибка при обработке фото:\n{str(e)}\n\n"
            "Попробуйте ещё раз!"
        )
        await state.set_state(ItemStates.waiting_datamatrix)


@router.callback_query(F.data.startswith("work_with_photos_"))
async def handle_work_with_photos(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки 'Генерация' - загружает все фото и показывает"""
    
    uin = callback.data.replace("work_with_photos_", "")
    data = await state.get_data()
    item_info = data.get('item_info', {})
    
    await callback.answer()
    
    # Инициализация переменных для cleanup в except блоке
    progress_msg = None
    ai_progress_msg = None
    
    try:
        # Проверка наличия фото в РМП
        item_photos = item_info.get('item_photos', [])
        
        if not item_photos:
            # Убираем только кнопки, оставляем информацию об изделии
            await callback.message.edit_reply_markup(reply_markup=None)
            
            # Отправляем предупреждение отдельным сообщением
            await callback.message.answer(
                "<b>ВНИМАНИЕ!</b>\n\n"
                "Для работы с фото необходимо <b>загрузить фотографии изделия в РМП</b>!\n\n"
                "После загрузки фото в РМП попробуйте снова.",
                parse_mode="HTML"
            )
            await state.set_state(ItemStates.waiting_datamatrix)
            return
        
        # Убираем кнопки из основного сообщения, оставляем информацию
        await callback.message.edit_reply_markup(reply_markup=None)
        
        # Показываем индикатор загрузки исходных фото
        progress_msg = await callback.message.answer(" Загружаю исходные фото из РМП...")
        
        # Определяем что нужно загрузить
        has_generated_photo = item_info.get('has_generated_photo', False)
        
        # Параллельная загрузка исходных фото
        logger.info(f"[WORK_WITH_PHOTOS] Загрузка {len(item_photos)} исходных фото для УИН {uin}")
        source_photos_bytes = await api_client.download_photos_parallel(item_photos)
        
        # Фильтруем успешно загруженные фото
        valid_photos = [(photo_bytes, url) for photo_bytes, url in zip(source_photos_bytes, item_photos) if photo_bytes]
        
        if not valid_photos:
            await progress_msg.edit_text(
                "Не удалось загрузить фото из РМП!\n\n"
                "Попробуйте позже."
            )
            await state.set_state(ItemStates.waiting_datamatrix)
            return
        
        logger.info(f"[WORK_WITH_PHOTOS] Успешно загружено {len(valid_photos)} из {len(item_photos)} фото")
        
        # Отправляем альбом с исходными фото
        from aiogram.types import BufferedInputFile, InputMediaPhoto
        
        media_group = []
        for i, (photo_bytes, url) in enumerate(valid_photos):
            caption = "Исходные фото из РМП" if i == 0 else None
            media_group.append(
                InputMediaPhoto(
                    media=BufferedInputFile(photo_bytes, filename=f"source_{i+1}.jpg"),
                    caption=caption
                )
            )
        
        await callback.message.answer_media_group(media_group)
        
        # Удаляем индикатор загрузки исходных фото
        await progress_msg.delete()
        
        # Если есть сгенерированное фото - показываем НОВЫЙ индикатор и загружаем
        if has_generated_photo:
            # Создаём НОВЫЙ индикатор для ИИ фото
            ai_progress_msg = await callback.message.answer(" Загружаю ИИ фото...")
            
            from database.photo_gen_tracker import get_generated_files_by_uin
            
            generated = get_generated_files_by_uin(uin)
            photo_url = generated.get('photo_url')
            
            if photo_url:
                logger.info(f"[WORK_WITH_PHOTOS] Загрузка ИИ фото: {photo_url}")
                
                ai_photo_bytes = await api_client.download_photo(photo_url)
                
                if ai_photo_bytes:
                    # Отправляем фото в Telegram (долгая операция)
                    await callback.message.answer_photo(
                        photo=BufferedInputFile(ai_photo_bytes, filename=f"{uin}_10.jpg"),
                        caption=(
                            f"<b>Сгенерированное фото</b>\n\n"
                            f" УИН: <code>{uin}</code>"
                        ),
                        parse_mode="HTML",
                        reply_markup=get_photo_confirmation_keyboard(uin)
                    )
                    
                    # Удаляем индикатор ПОСЛЕ отправки фото
                    await ai_progress_msg.delete()
                    
                    await state.update_data(generated_photo_url=photo_url)
                    await state.set_state(ItemStates.waiting_regeneration)
                else:
                    logger.error(f"[WORK_WITH_PHOTOS] Не удалось загрузить ИИ фото")
                    # Удаляем индикатор
                    await ai_progress_msg.delete()
                    # Предлагаем сгенерировать новое
                    await callback.message.answer(
                        "Не удалось загрузить существующее ИИ фото.\n\n"
                        "Доступна генерация нового фото!\n\n"
                        "Сгенерировать фото изделия на человеке?",
                        reply_markup=get_generate_photo_keyboard(uin),
                        parse_mode="HTML"
                    )
                    await state.set_state(ItemStates.waiting_confirmation)
            else:
                logger.warning(f"[WORK_WITH_PHOTOS] URL ИИ фото не найден для УИН {uin}")
                # Удаляем индикатор
                await ai_progress_msg.delete()
                # Предлагаем сгенерировать
                await callback.message.answer(
                    "<b>Доступна генерация фото!</b>\n\n"
                    "Сгенерировать фото изделия на человеке?",
                    reply_markup=get_generate_photo_keyboard(uin),
                    parse_mode="HTML"
                )
                await state.set_state(ItemStates.waiting_confirmation)
        else:
            # Нет сгенерированного фото - предлагаем сгенерировать (индикатор уже удалён)
            await callback.message.answer(
                "<b>Доступна генерация фото!</b>\n\n"
                "Сгенерировать фото изделия на человеке?",
                reply_markup=get_generate_photo_keyboard(uin),
                parse_mode="HTML"
            )
            await state.set_state(ItemStates.waiting_confirmation)
    
    except (TelegramAPIError, httpx.HTTPError, asyncio.TimeoutError, 
            ValueError, KeyError, AttributeError, OSError) as e:
        logger.error(f"[WORK_WITH_PHOTOS] Ошибка: {e}")
        try:
            # Пытаемся удалить индикаторы если они существуют
            if ai_progress_msg is not None:
                try:
                    await ai_progress_msg.delete()
                except (TelegramAPIError, AttributeError):
                    pass  # Сообщение уже удалено или недоступно
            if progress_msg is not None:
                try:
                    await progress_msg.delete()
                except (TelegramAPIError, AttributeError):
                    pass  # Сообщение уже удалено или недоступно
            
            await callback.message.answer(
                "Произошла ошибка при загрузке фото!\n\n"
                "Попробуйте позже."
            )
        except TelegramAPIError:
            pass  # Не удалось отправить уведомление об ошибке
        await state.set_state(ItemStates.waiting_datamatrix)


async def _generate_photo_common_logic(
    uin: str,
    callback: CallbackQuery,
    state: FSMContext,
    log_prefix: str = "GENERATION"
):
    """
    Общая логика генерации фото
    Используется в handle_generate_photo и handle_regenerate_photo
    """
    data = await state.get_data()
    item_info = data.get('item_info', {})
    
    await callback.answer()
    
    # Проверяем, есть ли текст в сообщении (текстовое сообщение или фото)
    if callback.message.text:
        # Текстовое сообщение - можем редактировать
        progress_msg = await callback.message.edit_text(
            "Генерирую фото...\n\n"
            "Это может занять 1-2 минуты, пожалуйста подождите..."
        )
    else:
        # Фото - удаляем и отправляем новое сообщение
        try:
            await callback.message.delete()
        except TelegramAPIError:
            pass  # Сообщение уже удалено
        progress_msg = await callback.message.answer(
            "Генерирую фото...\n\n"
            "Это может занять 1-2 минуты, пожалуйста подождите..."
        )
    
    try:
        # Получаем фото из item_info
        photos = item_info.get('item_photos', [])
        
        if not photos:
            await progress_msg.edit_text(
                "Ошибка: фотографии изделия не найдены в РМП!"
            )
            await state.set_state(ItemStates.waiting_datamatrix)
            return
        
        # Получаем тип изделия и гендер для промпта
        item_type = item_info.get('item_type', '')
        gender = item_info.get('gender', '')
        
        logger.info(f"[{log_prefix}] Запуск генерации фото для УИН {uin}, фото: {len(photos)}")
        if item_type:
            logger.info(f"[{log_prefix}] Тип изделия: {item_type}")
        if gender:
            logger.info(f"[{log_prefix}] Гендер: {gender}")
        
        # Запускаем генерацию только фото через FastAPI (синхронный результат)
        result = await api_client.generate_photo(
            uin=uin,
            photos=photos,
            item_type=item_type if item_type else None,
            gender=gender if gender else None
        )
        
        if not result:
            await progress_msg.edit_text(
                "Ошибка при генерации фото!\n\n"
                "Возможные причины:\n"
                "- FastAPI сервис недоступен\n"
                "- Проблема с сетью\n"
                "- Ошибка генерации AI\n\n"
                "Попробуйте позже или обратитесь к администратору."
            )
            await state.set_state(ItemStates.waiting_datamatrix)
            return
        
        photo_url = result.get('photo_url')
        
        if not photo_url:
            await progress_msg.edit_text(
                "Ошибка: URL фото не получен!"
            )
            await state.set_state(ItemStates.waiting_datamatrix)
            return
        
        logger.info(f"[{log_prefix}] Фото готово: {photo_url}")
        
        # Показываем что фото готово и начинается загрузка
        await progress_msg.edit_text(
            " Фото сгенерировано! Загружаю..."
        )
        
        # Скачиваем фото с РМП сервера для отправки в Telegram
        photo_bytes = await api_client.download_photo(photo_url)
        
        if not photo_bytes:
            await progress_msg.edit_text(
                "Ошибка: Не удалось загрузить сгенерированное фото!"
            )
            await state.set_state(ItemStates.waiting_datamatrix)
            return
        
        # Отправляем фото пользователю как BufferedInputFile (ДОЛГАЯ операция)
        from aiogram.types import BufferedInputFile
        
        await callback.message.answer_photo(
            photo=BufferedInputFile(
                photo_bytes,
                filename=f"{uin}_10.jpg"
            ),
            caption=(
                f"<b>Сгенерированное фото</b>\n\n"
                f" УИН: <code>{uin}</code>"
            ),
            parse_mode="HTML",
            reply_markup=get_photo_confirmation_keyboard(uin)
        )
        
        # Удаляем сообщение с прогрессом ПОСЛЕ отправки фото
        await progress_msg.delete()
        
        # Сохраняем в state
        await state.update_data(generated_photo_url=photo_url)
        await state.set_state(ItemStates.waiting_regeneration)
    
    except (TelegramAPIError, httpx.HTTPError, asyncio.TimeoutError, 
            ValueError, KeyError, AttributeError, OSError) as e:
        logger.error(f"[{log_prefix}] Ошибка генерации фото: {e}")
        try:
            if 'progress_msg' in locals():
                await progress_msg.edit_text(
                    "Произошла ошибка при генерации фото!\n\n"
                    "Попробуйте позже."
                )
            else:
                await callback.message.answer(
                    "Произошла ошибка при генерации фото!\n\n"
                    "Попробуйте позже."
                )
        except TelegramAPIError:
            pass  # Не удалось отправить уведомление об ошибке
        await state.set_state(ItemStates.waiting_datamatrix)


@router.callback_query(F.data.startswith("generate_photo_"))
async def handle_generate_photo(callback: CallbackQuery, state: FSMContext):
    """Обработчик генерации фото"""
    uin = callback.data.replace("generate_photo_", "")
    await _generate_photo_common_logic(uin, callback, state, "GENERATION")


@router.callback_query(F.data.startswith("confirm_photo_"))
async def handle_confirm_photo(callback: CallbackQuery, state: FSMContext):
    """Обработчик подтверждения фото"""
    
    uin = callback.data.replace("confirm_photo_", "")
    data = await state.get_data()
    item_info = data.get('item_info', {})
    generated_photo_url = data.get('generated_photo_url')
    
    await callback.answer(" Фото утверждено!")
    
    # Оставляем фото, убираем кнопки, меняем подпись
    await callback.message.edit_caption(
        caption=(
            f" <b>Фото утверждено!</b>\n\n"
            f" УИН: <code>{uin}</code>"
        ),
        parse_mode="HTML"
    )
    
    # Проверка, есть ли уже сгенерированное видео
    has_generated_video = item_info.get('has_generated_video', False)
    
    if has_generated_video:
        # Видео уже есть - загружаем и показываем
        from database.photo_gen_tracker import get_generated_files_by_uin
        
        generated = get_generated_files_by_uin(uin)
        video_url = generated.get('video_url')
        
        if video_url:
            logger.info(f"[CONFIRM] Загрузка существующего видео: {video_url}")
            
            # Показываем индикатор загрузки
            video_progress_msg = await callback.message.answer(" Загружаю ИИ видео...")
            
            video_bytes = await api_client.download_video(video_url)
            
            if video_bytes:
                from aiogram.types import BufferedInputFile
                # Отправляем как анимацию
                await callback.message.answer_animation(
                    animation=BufferedInputFile(video_bytes, filename=f"{uin}_10.mp4"),
                    caption=(
                        f"<b>Сгенерированное видео</b>\n\n"
                        f" УИН: <code>{uin}</code>"
                    ),
                    parse_mode="HTML",
                    reply_markup=get_video_confirmation_keyboard(uin)
                )
                
                # Удаляем индикатор
                await video_progress_msg.delete()
                
                await state.update_data(generated_video_url=video_url)
                await state.set_state(ItemStates.waiting_datamatrix)
                return
            else:
                # Не удалось загрузить видео
                await video_progress_msg.delete()
                logger.error(f"[CONFIRM] Не удалось загрузить видео для УИН {uin}")
    
    # Проверка цены для генерации видео: сначала цена без скидки, потом со скидкой, потом 0
    price_str = item_info.get('price_regular') or item_info.get('price_sale') or '0'
    
    price_str = str(price_str).replace(',', '').replace(' ', '').strip()
    
    try:
        price = int(price_str)
    except (ValueError, TypeError):
        price = 0
    
    logger.info(f"[CONFIRM] УИН {uin}, цена {price}, порог {VIDEO_PRICE_THRESHOLD}")
    
    if price >= VIDEO_PRICE_THRESHOLD:
        await callback.message.answer(
            f" <b>Цена изделия ≥ {VIDEO_PRICE_THRESHOLD:,}₽</b>\n\n"
            f"Доступна генерация видео!\n"
            f"Хотите сгенерировать видео?",
            reply_markup=get_video_generation_keyboard(uin),
            parse_mode="HTML"
        )
        await state.set_state(ItemStates.waiting_datamatrix)
    else:
        await callback.message.answer(
            "Работа с изделием завершена!\n\n"
            "Отправьте новую бирку или введите УИН вручную для нового запроса."
        )
        await state.set_state(ItemStates.waiting_datamatrix)


@router.callback_query(F.data.startswith("regenerate_photo_"))
async def handle_regenerate_photo(callback: CallbackQuery, state: FSMContext):
    """Обработчик перегенерации фото"""
    uin = callback.data.replace("regenerate_photo_", "")
    await _generate_photo_common_logic(uin, callback, state, "REGENERATION")


@router.callback_query(F.data.startswith("delete_photo_"))
async def handle_delete_photo(callback: CallbackQuery, state: FSMContext):
    """Обработчик удаления фото из РМП"""
    
    uin = callback.data.replace("delete_photo_", "")
    
    await callback.answer("Удаляю...")
    
    try:
        # Убираем кнопки
        await callback.message.edit_reply_markup(reply_markup=None)
        
        # Удаляем из photo_gen.csv и физический файл
        from database.photo_gen_tracker import delete_generated_photo_by_uin
        
        success = await delete_generated_photo_by_uin(uin)
        
        if success:
            logger.info(f"[DELETE_PHOTO] Фото УИН {uin} успешно удалено")
            
            await callback.message.answer("Фото удалено!")
            
            # Завершаем работу с изделием и переходим в режим ожидания нового УИН
            await state.set_state(ItemStates.waiting_datamatrix)
            await callback.message.answer(
                "Работа с изделием завершена!\n\n"
                "Отправьте новую бирку или введите УИН вручную для нового запроса."
            )
        else:
            logger.error(f"[DELETE_PHOTO] Не удалось удалить фото УИН {uin}")
            
            await callback.message.answer(
                "Не удалось удалить фото!\n\n"
                "Возможно, файл уже был удалён."
            )
            await state.set_state(ItemStates.waiting_datamatrix)
    
    except (TelegramAPIError, httpx.HTTPError, asyncio.TimeoutError, 
            ValueError, KeyError, AttributeError) as e:
        logger.error(f"[DELETE_PHOTO] Ошибка удаления фото: {e}")
        await callback.message.answer(
            "Произошла ошибка при удалении фото!"
        )
        await state.set_state(ItemStates.waiting_datamatrix)


@router.callback_query(F.data.startswith("generate_video_"))
async def handle_generate_video(callback: CallbackQuery, state: FSMContext):
    """
    Обработчик генерации видео
    
    Генерирует видео из уже сгенерированного фото в РМП
    """
    uin = callback.data.replace("generate_video_", "")
    
    await callback.message.edit_text(
        "Генерирую видео...\n\n"
        "Это может занять 3-5 минут, пожалуйста подождите..."
    )
    await callback.answer()
    
    try:
        logger.info(f"[VIDEO] Запуск генерации видео для УИН {uin}")
        
        # Запускаем генерацию только видео (фото УЖЕ есть в РМП)
        result = await api_client.generate_video(uin=uin)
        
        if not result:
            await callback.message.edit_text(
                " Ошибка при запуске генерации видео!\n\n"
                "Возможные причины:\n"
                "- FastAPI сервис недоступен\n"
                "- Фото не найдено в РМП\n\n"
                "Попробуйте позже."
            )
            await state.set_state(ItemStates.waiting_datamatrix)
            return
        
        task_id = result.get('task_id')
        logger.info(f"[VIDEO] Task ID для видео: {task_id}")
        
        # Ожидаем завершения генерации видео
        final_result = await api_client.wait_for_completion(
            task_id=task_id,
            max_wait_seconds=300,
            poll_interval=10
        )
        
        if not final_result:
            await callback.message.edit_text(
                "Таймаут ожидания генерации видео!\n\n"
                "Генерация заняла слишком много времени.\n"
                "Попробуйте позже."
            )
            await state.set_state(ItemStates.waiting_datamatrix)
            return
        
        if final_result.get('status') == 'SUCCEEDED':
            # Получаем video_url из data (как в API ответе)
            video_url = final_result.get('data', {}).get('video_url')
            
            if video_url:
                logger.info(f"[VIDEO] Видео готово: {video_url}")
                
                # Показываем что видео готово и начинается загрузка
                await callback.message.edit_text(
                    "Видео сгенерировано! Загружаю..."
                )
                
                # Скачиваем видео с РМП сервера для отправки в Telegram
                video_bytes = await api_client.download_video(video_url)
                
                if not video_bytes:
                    await callback.message.edit_text(
                        "Ошибка: Не удалось загрузить сгенерированное видео!"
                    )
                    await state.set_state(ItemStates.waiting_datamatrix)
                    return
                
                # Отправляем как анимацию
                from aiogram.types import BufferedInputFile
                await callback.message.answer_animation(
                    animation=BufferedInputFile(
                        video_bytes,
                        filename=f"{uin}_10.mp4"
                    ),
                    caption=(
                        f"<b>Сгенерированное видео</b>\n\n"
                        f" УИН: <code>{uin}</code>"
                    ),
                    parse_mode="HTML",
                    reply_markup=get_video_confirmation_keyboard(uin)
                )
                await callback.message.delete()
                await state.update_data(generated_video_url=video_url)
                await state.set_state(ItemStates.waiting_datamatrix)
            else:
                await callback.message.edit_text(
                    " Видео не было сгенерировано!"
                )
        else:
            error_msg = final_result.get('error', 'Неизвестная ошибка')
            await callback.message.edit_text(
                f" Генерация видео не удалась!\n\n{error_msg}"
            )
        
        await state.set_state(ItemStates.waiting_datamatrix)
    
    except (TelegramAPIError, httpx.HTTPError, asyncio.TimeoutError, 
            ValueError, KeyError, AttributeError) as e:
        logger.error(f"[VIDEO] Ошибка: {e}")
        await callback.message.edit_text(
            f" Произошла ошибка:\n{str(e)}"
        )
        await state.set_state(ItemStates.waiting_datamatrix)


@router.callback_query(F.data == "skip_video")
async def handle_skip_video(callback: CallbackQuery, state: FSMContext):
    """Обработчик пропуска видео"""
    
    await callback.message.edit_text(
        " Работа с изделием завершена!\n\n"
        "Отправьте новую бирку или введите УИН вручную для нового запроса."
    )
    await callback.answer()
    await state.set_state(ItemStates.waiting_datamatrix)


@router.callback_query(F.data.startswith("confirm_video_"))
async def handle_confirm_video(callback: CallbackQuery, state: FSMContext):
    """Обработчик подтверждения видео"""
    
    uin = callback.data.replace("confirm_video_", "")
    data = await state.get_data()
    generated_video_url = data.get('generated_video_url')
    
    await callback.answer(" Видео утверждено!")
    
    # Оставляем видео, убираем кнопки, меняем подпись
    await callback.message.edit_caption(
        caption=(
            f" <b>Видео утверждено!</b>\n\n"
            f" УИН: <code>{uin}</code>"
        ),
        parse_mode="HTML"
    )
    
    await callback.message.answer(
        " Работа с изделием завершена!\n\n"
        "Отправьте новую бирку или введите УИН вручную для нового запроса."
    )
    await state.set_state(ItemStates.waiting_datamatrix)


@router.callback_query(F.data.startswith("regenerate_video_"))
async def handle_regenerate_video(callback: CallbackQuery, state: FSMContext):
    """Обработчик перегенерации видео"""
    
    uin = callback.data.replace("regenerate_video_", "")
    
    # Удаляем видео-сообщение
    try:
        await callback.message.delete()
    except TelegramAPIError:
        pass  # Сообщение уже удалено
    
    # Создаём новое сообщение с прогрессом
    progress_msg = await callback.message.answer(
        "Генерирую видео...\n\n"
        "Это может занять 3-5 минут, пожалуйста подождите..."
    )
    
    await callback.answer()
    
    try:
        logger.info(f"[VIDEO_REGEN] Запуск регенерации видео для УИН {uin}")
        
        # Запускаем генерацию только видео (фото УЖЕ есть в РМП)
        result = await api_client.generate_video(uin=uin)
        
        if not result:
            await progress_msg.edit_text(
                " Ошибка при запуске генерации видео!\n\n"
                "Возможные причины:\n"
                "- FastAPI сервис недоступен\n"
                "- Фото не найдено в РМП\n\n"
                "Попробуйте позже."
            )
            await state.set_state(ItemStates.waiting_datamatrix)
            return
        
        task_id = result.get('task_id')
        logger.info(f"[VIDEO_REGEN] Task ID для видео: {task_id}")
        
        # Ожидаем завершения генерации видео
        final_result = await api_client.wait_for_completion(
            task_id=task_id,
            max_wait_seconds=300,
            poll_interval=10
        )
        
        if not final_result:
            await progress_msg.edit_text(
                "Таймаут ожидания генерации видео!\n\n"
                "Генерация заняла слишком много времени.\n"
                "Попробуйте позже."
            )
            await state.set_state(ItemStates.waiting_datamatrix)
            return
        
        if final_result.get('status') == 'SUCCEEDED':
            # Получаем video_url из data (как в API ответе)
            video_url = final_result.get('data', {}).get('video_url')
            
            if video_url:
                logger.info(f"[VIDEO_REGEN] Видео готово: {video_url}")
                
                # Показываем что видео готово и начинается загрузка
                await progress_msg.edit_text(
                    "Видео сгенерировано! Загружаю..."
                )
                
                # Скачиваем видео с РМП сервера для отправки в Telegram
                video_bytes = await api_client.download_video(video_url)
                
                if not video_bytes:
                    await progress_msg.edit_text(
                        "Ошибка: Не удалось загрузить сгенерированное видео!"
                    )
                    await state.set_state(ItemStates.waiting_datamatrix)
                    return
                
                # Отправляем как анимацию
                from aiogram.types import BufferedInputFile
                await callback.message.answer_animation(
                    animation=BufferedInputFile(
                        video_bytes,
                        filename=f"{uin}_10.mp4"
                    ),
                    caption=(
                        f"<b>Сгенерированное видео</b>\n\n"
                        f" УИН: <code>{uin}</code>"
                    ),
                    parse_mode="HTML",
                    reply_markup=get_video_confirmation_keyboard(uin)
                )
                await progress_msg.delete()
                await state.update_data(generated_video_url=video_url)
                await state.set_state(ItemStates.waiting_datamatrix)
            else:
                await progress_msg.edit_text(
                    " Видео не было сгенерировано!"
                )
        else:
            error_msg = final_result.get('error', 'Неизвестная ошибка')
            await progress_msg.edit_text(
                f" Генерация видео не удалась!\n\n{error_msg}"
            )
        
        await state.set_state(ItemStates.waiting_datamatrix)
    
    except (TelegramAPIError, httpx.HTTPError, asyncio.TimeoutError, 
            ValueError, KeyError, AttributeError) as e:
        logger.error(f"[VIDEO_REGEN] Ошибка: {e}")
        try:
            await progress_msg.edit_text(
                f" Произошла ошибка:\n{str(e)}"
            )
        except TelegramAPIError:
            pass  # Не удалось отправить уведомление об ошибке
        await state.set_state(ItemStates.waiting_datamatrix)


@router.callback_query(F.data.startswith("delete_video_"))
async def handle_delete_video(callback: CallbackQuery, state: FSMContext):
    """Обработчик удаления видео из РМП"""
    
    uin = callback.data.replace("delete_video_", "")
    
    await callback.answer("Удаляю...")
    
    try:
        # Убираем кнопки
        await callback.message.edit_reply_markup(reply_markup=None)
        
        # Удаляем из photo_gen.csv и физический файл
        from database.photo_gen_tracker import delete_generated_video_by_uin
        
        success = await delete_generated_video_by_uin(uin)
        
        if success:
            logger.info(f"[DELETE_VIDEO] Видео УИН {uin} успешно удалено")
            
            await callback.message.answer("Видео удалено!")
            
            # Завершаем работу с изделием и переходим в режим ожидания нового УИН
            await state.set_state(ItemStates.waiting_datamatrix)
            await callback.message.answer(
                "Работа с изделием завершена!\n\n"
                "Отправьте новую бирку или введите УИН вручную для нового запроса."
            )
        else:
            logger.error(f"[DELETE_VIDEO] Не удалось удалить видео УИН {uin}")
            
            await callback.message.answer(
                "Не удалось удалить видео!\n\n"
                "Возможно, файл уже был удалён."
            )
            await state.set_state(ItemStates.waiting_datamatrix)
    
    except (TelegramAPIError, httpx.HTTPError, asyncio.TimeoutError, 
            ValueError, KeyError, AttributeError) as e:
        logger.error(f"[DELETE_VIDEO] Ошибка удаления видео: {e}")
        await callback.message.answer(
            "Произошла ошибка при удалении видео!"
        )
        await state.set_state(ItemStates.waiting_datamatrix)


@router.callback_query(F.data == "finish")
async def handle_finish(callback: CallbackQuery, state: FSMContext):
    """Обработчик завершения работы с изделием (кнопка ' Завершить')"""
    
    await callback.answer()
    
    try:
        # Убираем только кнопки, оставляем текст (информацию об изделии)
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError as e:
        logger.warning(f"[FINISH] Не удалось убрать кнопки: {e}")
    
    # Отправляем новое сообщение
    await callback.message.answer(
        " Работа с изделием завершена!\n\n"
        "Отправьте новую бирку или введите УИН вручную для нового запроса."
    )
    
    await state.set_state(ItemStates.waiting_datamatrix)


@router.callback_query(F.data == "cancel")
async def handle_cancel(callback: CallbackQuery, state: FSMContext):
    """Обработчик отмены (кнопка ' Отмена' при генерации)"""
    
    await callback.answer()
    
    try:
        # Удаляем сообщение с предложением генерации
        await callback.message.delete()
    except TelegramAPIError as e:
        # Если не получилось удалить, хотя бы убираем кнопки
        logger.warning(f"[CANCEL] Не удалось удалить сообщение: {e}")
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError as e2:
            logger.warning(f"[CANCEL] Не удалось убрать кнопки: {e2}")
    
    # Отправляем новое сообщение
    await callback.message.answer(
        " Работа с изделием завершена!\n\n"
        "Отправьте новую бирку или введите УИН вручную для нового запроса."
    )
    
    await state.set_state(ItemStates.waiting_datamatrix)


@router.message(ItemStates.waiting_datamatrix, F.text)
async def handle_uin_text(message: Message, state: FSMContext, bot: Bot):
    """Обработчик ручного ввода УИН (16 цифр)"""
    
    text = message.text.strip()
    
    # Проверяем, что это 16 цифр
    if not text.isdigit():
        await message.answer(
            "УИН должен содержать только цифры.\n\n"
            "Попробуйте ещё раз или отправьте фото бирки."
        )
        return
    
    if len(text) != 16:
        await message.answer(
            f" УИН должен содержать ровно 16 цифр.\n"
            f"Вы ввели: {len(text)} цифр(ы)\n\n"
            "Попробуйте ещё раз или отправьте фото бирки."
        )
        return
    
    uin = text
    
    status_msg = await message.answer(f"УИН: `{uin}`\n\nИщу в базе данных...", parse_mode="Markdown")
    
    try:
        # Получаем информацию из БД (в отдельном потоке для асинхронности)
        info = await asyncio.to_thread(get_item_info, uin)
        
        if not info:
            await status_msg.edit_text(
                f"Изделие с УИН `{uin}` не найдено в базе.\n\n"
                "Попробуйте другой УИН!",
                parse_mode="Markdown"
            )
            return
        
        # Формируем ответ с информацией об изделии
        response = (
            f"<b>Изделие найдено!</b>\n\n"
            f"УИН: <code>{info['uin']}</code>\n"
            f"Тип: {info['item_type']}\n"
            f"Вес: {info['weight']} г\n"
        )
        
        # Показываем цену без скидки и процент скидки, если они есть
        if info['price_regular'] is not None and info['discount'] is not None:
            response += (
                f"Цена: {info['price_regular']} руб\n"
                f"Скидка: {info['discount']}%\n"
                f"Цена со скидкой: <b>{info['price_sale']} руб</b>\n"
            )
        else:
            # Если нет цены без скидки - показываем только цену со скидкой
            response += f"Цена со скидкой: <b>{info['price_sale']} руб</b>\n"
        
        response += f"Фото в РМП: {len(info['item_photos'])}\n"
        
        # Добавляем информацию о сгенерированном фото, если есть
        if info.get('has_generated_photo', False):
            response += f"Фото ИИ: 1\n"
        
        # Добавляем информацию о сгенерированном видео, если есть
        if info.get('has_generated_video', False):
            response += f"Видео ИИ: 1\n"

        await status_msg.edit_text(
            response,
            reply_markup=get_item_found_keyboard(uin),
            parse_mode="HTML"
        )
        
        # Сохраняем данные в state
        await state.update_data(
            uin=uin,
            item_info=info
        )
        await state.set_state(ItemStates.waiting_confirmation)
        
    except (TelegramAPIError, httpx.HTTPError, asyncio.TimeoutError, 
            ValueError, KeyError, AttributeError, OSError) as e:
        await status_msg.edit_text(
            f" Произошла ошибка при обработке УИН:\n{str(e)}\n\n"
            "Попробуйте ещё раз!"
        )
        await state.set_state(ItemStates.waiting_datamatrix)


@router.message(F.photo | F.document)
async def handle_photo_fallback(message: Message, state: FSMContext, bot: Bot):
    """Обработчик фото вне состояния waiting_datamatrix - автостарт и обработка"""
    # Проверяем, что это изображение
    if message.document and (not message.document.mime_type or not message.document.mime_type.startswith('image/')):
        return  # Это не изображение, пропускаем
    
    # Автоматически переводим в режим ожидания и обрабатываем фото
    await state.set_state(ItemStates.waiting_datamatrix)
    
    # Перенаправляем на основной обработчик
    await handle_datamatrix_photo(message, state, bot)


@router.message()
async def handle_other(message: Message, state: FSMContext, bot: Bot):
    """Обработчик всех остальных сообщений (catch-all)"""
    
    # КРИТИЧЕСКАЯ ПРОВЕРКА: если это команда - НЕ обрабатываем!
    if message.text:
        text = message.text.strip()
        if text.startswith('/'):
            logger.error(f"[HANDLE_OTHER] ОШИБКА! Команда '{text}' попала в handle_other! Message ID: {message.message_id}")
            return  # НЕ обрабатываем команды здесь!
    
    # Проверяем, установлено ли состояние (пользователь нажал /start)
    current_state = await state.get_state()
    
    # Если состояние НЕ установлено - просим нажать /start
    if current_state is None or current_state != ItemStates.waiting_datamatrix:
        await message.answer(
            "Пожалуйста, начните работу с ботом, нажав команду /start"
        )
        return
    
    # Если состояние установлено, но сообщение попало в handle_other (не обработалось другими обработчиками)
    # Это может быть текст, который должен был обработаться handle_uin_text
    if message.text:
        # Если это текст в состоянии waiting_datamatrix - обрабатываем как УИН
        await handle_uin_text(message, state, bot)
        return
    
    # Если это не текст (стикер, голосовое и т.д.) - игнорируем
