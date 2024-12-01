import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters.command import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from aiohttp import web
from datetime import datetime
from aiogram.fsm.storage.memory import MemoryStorage

import config
from models import Base, User, Subscription
from handlers import admin, subscription, referral
from utils.monitoring import start_monitoring, log_command
from parsers.search_aggregator import SearchAggregator
from webhook_server import app as webhook_app
from database import engine, async_session_maker, DatabaseMiddleware
from keyboards.subscription import get_subscription_keyboard
from keyboards.main import get_main_keyboard

# Configure logging
logging.basicConfig(level=getattr(logging, config.LOG_LEVEL))
logger = logging.getLogger(__name__)

# Initialize bot and dispatcher
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())  # Добавляем хранилище для FSM

# Add middleware
dp.update.middleware(DatabaseMiddleware())

# Register routers
dp.include_router(admin.router)
dp.include_router(subscription.router)
dp.include_router(referral.router)

# Initialize parsers
search_aggregator = SearchAggregator()

# Создаем состояния для FSM
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

class SearchStates(StatesGroup):
    waiting_for_part_number = State()

@dp.message(Command("start"))
@log_command
async def cmd_start(message: types.Message, session: AsyncSession):
    """Обработчик команды /start"""
    # Создаем или получаем пользователя
    result = await session.execute(
        select(User)
        .options(selectinload(User.subscription))
        .where(User.telegram_id == message.from_user.id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        # Создаем нового пользователя
        user = User(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name
        )
        session.add(user)
        await session.commit()
        
        # Создаем тестовую подписку на 1 день
        from datetime import datetime, timedelta
        trial_subscription = Subscription(
            user_id=user.id,
            is_active=True,
            start_date=datetime.utcnow(),
            period='trial',
            end_date=datetime.utcnow() + timedelta(days=1),
            is_trial=True
        )
        session.add(trial_subscription)
        await session.commit()
    
    await message.answer(
        f"Привет, {message.from_user.first_name}! 👋\n\n"
        f"Я помогу тебе найти автозапчасти по лучшим ценам.\n"
        f"Используй кнопки меню для навигации:",
        reply_markup=get_main_keyboard()
    )

@dp.message(lambda message: message.text == "🔍 Поиск запчастей")
@log_command
async def search_parts(message: types.Message, state: FSMContext):
    """Обработчик кнопки поиска запчастей"""
    await state.set_state(SearchStates.waiting_for_part_number)
    await message.answer(
        "Введите номер детали для поиска.\n"
        "Например: 90915YZZD4"
    )

@dp.message(SearchStates.waiting_for_part_number)
@log_command
async def handle_part_number(message: types.Message, session: AsyncSession, state: FSMContext):
    """Обработчик ввода номера детали"""
    await state.clear()
    part_number = message.text.strip()
    
    # Проверяем подписку
    result = await session.execute(
        select(User)
        .options(selectinload(User.subscription))
        .where(User.telegram_id == message.from_user.id)
    )
    user = result.scalar_one_or_none()
    
    if not user or not user.subscription:
        keyboard = get_subscription_keyboard()
        await message.answer(
            "Для поиска запчастей необходима подписка.\n"
            "Выберите тариф для оформления подписки:",
            reply_markup=keyboard
        )
        return
        
    # Проверяем активность подписки
    now = datetime.utcnow()
    subscription = user.subscription
    if not subscription.is_active or subscription.end_date < now:
        subscription.is_active = False
        await session.commit()
        
        keyboard = get_subscription_keyboard()
        await message.answer(
            "Ваша подписка истекла.\n"
            "Выберите тариф для продления подписки:",
            reply_markup=keyboard
        )
        return
    
    status_message = await message.answer("🔍 Ищем запчасть на всех площадках... Это может занять некоторое время.")
    
    try:
        # Используем агрегатор для поиска на всех площадках
        results = await search_aggregator.search_all(part_number)
        
        # Получаем отсортированные по цене результаты
        sorted_results = search_aggregator.sort_results_by_price(results)
        
        logging.info(f"Search results for {part_number}: {sorted_results}")
        
        if not any(results.values()):  # Проверяем, есть ли результаты хоть на одной площадке
            await status_message.edit_text(
                "😕 К сожалению, запчасти с таким номером не найдены ни на одной площадке.\n"
                "Проверьте правильность номера и попробуйте снова."
            )
            return
        
        # Формируем сообщение с результатами
        response = "🔍 Найденные запчасти (отсортированы по цене):\n\n"
        
        # Выводим топ-5 результатов с каждой площадки
        for i, item in enumerate(sorted_results[:15], 1):
            delivery_info = f"📦 Доставка: {item.get('delivery_days', 'Не указано')} дн." if item.get('delivery_days') is not None else ""
            price = item.get('price', 0)
            price_str = f"{price:,.0f}".replace(",", " ") if price else "Не указана"
            quantity = item.get('in_stock', 0)
            in_stock = f"✅ В наличии: {quantity} шт." if quantity > 0 else "❌ Нет в наличии"
            
            response += (
                f"{i}. {item.get('part_name', 'Название не указано')}\n"
                f"📝 Артикул: {item.get('part_number', 'Не указан')}\n"
                f"🏭 Производитель: {item.get('brand', 'Не указан')}\n"
                f"💰 Цена: {price_str} ₽\n"
                f"🏪 Магазин: {item.get('source', 'Не указан')}\n"
                f"{in_stock}\n"
                f"{delivery_info}\n"
                f"🔗 {item.get('url', '')}\n\n"
            )
        
        # Добавляем статистику по площадкам
        response += "📊 Статистика поиска:\n"
        for source, items in results.items():
            response += f"{source}: найдено {len(items)} предложений\n"
        
        await status_message.edit_text(response)
        
    except Exception as e:
        logging.error(f"Error searching parts: {e}", exc_info=True)
        await status_message.edit_text(
            "😔 Произошла ошибка при поиске.\n"
            "Пожалуйста, попробуйте позже или обратитесь в поддержку."
        )

async def main():
    # Инициализация базы данных
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Запуск мониторинга
    await start_monitoring()

    # Запуск вебхук сервера
    runner = web.AppRunner(webhook_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    logger.info("Webhook server started on port 8080")

    # Запуск бота
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
