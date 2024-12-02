import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
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
    waiting_for_region = State()
    viewing_modifications = State()

class CarSearch(StatesGroup):
    manufacturer = State()
    modifications = State()
    model = State()
    region = State()

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
    await message.answer(
        "Введите поисковый запрос:\n\n"
        "Примеры:\n"
        "• Поиск по артикулу: 04465-42160\n"
        "• Поиск по VIN: JF1BL5KS57G03135T\n"
        "• Поиск по марке/модели: HONDA CIVIC 1996"
    )
    await state.set_state(SearchStates.waiting_for_part_number)

@dp.message(SearchStates.waiting_for_part_number)
@log_command
async def handle_part_number(message: types.Message, session: AsyncSession, state: FSMContext):
    """Обработчик ввода номера детали"""
    query = message.text.strip()
    try:
        # Определяем тип поиска
        search_type = await AutodocParserFactory.get_search_type(query)

        if search_type == "car":
            # Создаем парсер для поиска автомобилей
            parser = AutodocCarParser()
            
            # Извлекаем информацию об автомобиле
            car_info = await AutodocParserFactory.extract_car_info(query)

            if car_info:
                brand, model, year = car_info
                # Проверяем существование бренда
                brand_code = await parser.get_brand_code(brand)
                
                if brand_code:
                    # Создаем кнопки для каждого региона
                    keyboard_buttons = []
                    current_row = []
                    
                    for region in parser.available_regions:
                        current_row.append(
                            types.InlineKeyboardButton(
                                text=region,
                                callback_data=f"region_{brand}_{model}_{year}_{region}"
                            )
                        )
                        
                        # Добавляем по 2 кнопки в ряд
                        if len(current_row) == 2:
                            keyboard_buttons.append(current_row)
                            current_row = []
                    
                    # Добавляем оставшиеся кнопки, если есть
                    if current_row:
                        keyboard_buttons.append(current_row)
                    
                    # Создаем клавиатуру с явным указанием inline_keyboard
                    keyboard = types.InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
                    
                    await message.answer(
                        "Выберите регион для поиска:",
                        reply_markup=keyboard
                    )
                    await state.update_data(brand=brand, model=model, year=year)
                    await state.set_state(SearchStates.waiting_for_region)
                else:
                    await message.answer(
                        "❌ Производитель не найден. Пожалуйста, проверьте название и попробуйте снова."
                    )
            else:
                await message.answer(
                    "❌ Не удалось распознать информацию об автомобиле.\n"
                    "Пожалуйста, используйте формат: МАРКА МОДЕЛЬ ГОД\n"
                    "Например: HONDA CIVIC 1996"
                )
                
        elif search_type == "vin":
            # Поиск по VIN
            parser = AutodocVinParser()
            result = await parser.search(query)
            if result:
                await message.answer(result)
            else:
                await message.answer("❌ Не удалось найти информацию по указанному VIN")
                
        else:
            # Поиск по артикулу
            parser = AutodocArticleParser()
            results = await parser.search(query)
            if results:
                # Форматируем результаты поиска
                response = "🔍 Найденные запчасти:\n\n"
                for i, part in enumerate(results, 1):
                    response += f"{i}. {part.get('name', 'Название не указано')}\n"
                    response += f"📝 Артикул: {part.get('number', 'Не указан')}\n"
                    response += f"🏭 Производитель: {part.get('manufacturer', 'Не указан')}\n"
                    
                    # Цена
                    price = part.get('price')
                    if price:
                        response += f"💰 Цена: {price} ₽\n"
                    else:
                        response += "💰 Цена: Не указана\n"
                    
                    # Магазин
                    source = part.get('source', 'Не указан')
                    response += f"🏪 Магазин: {source}\n"
                    
                    # Наличие
                    if part.get('availability'):
                        response += "✅ В наличии\n"
                    else:
                        response += "❌ Нет в наличии\n"
                    
                    # URL если есть
                    if part.get('url'):
                        response += f"🔗 {part['url']}\n"
                    
                    response += "\n" + "="*30 + "\n"
                
                # Разбиваем на части если сообщение слишком длинное
                max_length = 4096
                for i in range(0, len(response), max_length):
                    chunk = response[i:i + max_length]
                    await message.answer(chunk)
            else:
                await message.answer("❌ Не удалось найти информацию по указанному артикулу")
                
    except Exception as e:
        logger.error(f"Error in search handler: {e}")
        await message.answer(
            "❌ Произошла ошибка при поиске. Пожалуйста, попробуйте позже или измените запрос."
        )
    finally:
        await state.clear()

def create_modifications_keyboard(modifications, page=1):
    """Создать клавиатуру с модификациями и пагинацией"""
    # Проверяем, что у нас есть список модификаций
    if not modifications.get('modifications'):
        return types.InlineKeyboardMarkup(inline_keyboard=[])

    # Получаем список модификаций
    mod_list = modifications.get('modifications', [])
    logger.info(modifications)
    
    # Разбиваем на страницы по 5 кнопок (уменьшаем количество для лучшей читаемости)
    items_per_page = 5
    total_pages = (len(mod_list) + items_per_page - 1) // items_per_page
    
    # Убедимся, что страница в допустимых пределах
    page = max(1, min(page, total_pages))
    
    # Вычисляем индексы для текущей страницы
    start_idx = (page - 1) * items_per_page
    end_idx = min(start_idx + items_per_page, len(mod_list))
    
    # Создаем кнопки для текущей страницы
    keyboard = []
    for mod in mod_list[start_idx:end_idx]:
        # Создаем текст кнопки с информацией о модификации
        button_text = (
            f"{mod.get('grade', 'Н/Д')} • "
            f"{mod.get('transmission', 'Н/Д')} • "
            f"{mod.get('doors', 'Н/Д')}д • "
            f"({mod.get('dest_region', 'Н/Д')})"
        )
        
        # Создаем callback_data с ID модификации
        callback_data = f"mod_{mod.get('id', '')}"
        
        keyboard.append([
            types.InlineKeyboardButton(
                text=button_text,
                callback_data=callback_data
            )
        ])
    
    # Добавляем кнопки пагинации
    nav_buttons = []
    
    # Кнопка "В начало", если не на первой странице
    if page > 1:
        nav_buttons.append(types.InlineKeyboardButton(
            text="⏮",
            callback_data="page_1"
        ))
    
    # Кнопка "Назад"
    if page > 1:
        nav_buttons.append(types.InlineKeyboardButton(
            text="⬅️",
            callback_data=f"page_{page-1}"
        ))
    
    # Кнопка "Вперед"
    if page < total_pages:
        nav_buttons.append(types.InlineKeyboardButton(
            text="➡️",
            callback_data=f"page_{page+1}"
        ))
    
    # Кнопка "В конец", если не на последней странице
    if page < total_pages:
        nav_buttons.append(types.InlineKeyboardButton(
            text="⏭",
            callback_data=f"page_{total_pages}"
        ))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # Добавляем информацию о странице
    keyboard.append([
        types.InlineKeyboardButton(
            text=f"📄 {page} из {total_pages}",
            callback_data="page_info"
        )
    ])
    
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard)

@dp.callback_query(lambda c: c.data.startswith('region_'))
async def handle_region_selection(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора региона"""
    try:
        # Разбираем callback data
        _, brand, model, year, region = callback_query.data.split('_')
        
        logger.info(f"Selected: brand={brand}, model={model}, year={year}, region={region}")
        
        # Создаем парсер и получаем модификации
        parser = AutodocCarParser()
        try:
            modifications_data = await parser.search_modifications(brand, model, year, region)
            logger.info(f"Modifications data: {modifications_data}")
            if not modifications_data or not modifications_data.get('modifications'):
                await callback_query.answer("Модификации не найдены")
                return
            
            # Сохраняем данные в состояние
            await state.update_data(
                modifications=modifications_data['modifications'],
                region=region,
                brand=brand,
                model=model,
                year=year
            )
            
            # Создаем клавиатуру с модификациями
            keyboard = create_modifications_keyboard(modifications_data)
            
            # Форматируем общую информацию
            common_info = []
            for attr in modifications_data.get('commonAttributes', []):
                if attr['key'] in ['Brand', 'Model', 'manufactured']:
                    common_info.append(f"{attr['name']}: {attr['value']}")
            
            message_text = (
                f"🚗 {' | '.join(common_info)}\n\n"
                "Выберите модификацию:"
            )
            
            try:
                await callback_query.message.edit_text(
                    text=message_text,
                    reply_markup=keyboard
                )
            except aiogram.exceptions.TelegramBadRequest as e:
                if "message is not modified" not in str(e):
                    raise
                
        except Exception as e:
            logger.error(f"Error getting modifications: {e}")
            await callback_query.answer("Ошибка при получении модификаций. Попробуйте позже.")
            
    except Exception as e:
        logger.error(f"Error in region selection handler: {e}")
        try:
            await callback_query.answer("Произошла ошибка. Попробуйте позже.")
        except:
            pass

@dp.callback_query(lambda c: c.data.startswith('page_'))
async def handle_page_selection(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора страницы"""
    try:
        page = int(callback_query.data.split('_')[1])
        data = await state.get_data()
        modifications = data.get('modifications', [])
        keyboard = create_modifications_keyboard({'modifications': modifications}, page)
        await callback_query.message.edit_text(
            f"{data.get('brand')} {data.get('model')} {data.get('year')}\n\nВыберите модификацию:",
            reply_markup=keyboard
        )
        await state.update_data(current_page=page)
        await callback_query.answer()
    except Exception as e:
        logger.error(f"Error in page selection handler: {e}")
        await callback_query.answer("Ошибка при переключении страницы", show_alert=True)

@dp.callback_query(lambda c: c.data.startswith('mod_'))
async def handle_modification_selection(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора модификации"""
    try:
        _, mod_id = callback_query.data.split('_')
        
        # Получаем данные о выбранной модификации
        data = await state.get_data()
        modifications = data.get('modifications', [])
        
        # Ищем выбранную модификацию
        selected_mod = None
        for mod in modifications:
            if str(mod.get("id")) == mod_id:
                selected_mod = mod
                break
        
        if selected_mod:
            # Извлекаем атрибуты из списка attributes
            attributes_dict = {}
            for attr in selected_mod.get('attributes', []):
                attributes_dict[attr['key']] = attr['value']
            
            message_text = [
                "🚗 Выбранная модификация:"
            ]
            
            # Добавляем основные характеристики, если они есть
            if attributes_dict.get('grade'):
                message_text.append(f"• Комплектация: {attributes_dict['grade']}")
            if attributes_dict.get('transmission'):
                message_text.append(f"• КПП: {attributes_dict['transmission']}")
            if attributes_dict.get('engine'):
                message_text.append(f"• Двигатель: {attributes_dict['engine']}")
            if attributes_dict.get('engineCode'):
                message_text.append(f"• Код двигателя: {attributes_dict['engineCode']}")
            if attributes_dict.get('power'):
                message_text.append(f"• Мощность: {attributes_dict['power']}")
            if attributes_dict.get('bodyType'):
                message_text.append(f"• Тип кузова: {attributes_dict['bodyType']}")
            if data.get('region'):
                message_text.append(f"• Регион: {data['region']}")
            
            # Добавляем остальные атрибуты, которые могут быть полезны
            for key, value in attributes_dict.items():
                if key not in ['grade', 'transmission', 'engine', 'engineCode', 'power', 'bodyType'] and value:
                    message_text.append(f"• {key}: {value}")
            
            await callback_query.message.answer("\n".join(message_text))
            
            # Добавляем кнопку для перехода к поиску запчастей
            keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(
                    text="🔍 Искать запчасти",
                    callback_data=f"search_parts_{mod_id}"
                )]
            ])
            
            await callback_query.message.answer(
                "Нажмите кнопку ниже, чтобы начать поиск запчастей для выбранной модификации:",
                reply_markup=keyboard
            )
            
            await callback_query.answer()
        else:
            await callback_query.answer("Модификация не найдена", show_alert=True)
            
    except Exception as e:
        logger.error(f"Error in modification selection handler: {e}")
        await callback_query.answer("Ошибка при выборе модификации", show_alert=True)

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
