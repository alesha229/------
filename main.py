import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta

from config import config
from models import Base, User, Subscription
from handlers import admin, subscription, referral
from utils.logger import logger
from utils.metrics import metrics
from prometheus_client import start_http_server
from database import engine, async_session_maker, DatabaseMiddleware
from keyboards.main import get_main_keyboard, get_search_keyboard
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from parsers.autodoc_factory import AutodocParserFactory
from parsers.search_aggregator import SearchAggregator
from parsers.autodoc_car_parser import AutodocCarParser

def create_regions_keyboard() -> InlineKeyboardMarkup:
    """Создать клавиатуру с регионами"""
    regions = ["General", "America", "Europe", "Japan"]
    
    keyboard = []
    current_row = []
    
    for region in regions:
        if len(current_row) == 2:
            keyboard.append(current_row)
            current_row = []
        
        current_row.append(
            InlineKeyboardButton(
                text=region,
                callback_data=f"region_{region}"
            )
        )
    
    if current_row:
        keyboard.append(current_row)
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# Инициализация бота и диспетчера
bot = Bot(token=config.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Инициализация парсеров
parser_factory = AutodocParserFactory()
search_aggregator = SearchAggregator()

class SearchStates(StatesGroup):
    waiting_for_part_number = State()
    waiting_for_region = State()
    viewing_modifications = State()

class CarSearch(StatesGroup):
    manufacturer = State()
    modifications = State()
    model = State()
    region = State()

async def register_handlers(dp: Dispatcher):
    """Регистрация всех обработчиков"""
    dp.include_router(admin.router)
    dp.include_router(subscription.router)
    dp.include_router(referral.router)

@dp.message(Command("start"))
async def cmd_start(message: types.Message, session: AsyncSession):
    """Обработчик команды /start"""
    metrics.user_commands.labels(command="start").inc()
    
    try:
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
                last_name=message.from_user.last_name,
                registered_at=datetime.utcnow()
            )
            session.add(user)
            await session.commit()
            
            logger.info(
                "new_user_registered",
                telegram_id=user.telegram_id,
                username=user.username
            )
            metrics.new_users.inc()
        
        # Формируем приветственное сообщение
        welcome_text = (
            f"👋 Привет, {message.from_user.first_name}!\n\n"
            "🔍 Я помогу тебе найти автозапчасти по всей России.\n"
            "Просто отправь мне номер детали, и я найду лучшие предложения!"
        )
        
        # Отправляем сообщение с основной клавиатурой
        await message.answer(
            welcome_text,
            reply_markup=get_main_keyboard()
        )
        
        logger.info(
            "start_command_processed",
            telegram_id=user.telegram_id,
            has_subscription=bool(user.subscription)
        )
        
    except Exception as e:
        logger.error(
            "start_command_error",
            error=str(e),
            telegram_id=message.from_user.id
        )
        metrics.error_count.labels(type="start_command").inc()
        await message.answer(
            "Произошла ошибка при обработке команды. Попробуйте позже.",
            reply_markup=get_main_keyboard()
        )

@dp.message(lambda message: message.text == "🔍 Поиск запчастей")
async def search_parts(message: types.Message, state: FSMContext):
    """Обработчик кнопки поиска запчастей"""
    try:
        await state.set_state(SearchStates.waiting_for_part_number)
        await message.answer(
            "🔍 Выберите способ поиска:\n\n"
            "1️⃣ Поиск по номеру детали:\n"
            "   • Пример: 04465-42160\n\n"
            "2️⃣ Поиск по VIN-номеру:\n"
            "   • Пример: JF1BL5KS57G03135T\n\n"
            "3️⃣ Поиск по автомобилю:\n"
            "   • Формат: МАРКА МОДЕЛЬ ГОД\n"
            "   • Пример: HONDA CIVIC 1996\n\n"
            "✍️ Введите ваш запрос в любом из этих форматов:",
            reply_markup=types.ReplyKeyboardRemove()
        )
        logger.info(
            "search_initiated",
            telegram_id=message.from_user.id
        )
        metrics.user_actions.labels(action="search_initiated").inc()
    except Exception as e:
        logger.error(
            "search_initiation_error",
            error=str(e),
            telegram_id=message.from_user.id
        )
        metrics.error_count.labels(type="search_initiation").inc()
        await message.answer(
            "Произошла ошибка. Попробуйте позже.",
            reply_markup=get_main_keyboard()
        )

@dp.message(SearchStates.waiting_for_part_number)
async def handle_part_number(message: types.Message, session: AsyncSession, state: FSMContext):
    """Обработчик ввода номера детали"""
    try:
        query = message.text.strip()
        
        # Проверяем подписку пользователя
        result = await session.execute(
            select(User)
            .options(selectinload(User.subscription))
            .where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one()
        
        if not user.subscription or not user.subscription.is_active:
            await message.answer(
                "⚠️ Для поиска запчастей необходима активная подписка.\n"
                "Оформите подписку, чтобы получить доступ к поиску.",
                reply_markup=get_main_keyboard()
            )
            await state.clear()
            return
        
        # Определяем тип поиска
        search_type = await parser_factory.get_search_type(query)
        
        if search_type == "car":
            # Поиск по марке/модели
            car_info = await parser_factory.extract_car_info(query)
            if car_info:
                brand, model, year = car_info
                await state.update_data(car_info={"brand": brand, "model": model, "year": year})
                await state.set_state(SearchStates.waiting_for_region)
                await message.answer(
                    f"🚗 Найден автомобиль:\n"
                    f"Марка: {brand}\n"
                    f"Модель: {model}\n"
                    f"Год: {year}\n\n"
                    f"Выберите регион поиска:",
                    reply_markup=create_regions_keyboard()
                )
                logger.info(
                    "car_search_success",
                    telegram_id=user.telegram_id,
                    brand=brand,
                    model=model,
                    year=year
                )
            else:
                await message.answer(
                    "❌ Не удалось распознать информацию об автомобиле.\n"
                    "Используйте формат: МАРКА МОДЕЛЬ ГОД\n"
                    "Например: HONDA CIVIC 1996",
                    reply_markup=get_main_keyboard()
                )
                await state.clear()
                
        elif search_type == "vin":
            # Поиск по VIN
            car_info = await parser_factory.extract_car_info(query)
            if car_info:
                await state.update_data(car_info=car_info)
                await state.set_state(SearchStates.waiting_for_region)
                await message.answer(
                    f"🚗 Информация по VIN:\n"
                    f"Марка: {car_info['brand']}\n"
                    f"Модель: {car_info['model']}\n"
                    f"Год: {car_info['year']}\n\n"
                    f"Выберите регион поиска:",
                    reply_markup=create_regions_keyboard()
                )
                logger.info(
                    "vin_search_success",
                    telegram_id=user.telegram_id,
                    vin=query
                )
            else:
                await message.answer(
                    "❌ Не удалось получить информацию по VIN.\n"
                    "Проверьте правильность ввода и попробуйте снова.",
                    reply_markup=get_main_keyboard()
                )
                await state.clear()
                
        else:
            # Поиск по артикулу
            await message.answer("🔍 Ищу запчасти по артикулу...")
            
            results = await search_aggregator.search_all(query)
            if results and any(results.values()):
                # Форматируем результаты
                response = "🔍 Найденные запчасти:\n\n"
                idx = 1
                
                for source, items in results.items():
                    if items:
                        for item in items:
                            if isinstance(item, dict) and item.get('type') != 'car_model':
                                response += f"{idx}. {item.get('name', 'Название не указано')}\n"
                                response += f"📝 Артикул: {item.get('article', query)}\n"
                                response += f"🏭 Производитель: {item.get('brand', 'Не указан')}\n"
                                
                                # Цена
                                price = item.get('price')
                                if price:
                                    response += f"💰 Цена: {price} ₽\n"
                                else:
                                    response += "💰 Цена: По запросу\n"
                                
                                # Магазин
                                response += f"🏪 Магазин: {source.upper()}\n"
                                
                                # Наличие
                                quantity = item.get('quantity')
                                if quantity and quantity > 0:
                                    response += f"✅ В наличии: {quantity} шт.\n"
                                else:
                                    response += "❌ Нет в наличии\n"
                                
                                # Срок доставки
                                delivery = item.get('delivery_days')
                                if delivery:
                                    response += f"🚚 Срок доставки: {delivery} дн.\n"
                                
                                # URL если есть
                                if item.get('url'):
                                    response += f"🔗 {item['url']}\n"
                                
                                response += "\n" + "="*30 + "\n"
                                idx += 1
                
                # Разбиваем на части если сообщение слишком длинное
                max_length = 4096
                for i in range(0, len(response), max_length):
                    chunk = response[i:i + max_length]
                    await message.answer(chunk)
                
                logger.info(
                    "article_search_success",
                    telegram_id=user.telegram_id,
                    query=query,
                    results_count=sum(len(items) for items in results.values())
                )
                metrics.search_results.labels(type="success").inc()
            else:
                await message.answer(
                    "❌ По вашему запросу ничего не найдено.\n"
                    "Проверьте правильность ввода номера детали.",
                    reply_markup=get_main_keyboard()
                )
                await state.clear()
                
                logger.info(
                    "search_no_results",
                    telegram_id=user.telegram_id,
                    query=query
                )
                metrics.search_results.labels(type="no_results").inc()
                
    except Exception as e:
        logger.error(
            "search_error",
            error=str(e),
            telegram_id=message.from_user.id,
            query=message.text
        )
        metrics.error_count.labels(type="search").inc()
        await message.answer(
            "Произошла ошибка при поиске.\n"
            "Попробуйте позже или обратитесь в поддержку.",
            reply_markup=get_main_keyboard()
        )
        await state.clear()

def create_modifications_keyboard(modifications, page=1):
    """Создать клавиатуру с модификациями и пагинацией"""
    # Проверяем, что у нас есть список модификаций
    if not modifications:
        return types.InlineKeyboardMarkup(inline_keyboard=[])

    # Разбиваем на страницы по 5 кнопок
    items_per_page = 5
    total_pages = (len(modifications) + items_per_page - 1) // items_per_page
    
    # Убедимся, что страница в допустимом диапазоне
    page = max(1, min(page, total_pages))
    
    # Получаем модификации для текущей страницы
    start_idx = (page - 1) * items_per_page
    end_idx = min(start_idx + items_per_page, len(modifications))
    current_modifications = modifications[start_idx:end_idx]
    
    # Создаем кнопки для каждой модификации
    keyboard = []
    for mod in current_modifications:
        # Формируем текст кнопки с информацией о модификации
        mod_text = f"{mod['grade']} • {mod['transmission']} • {mod['doors']}д • {mod['dest_region']}"
        callback_data = f"mod_{mod['id']}"
        keyboard.append([types.InlineKeyboardButton(text=mod_text, callback_data=callback_data)])
    
    # Добавляем кнопки пагинации если есть больше одной страницы
    if total_pages > 1:
        nav_buttons = []
        
        # Кнопка "Назад" если не на первой странице
        if page > 1:
            nav_buttons.append(types.InlineKeyboardButton(
                text="◀️",
                callback_data=f"page_{page-1}"
            ))
            
        # Показываем текущую страницу
        nav_buttons.append(types.InlineKeyboardButton(
            text=f"{page}/{total_pages}",
            callback_data="current_page"
        ))
        
        # Кнопка "Вперед" если не на последней странице
        if page < total_pages:
            nav_buttons.append(types.InlineKeyboardButton(
                text="▶️",
                callback_data=f"page_{page+1}"
            ))
            
        keyboard.append(nav_buttons)
    
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard)

@dp.callback_query(lambda c: c.data.startswith('region_'))
async def handle_region_selection(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора региона"""
    try:
        # Получаем выбранный регион
        region = callback_query.data.split('_')[1]
        
        # Получаем сохраненные данные об автомобиле
        data = await state.get_data()
        car_info = data.get('car_info', {})
        
        brand = car_info.get('brand')
        model = car_info.get('model')
        year = car_info.get('year')
        
        logger.info(f"Selected: brand={brand}, model={model}, year={year}, region={region}")
        
        if not all([brand, model, year]):
            await callback_query.answer("Ошибка: неполные данные об автомобиле")
            return
        
        # Создаем парсер и получаем модификации
        parser = AutodocCarParser()
        try:
            modifications_data = await parser.search_modifications(brand, model, year, region)
            logger.info(f"Modifications data: {modifications_data}")
            
            if not modifications_data or not modifications_data.get('modifications'):
                await callback_query.message.edit_text(
                    "❌ Модификации не найдены для выбранного региона.\n"
                    "Попробуйте выбрать другой регион или изменить параметры поиска.",
                    reply_markup=create_regions_keyboard()
                )
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
            keyboard = create_modifications_keyboard(modifications_data.get('modifications', []))
            
            # Форматируем сообщение
            message_text = (
                f"🚗 {brand} {model} {year}\n"
                f"🌍 Регион: {region}\n\n"
                f"Выберите модификацию:"
            )
            
            await callback_query.message.edit_text(
                message_text,
                reply_markup=keyboard
            )
            
            # Устанавливаем состояние просмотра модификаций
            await state.set_state(SearchStates.viewing_modifications)
            
        except Exception as e:
            logger.error(f"Error getting modifications: {str(e)}")
            await callback_query.message.edit_text(
                "❌ Произошла ошибка при получении модификаций.\n"
                "Попробуйте позже или выберите другой регион.",
                reply_markup=create_regions_keyboard()
            )
    
    except Exception as e:
        logger.error(
            "Error in region selection handler",
            error=str(e),
            telegram_id=callback_query.from_user.id
        )
        await callback_query.message.edit_text(
            "Произошла ошибка. Попробуйте начать поиск заново.",
            reply_markup=get_main_keyboard()
        )
        await state.clear()

@dp.callback_query(lambda c: c.data.startswith('page_'))
async def handle_page_selection(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора страницы"""
    try:
        page = int(callback_query.data.split('_')[1])
        data = await state.get_data()
        modifications = data.get('modifications', [])
        keyboard = create_modifications_keyboard(modifications, page)
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
    """Основная функция запуска бота"""
    try:
        # Инициализация базы данных
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        # Настройка middleware
        dp.update.middleware.register(DatabaseMiddleware())
        
        # Регистрация обработчиков
        await register_handlers(dp)
        
        # Запуск Prometheus сервера
        start_http_server(config.PROMETHEUS_PORT)
        logger.info(
            "prometheus_server_started",
            port=config.PROMETHEUS_PORT
        )
        
        # Запуск бота
        logger.info("bot_starting")
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.error("bot_startup_error", error=str(e))
        metrics.error_count.labels(type="startup").inc()
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("bot_shutdown_keyboard_interrupt")
    except Exception as e:
        logger.error("bot_shutdown_error", error=str(e))
    finally:
        logger.info("bot_shutdown_complete")
