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
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

from config import config
from models import Base, User, Subscription
from handlers import admin, subscription, referral
from utils.logger import logger
from utils.metrics import metrics
from database import engine, async_session_maker, DatabaseMiddleware
from keyboards.main import get_main_keyboard, get_search_keyboard
from parsers.autodoc_factory import AutodocParserFactory
from parsers.search_aggregator import SearchAggregator
from parsers.autodoc_car_parser import AutodocCarParser

class SearchStates(StatesGroup):
    waiting_for_part_number = State()
    waiting_for_region = State()
    viewing_modifications = State()

class CarSearchStates(StatesGroup):
    waiting_for_brand = State()
    waiting_for_model = State()
    waiting_for_year = State()
    selecting_field = State()
    selecting_field_value = State()
    viewing_modifications = State()

class CarSearch(StatesGroup):
    manufacturer = State()
    modifications = State()
    model = State()
    region = State()

# def create_regions_keyboard() -> InlineKeyboardMarkup:
#     """Создать клавиатуру с регионами"""
#     regions = ["General", "America", "Europe", "Japan"]
    
#     keyboard = []
#     current_row = []
    
#     for region in regions:
#         if len(current_row) == 2:
#             keyboard.append(current_row)
#             current_row = []
        
#         current_row.append(
#             InlineKeyboardButton(
#                 text=region,
#                 callback_data=f"region_{region}"
#             )
#         )
    
#     if current_row:
#         keyboard.append(current_row)
    
#     return InlineKeyboardMarkup(inline_keyboard=keyboard)

class TelegramBot:
    def __init__(self):
        self.bot = Bot(token=config.BOT_TOKEN)
        self.storage = MemoryStorage()
        self.dp = Dispatcher(storage=self.storage)
        self.parser_factory = AutodocParserFactory()
        self.search_aggregator = SearchAggregator()
        
    async def register_handlers(self):
        """Регистрация всех обработчиков"""
        # Инициализация базы данных
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            
        # Настройка middleware для базы данных
        self.dp.update.middleware.register(DatabaseMiddleware())
        
        # Регистрация роутеров
        self.dp.include_router(admin.router)
        self.dp.include_router(subscription.router)
        self.dp.include_router(referral.router)
        
        # Регистрация основных хендлеров
        self.dp.message.register(self.cmd_start, Command("start"))
        
        # Регистрация хендлеров кнопок основного меню
        self.dp.message.register(self.search_parts, F.text == "🔍 Поиск запчастей")
        self.dp.message.register(self.handle_subscription, F.text == "💳 Подписка")
        self.dp.message.register(self.handle_profile, F.text == "📱 Мой профиль")
        self.dp.message.register(self.handle_help, F.text == "❓ Помощь")
        self.dp.message.register(self.handle_referral, F.text == "👥 Реферальная программа")
        
        # Регистрация хендлеров кнопок поиска
        self.dp.message.register(self.handle_new_search, F.text == "🔄 Новый поиск")
        self.dp.message.register(self.handle_search_history, F.text == "📋 История поиска")
        self.dp.message.register(self.handle_main_menu, F.text == "🏠 Главное меню")
        
        # Регистрация хендлеров кнопок профиля
        self.dp.message.register(self.handle_search_stats, F.text == "📊 Статистика поиска")
        self.dp.message.register(self.handle_settings, F.text == "⚙️ Настройки")
        
        # Регистрация остальных хендлеров
        self.dp.message.register(self.handle_part_number, SearchStates.waiting_for_part_number)
        self.dp.callback_query.register(self.handle_region_selection, lambda c: c.data.startswith("region_"))
        self.dp.callback_query.register(self.handle_page_selection, lambda c: c.data.startswith("page_"))
        self.dp.callback_query.register(self.handle_modification_selection, lambda c: c.data.startswith("mod_"))
        self.dp.message.register(self.handle_car_search, F.text == "🚗 Поиск по авто")
        self.dp.callback_query.register(self.handle_wizard_selection, lambda c: c.data.startswith("wizard_"))
        
        # Регистрация хендлеров для поиска по марке/модели/году
        self.dp.message.register(self.handle_brand_input, CarSearchStates.waiting_for_brand)
        self.dp.message.register(self.handle_model_input, CarSearchStates.waiting_for_model)
        self.dp.message.register(self.handle_year_input, CarSearchStates.waiting_for_year)
        self.dp.callback_query.register(self.handle_field_selection, CarSearchStates.selecting_field)
        self.dp.callback_query.register(self.handle_field_value_selection, CarSearchStates.selecting_field_value)

    @staticmethod
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
                
                logger.info(f"New user registered: {user.telegram_id}")
                
            # Проверяем наличие активной подписки
            has_active_subscription = (
                user.subscription and 
                user.subscription.valid_until and 
                user.subscription.valid_until > datetime.utcnow()
            )
            
            # Отправляем приветственное сообщение
            welcome_text = (
                f"👋 Привет, {message.from_user.first_name}!\n\n"
                "🔍 Я помогу найти запчасти по артикулу или через поиск по авто.\n"
                "Выберите нужный вариант поиска:"
            )
            
            await message.answer(
                welcome_text,
                reply_markup=get_main_keyboard(has_subscription=has_active_subscription)
            )
            
        except Exception as e:
            logger.error(f"Error in start command: {e}")
            await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

    @staticmethod
    async def search_parts(message: types.Message, state: FSMContext):
        """Обработчик кнопки поиска запчастей"""
        await message.answer(
            "Введите артикул запчасти:",
            reply_markup=get_search_keyboard()
        )
        await state.set_state(SearchStates.waiting_for_part_number)

    async def handle_part_number(self, message: types.Message, session: AsyncSession, state: FSMContext):
        """Обработчик ввода номера детали"""
        try:
            part_number = message.text.strip()
            
            if len(part_number) < 3:
                await message.answer("Артикул должен содержать минимум 3 символа. Попробуйте еще раз.")
                return

            # Отправляем сообщение о начале поиска
            await message.answer("🔍 Ищу запчасти по артикулу...")
            
            # Используем search_aggregator для поиска
            results = await self.search_aggregator.search_all(part_number)
            
            if results and any(results.values()):
                # Форматируем результаты
                response = "🔍 Найденные запчасти:\n\n"
                idx = 1
                
                for source, items in results.items():
                    if items:
                        for item in items:
                            if isinstance(item, dict) and item.get('type') != 'car_model':
                                response += f"{idx}. {item.get('name', 'Название не указано')}\n"
                                response += f"📝 Артикул: {item.get('article', part_number)}\n"
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
                    telegram_id=message.from_user.id,
                    query=part_number,
                    results_count=sum(len(items) for items in results.values())
                )
                metrics.search_results.labels(type="success").inc()
            else:
                await message.answer(
                    "❌ По вашему запросу ничего не найдено.\n"
                    "Проверьте правильность ввода номера детали.",
                    reply_markup=get_main_keyboard()
                )
                
                logger.info(
                    "search_no_results",
                    telegram_id=message.from_user.id,
                    query=part_number
                )
                metrics.search_results.labels(type="no_results").inc()
            
            # Очищаем состояние после завершения поиска
            await state.clear()
                
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

    @staticmethod
    async def handle_region_selection(callback_query: types.CallbackQuery, state: FSMContext):
        """Обработчик выбора региона"""
        region = callback_query.data.replace("region_", "")
        data = await state.get_data()
        part_number = data.get("part_number")
        
        if not part_number:
            await callback_query.message.answer("Ошибка: номер детали не найден. Начните поиск заново.")
            await state.clear()
            return
        
        await callback_query.answer()
        
        # Здесь должна быть логика поиска модификаций
        # Временно используем тестовые данные
        modifications = [
            {"id": 1, "name": "Modification 1", "price": 100},
            {"id": 2, "name": "Modification 2", "price": 200},
        ]
        
        if not modifications:
            await callback_query.message.answer(
                "По вашему запросу ничего не найдено. Попробуйте другой артикул или регион."
            )
            await state.clear()
            return
        
        # Сохраняем данные в состоянии
        await state.update_data(
            region=region,
            modifications=modifications,
            current_page=1
        )
        
        # Показываем первую страницу результатов
        keyboard = create_modifications_keyboard(modifications)
        await callback_query.message.answer(
            f"Найдены следующие варианты для артикула {part_number}:",
            reply_markup=keyboard
        )
        await state.set_state(SearchStates.viewing_modifications)

    @staticmethod
    async def handle_page_selection(callback_query: types.CallbackQuery, state: FSMContext):
        """Обработчик выбора страницы"""
        page = int(callback_query.data.replace("page_", ""))
        data = await state.get_data()
        
        modifications = data.get("modifications", [])
        keyboard = create_modifications_keyboard(modifications, page)
        
        await callback_query.message.edit_reply_markup(reply_markup=keyboard)
        await callback_query.answer()

    @staticmethod
    async def handle_modification_selection(callback_query: types.CallbackQuery, state: FSMContext):
        """Обработчик выбора модификации"""
        mod_id = int(callback_query.data.replace("mod_", ""))
        data = await state.get_data()
        
        modifications = data.get("modifications", [])
        selected_mod = next((m for m in modifications if m["id"] == mod_id), None)
        
        if not selected_mod:
            await callback_query.answer("Модификация не найдена")
            return
        
        # Здесь должна быть логика обработки выбранной модификации
        await callback_query.message.answer(
            f"Вы выбрали: {selected_mod['name']}\n"
            f"Цена: {selected_mod['price']} руб."
        )
        await callback_query.answer()
        await state.clear()

    async def handle_car_search(self, message: types.Message, state: FSMContext):
        """Начало поиска по марке/модели/году"""
        await message.answer("Введите марку автомобиля:", reply_markup=types.ReplyKeyboardMarkup(
            keyboard=[[types.KeyboardButton(text="🏠 Главное меню")]], 
            resize_keyboard=True
        ))
        await state.set_state(CarSearchStates.waiting_for_brand)

    async def handle_brand_input(self, message: types.Message, state: FSMContext):
        """Обработка ввода марки"""
        if message.text == "🏠 Главное меню":
            await self.handle_main_menu(message, state)
            return
            
        await state.update_data(brand=message.text.upper())
        await message.answer("Теперь введите модель автомобиля:")
        await state.set_state(CarSearchStates.waiting_for_model)

    async def handle_model_input(self, message: types.Message, state: FSMContext):
        """Обработка ввода модели"""
        if message.text == "🏠 Главное меню":
            await self.handle_main_menu(message, state)
            return
            
        await state.update_data(model=message.text)
        await message.answer("Введите год выпуска:")
        await state.set_state(CarSearchStates.waiting_for_year)

    async def handle_year_input(self, message: types.Message, state: FSMContext):
        """Обработка ввода года"""
        if message.text == "🏠 Главное меню":
            await self.handle_main_menu(message, state)
            return
            
        if not message.text.isdigit():
            await message.answer("Пожалуйста, введите корректный год")
            return
            
        data = await state.get_data()
        brand = data['brand']
        model = data['model']
        year = message.text
        
        parser = AutodocCarParser()
        initial_query = f"{brand} {model} {year}"
        
        search_result = await parser.step_by_step_search(initial_query)
        await state.update_data(
            search_result=search_result,
            current_ssd=None,
            known_values={'Модель': model, 'Год': year}
        )
        
        await self.show_available_fields(message, state)

    async def show_available_fields(self, message: types.Message, state: FSMContext):
        """Показать доступные поля для выбора"""
        data = await state.get_data()
        search_result = data['search_result']
        fields = list(search_result.get('available_fields', {}).items())
        
        if not fields:
            if data.get('current_ssd'):
                await self.show_modifications(message, state)
            else:
                await message.answer("Поиск завершен!")
                await state.clear()
            return
            
        keyboard = []
        for idx, (field_name, _) in enumerate(fields, 1):
            keyboard.append([InlineKeyboardButton(
                text=field_name,
                callback_data=f"field_{idx}"
            )])
        
        keyboard.append([InlineKeyboardButton(
            text="Показать текущие модификации",
            callback_data="show_modifications"
        )])
        
        await message.answer(
            "Выберите поле для уточнения:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        await state.set_state(CarSearchStates.selecting_field)

    async def handle_field_selection(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка выбора поля"""
        if callback.data == "show_modifications":
            await self.show_modifications(callback.message, state)
            return
            
        field_idx = int(callback.data.split('_')[1]) - 1
        data = await state.get_data()
        fields = list(data['search_result'].get('available_fields', {}).items())
        
        if 0 <= field_idx < len(fields):
            field_name, field_data = fields[field_idx]
            keyboard = []
            
            for idx, option in enumerate(field_data['options'], 1):
                keyboard.append([InlineKeyboardButton(
                    text=option['value'],
                    callback_data=f"value_{idx}_{field_idx}"
                )])
                
            await callback.message.edit_text(
                f"Выберите значение для {field_name}:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
            await state.set_state(CarSearchStates.selecting_field_value)

    async def handle_field_value_selection(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка выбора значения поля"""
        value_idx, field_idx = map(int, callback.data.split('_')[1:])
        data = await state.get_data()
        fields = list(data['search_result'].get('available_fields', {}).items())
        field_name, field_data = fields[field_idx]
        
        selected_option = field_data['options'][value_idx - 1]
        current_ssd = selected_option['key']
        
        parser = AutodocCarParser()
        search_result = await parser.step_by_step_search({
            'brand_code': data['search_result'].get('brand_code'),
            'ssd': current_ssd
        })
        
        await state.update_data(
            search_result=search_result,
            current_ssd=current_ssd
        )
        
        await self.show_available_fields(callback.message, state)

    async def show_modifications(self, message: types.Message, state: FSMContext):
        """Показать модификации"""
        data = await state.get_data()
        parser = AutodocCarParser()
        
        mod_result = await parser.display_modifications(
            data['search_result'].get('brand_code'),
            data['current_ssd']
        )
        
        if mod_result:
            car_id, ssd = mod_result
            parts_data = await parser.get_parts_list(
                data['search_result'].get('brand_code'),
                car_id,
                ssd
            )
            
            # Преобразуем дерево запчастей в текстовый формат для отправки
            parts_text = self.format_parts_tree(parts_data)
            
            # Разбиваем длинное сообщение на части, если необходимо
            for part in self.split_long_message(parts_text):
                await message.answer(part)
                
        await state.clear()
        await message.answer(
            "Поиск завершен! Выберите действие:",
            reply_markup=get_main_keyboard()
        )

    def format_parts_tree(self, parts_data, level=0):
        """Форматирование дерева запчастей в текст"""
        result = []
        indent = "  " * level
        
        for item in parts_data:
            result.append(f"{indent}📦 {item['name']}")
            if 'children' in item:
                result.extend(self.format_parts_tree(item['children'], level + 1))
                
        return "\n".join(result)

    def split_long_message(self, text, max_length=4096):
        """Разбивка длинного сообщения на части"""
        return [text[i:i+max_length] for i in range(0, len(text), max_length)]

    async def handle_wizard_selection(self, callback_query: types.CallbackQuery, state: FSMContext):
        """Обработчик выбора опции в wizard"""
        # Здесь должна быть логика обработки выбора в wizard
        await callback_query.answer("Функция в разработке")

    async def start(self):
        """Запуск бота"""
        try:
            # Регистрируем обработчики
            await self.register_handlers()
            
            # Запуск бота
            logger.info("bot_starting")
            await self.dp.start_polling(self.bot)
            
        except Exception as e:
            logger.error("bot_startup_error", error=str(e))
            metrics.error_count.labels(type="startup").inc()
            raise

    async def handle_subscription(self, message: types.Message):
        """Обработчик кнопки подписки"""
        await message.answer("Информация о подписке и доступных тарифах")

    async def handle_profile(self, message: types.Message):
        """Обработчик кнопки профиля"""
        await message.answer(
            "Ваш профиль",
            reply_markup=get_profile_keyboard()
        )

    async def handle_help(self, message: types.Message):
        """Обработчик кнопки помощи"""
        help_text = (
            "🤖 Как пользоваться ботом:\n\n"
            "1. Поиск запчастей - поиск по артикулу или VIN\n"
            "2. Подписка - информация о тарифах\n"
            "3. Профиль - ваши данные и настройки\n"
            "4. Реферальная программа - приглашайте друзей\n\n"
            "По всем вопросам обращайтесь к @admin"
        )
        await message.answer(help_text)

    async def handle_referral(self, message: types.Message):
        """Обработчик кнопки реферальной программы"""
        await message.answer("Информация о реферальной программе")

    async def handle_new_search(self, message: types.Message, state: FSMContext):
        """Обработчик кнопки нового поиска"""
        await self.search_parts(message, state)

    async def handle_search_history(self, message: types.Message):
        """Обработчик кнопки истории поиска"""
        await message.answer("История ваших поисков")

    async def handle_main_menu(self, message: types.Message):
        """Обработчик кнопки главного меню"""
        await message.answer(
            "Главное меню",
            reply_markup=get_main_keyboard()
        )

    async def handle_search_stats(self, message: types.Message):
        """Обработчик кнопки статистики поиска"""
        await message.answer("Статистика ваших поисков")

    async def handle_settings(self, message: types.Message):
        """Обработчик кнопки настроек"""
        await message.answer("Настройки профиля")
