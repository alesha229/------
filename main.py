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
from parsers.autodoc_car_parser import AutodocCarParser
from parsers.autodoc_article_parser import AutodocArticleParser
from parsers.autodoc_factory import AutodocParserFactory
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

class CarSearch(StatesGroup):
    manufacturer = State()
    modifications = State()
    model = State()

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
        # Определяем тип поиска
        search_type = await AutodocParserFactory.get_search_type(part_number)
        
        if search_type == "article":
            # Поиск по артикулу
            parser = AutodocArticleParser()
            results = await parser.search_by_article(part_number)
            
            if results:
                response = "🔍 Найденные запчасти (отсортированы по цене):\n\n"
                for i, part in enumerate(results, 1):
                    # Название детали (если есть)
                    if part.get('name'):
                        response += f"{i}. {part['name']}\n"
                    else:
                        response += f"{i}. \n"
                        
                    response += f"📝 Артикул: {part['number']}\n"
                    response += f"🏭 Производитель: {part['manufacturer']}\n"
                    
                    # Цена с проверкой
                    price = part.get('price', 0)
                    if price > 0:
                        response += f"💰 Цена: {price} ₽\n"
                    else:
                        response += f"💰 Цена: Не указана ₽\n"
                        
                    response += f"🏪 Магазин: {part['source']}\n"
                    
                    # Наличие
                    in_stock = part.get('in_stock', 0)
                    if in_stock > 0:
                        response += f"✅ В наличии: {in_stock} шт.\n"
                    else:
                        response += "❌ Нет в наличии\n"
                    
                    # URL если есть
                    if part.get('url'):
                        response += f"\n🔗 {part['url']}\n"
                        
                    response += "\n"
            else:
                response = "К сожалению, запчасти с таким артикулом не найдены"
                
            await status_message.edit_text(response)
            
        elif search_type == "car":
            # Поиск по марке/модели
            parser = AutodocCarParser()
            
            # Проверяем, содержит ли запрос только название бренда
            if len(part_number.split()) == 1:
                wizard_data = await parser.get_wizard_data(part_number)
                if wizard_data:
                    models = parser.extract_models(wizard_data)
                    if models:
                        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
                        for model in models:
                            keyboard.add(types.KeyboardButton(model['name']))
                        await status_message.edit_text("Выберите модель:", reply_markup=keyboard)
                        await state.update_data(brand=part_number)
                        await CarSearch.model.set()
                    else:
                        await status_message.edit_text("Не удалось найти модели для данного производителя")
                else:
                    await status_message.edit_text("Не удалось получить информацию о моделях")
            else:
                await status_message.edit_text(
                    "Для поиска по марке автомобиля, пожалуйста, введите только название марки.\n"
                    "Например: HONDA"
                )
        
    except Exception as e:
        logger.error(f"Error during part search: {e}")
        await status_message.edit_text("Произошла ошибка при поиске. Пожалуйста, попробуйте позже.")
    
    await state.clear()

@dp.message(lambda message: message.text.startswith("/search"))
@log_command
async def search_handler(message: types.Message, state: FSMContext):
    """Обработчик поискового запроса"""
    query = message.text.replace("/search", "").strip()
    
    # Определяем тип поиска
    search_type = await AutodocParserFactory.get_search_type(query)
    
    if search_type == "article":
        # Поиск по артикулу
        parser = AutodocArticleParser()
        results = await parser.search_by_article(query)
        if results:
            response = "🔍 Найденные запчасти (отсортированы по цене):\n\n"
            for i, part in enumerate(results, 1):
                # Название детали (если есть)
                if part.get('name'):
                    response += f"{i}. {part['name']}\n"
                else:
                    response += f"{i}. \n"
                    
                response += f"📝 Артикул: {part['number']}\n"
                response += f"🏭 Производитель: {part['manufacturer']}\n"
                
                # Цена с проверкой
                price = part.get('price', 0)
                if price > 0:
                    response += f"💰 Цена: {price} ₽\n"
                else:
                    response += f"💰 Цена: Не указана ₽\n"
                    
                response += f"🏪 Магазин: {part['source']}\n"
                
                # Наличие
                in_stock = part.get('in_stock', 0)
                if in_stock > 0:
                    response += f"✅ В наличии: {in_stock} шт.\n"
                else:
                    response += "❌ Нет в наличии\n"
                
                # URL если есть
                if part.get('url'):
                    response += f"\n🔗 {part['url']}\n"
                    
                response += "\n"
        else:
            response = "К сожалению, запчасти с таким артикулом не найдены"
            
        await message.answer(response)
        await state.clear()
        
    else:
        # Поиск по марке/модели
        parser = AutodocCarParser()
        
        # Если запрос содержит только название бренда
        if len(query.split()) == 1:
            # Получаем данные мастера для бренда
            wizard_data = await parser.get_wizard_data(query)
            if wizard_data:
                models = parser.extract_models(wizard_data)
                if models:
                    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
                    for model in models:
                        keyboard.add(types.KeyboardButton(model['name']))
                    await message.answer("Выберите модель:", reply_markup=keyboard)
                    await state.update_data(brand=query)
                    await CarSearch.model.set()
                else:
                    await message.answer("Не удалось найти модели для данного производителя")
                    await state.clear()
            else:
                await message.answer("Не удалось получить информацию о моделях")
                await state.clear()
        else:
            # Если запрос содержит больше информации
            car_info = await AutodocParserFactory.extract_car_info(query)
            if car_info:
                manufacturer, model, year = car_info
                await state.update_data(brand=manufacturer, model=model, year=year)
                wizard_data = await parser.get_wizard_data(manufacturer)
                if wizard_data:
                    modifications = parser.extract_models(wizard_data)
                    if modifications:
                        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
                        for mod in modifications:
                            keyboard.add(types.KeyboardButton(mod['name']))
                        await message.answer("Выберите модификацию:", reply_markup=keyboard)
                        await CarSearch.modifications.set()
                    else:
                        await message.answer("Не удалось найти модификации для данного автомобиля")
                        await state.clear()
                else:
                    await message.answer("Не удалось получить информацию о модификациях")
                    await state.clear()
            else:
                await message.answer("Пожалуйста, укажите производителя, модель и год автомобиля в формате:\n/search HONDA CIVIC 2020")
                await state.clear()

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
