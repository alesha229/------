from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Создание основной клавиатуры"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🔍 Поиск запчастей")
            ],
            [
                KeyboardButton(text="💳 Подписка"),
                KeyboardButton(text="📱 Мой профиль")
            ],
            [
                KeyboardButton(text="❓ Помощь"),
                KeyboardButton(text="👥 Реферальная программа")
            ]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_search_keyboard() -> ReplyKeyboardMarkup:
    """Создание клавиатуры для поиска"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🔍 Поиск по артикулу/VIN"),
                KeyboardButton(text="🚗 Поиск по авто")
            ],
            [
                KeyboardButton(text="📋 История поиска")
            ],
            [
                KeyboardButton(text="🏠 Главное меню")
            ]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_profile_keyboard() -> ReplyKeyboardMarkup:
    """Создание клавиатуры профиля"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Статистика поиска"),
                KeyboardButton(text="⚙️ Настройки")
            ],
            [
                KeyboardButton(text="🏠 Главное меню")
            ]
        ],
        resize_keyboard=True
    )
    return keyboard
