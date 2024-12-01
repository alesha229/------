from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_subscription_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с вариантами подписки"""
    keyboard = [
        [
            InlineKeyboardButton(
                text="Месяц - 299₽",
                callback_data="subscribe_month"
            )
        ],
        [
            InlineKeyboardButton(
                text="Год - 2990₽ (экономия 20%)",
                callback_data="subscribe_year"
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
