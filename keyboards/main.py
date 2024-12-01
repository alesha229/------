from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Основная клавиатура бота"""
    keyboard = [
        [
            KeyboardButton(text="🔍 Поиск запчастей"),
            KeyboardButton(text="💎 Подписка")
        ],
        [
            KeyboardButton(text="❓ Помощь"),
            KeyboardButton(text="👥 Реферальная программа")
        ]
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие"
    )
