from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_item_found_keyboard(uin: str) -> InlineKeyboardMarkup:
    """Клавиатура после нахождения изделия - выбор действия"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Генерация", callback_data=f"work_with_photos_{uin}"),
            InlineKeyboardButton(text="Завершить", callback_data="finish")
        ]
    ])


def get_photo_confirmation_keyboard(uin: str) -> InlineKeyboardMarkup:
    """Клавиатура для подтверждения фото"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Утвердить", callback_data=f"confirm_photo_{uin}"),
            InlineKeyboardButton(text="Перегенерировать", callback_data=f"regenerate_photo_{uin}")
        ],
        [
            InlineKeyboardButton(text="Удалить", callback_data=f"delete_photo_{uin}")
        ]
    ])


def get_video_confirmation_keyboard(uin: str) -> InlineKeyboardMarkup:
    """Клавиатура для подтверждения видео"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Утвердить", callback_data=f"confirm_video_{uin}"),
            InlineKeyboardButton(text="Перегенерировать", callback_data=f"regenerate_video_{uin}")
        ],
        [
            InlineKeyboardButton(text="Удалить", callback_data=f"delete_video_{uin}")
        ]
    ])


def get_generate_photo_keyboard(uin: str) -> InlineKeyboardMarkup:
    """Клавиатура для предложения генерации фото"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Сгенерировать", callback_data=f"generate_photo_{uin}"),
            InlineKeyboardButton(text="Отмена", callback_data="cancel")
        ]
    ])


def get_video_generation_keyboard(uin: str) -> InlineKeyboardMarkup:
    """Клавиатура для генерации видео"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сгенерировать видео", callback_data=f"generate_video_{uin}")],
        [InlineKeyboardButton(text="Пропустить", callback_data="skip_video")]
    ])

