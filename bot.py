import sys
import locale
import json

# Устанавливаем кодировку для консоли
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    locale.setlocale(locale.LC_ALL, 'Russian_Russia.1251')

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
from typing import Dict

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
from utils.response_logger import response_logger

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
    viewing_parts_tree = State()

class CarSearch(StatesGroup):
    manufacturer = State()
    modifications = State()
    model = State()
    region = State()

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
            
        # Настройка middleware для баз данных
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
        self.dp.message.register(self.handle_settings, F.text == "⚙ Настройки")
        
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
        self.dp.callback_query.register(self.handle_back_to_fields, lambda c: c.data == "back_to_fields")
        
        # Добавляем обработчики для модификаций
        self.dp.callback_query.register(
            self.handle_modification_selection,
            lambda c: c.data.startswith("select_mod_")
        )
        
        self.dp.callback_query.register(
            self.handle_back_to_modifications,
            lambda c: c.data == "back_to_modifications"
        )
        
        # Добавляем обработчик навигации по дереву запчастей
        self.dp.callback_query.register(
            self.handle_parts_navigation,
            lambda c: c.data.startswith("parts_select_") or c.data == "parts_back"
        )
        
        # Добавляем обработчики для состояния просмотра дерева запчастей
        self.dp.callback_query.register(
            self.handle_parts_navigation,
            CarSearchStates.viewing_parts_tree,
            lambda c: c.data.startswith("parts_select_") or c.data == "parts_back"
        )
        
        self.dp.callback_query.register(
            self.handle_back_to_modifications,
            CarSearchStates.viewing_parts_tree,
            lambda c: c.data == "back_to_modifications"
        )
        
        # Добавляем обработчик переключения страниц модификаций
        self.dp.callback_query.register(
            self.handle_modification_page,
            lambda c: c.data.startswith("mod_page_")
        )
        
        # Добавляем обработчик выбора запчасти
        self.dp.callback_query.register(
            self.handle_spare_part_selection,
            lambda c: c.data.startswith("spare_part_")
        )

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
                "🔍 Я помогу найти запчаст по артикулу или ����рез поиск по ��вт����.\n"
                "Выберите ужн вариант оиска:"
            )
            
            await message.answer(
                welcome_text,
                reply_markup=get_main_keyboard(has_subscription=has_active_subscription)
            )
            
        except Exception as e:
            logger.error(f"Error in start command: {e}")
            await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

    async def search_parts(self, message: types.Message, state: FSMContext):
        """Начало поиска запчастей"""
        await message.answer(
            "Введите артикул, VIN-номер или информацию об автомоле в формате: МАРКА ОДЕЛЬ ГОД\n"
            "Например: honda civic 1996",
            reply_markup=types.ReplyKeyboardMarkup(
                keyboard=[[types.KeyboardButton(text="🏠 Главное меню")]], 
                resize_keyboard=True
            )
        )
        await state.set_state(SearchStates.waiting_for_part_number)

    async def handle_part_number(self, message: types.Message, state: FSMContext):
        """Обр����ботка ввода артикула/VIN или н��ормации об авто"""
        if message.text == "🏠 Главное меню":
            await self.handle_main_menu(message, state)
            return

        # Прове��яем формат ввода
        parts = message.text.strip().split()
        
        if len(parts) >= 3 and parts[-1].isdigit():
            # Это поиск по марке/модели/году
            brand = parts[0].upper()  # AUDI
            model = parts[1]          # 100
            year = parts[-1]          # 1996
            
            parser = AutodocCarParser()
            initial_query = f"{brand} {model} {year}"
            
            search_result = await parser.step_by_step_search(initial_query)
            if not search_result:
                await message.answer("Не удалось найти информацию по указанному автомобилю. Проверьте правильность ввода.")
                return

            # Используем словарь алиасов для стандартизации параметров
            known_values = {
                'Model': model,            # 100 - будет сопоставлено с 'Модель'
                'year': year,             # 1996 - будет с��поставлен��������������������������������������� с обоими вар��антами года
                'Brand': brand            # AUDI - будет сопоставлено с 'Марка'
            }
            standardized_values = response_logger.standardize_parameters(known_values)
            logger.info(f"[ПОИСК] Стандартизированные значения: {standardized_values}")

            # Пробуем автозаполнить поля на первом шаге
            current_ssd = None
            fields = list(search_result.get('available_fields', {}).items())
            auto_filled = False

            # Проверяем каждое по��е на возможность автозаполнения
            for field_name, field_data in fields:
                standard_key = response_logger.get_parameter_key(field_name)
                if standard_key in standardized_values:
                    target_value = standardized_values[standard_key]
                    logger.info(f"[ПОИСК] Проверяем поле {field_name} ({standard_key}) со значением {target_value}")
                    
                    # Для года пробуем оба варианта
                    if field_name.lower() in ['год', 'год выпуска', 'год производсва']:
                        # Проверям точное совпадение для обоих вариантов года
                        for option in field_data['options']:
                            if target_value == option['value']:
                                current_ssd = option['key']
                                logger.info(f"[ПОИСК] Найдено точное совпадение года: {option['value']}, ssd={current_ssd}")
                                auto_filled = True
                                
                                # Пол��чаем обновл��нные данные
                                search_result = await parser.step_by_step_search({
                                    'brand_code': search_result.get('brand_code'),
                                    'ssd': current_ssd
                                })
                                
                                # Если есть еще поля для заполнения, продолжаем
                                if not search_result.get('available_fields'):
                                    break
                                
                                # Иначе продолжаем проверку других полей
                                continue
                    
                    # Для стальны�� полей используем частичное совпадение
                    else:
                        for option in field_data['options']:
                            if target_value.upper() in option['value'].upper():
                                current_ssd = option['key']
                                logger.info(f"[ПОИСК] Найдено совпадение: {option['value']}, ssd={current_ssd}")
                                auto_filled = True
                                
                                search_result = await parser.step_by_step_search({
                                    'brand_code': search_result.get('brand_code'),
                                    'ssd': current_ssd
                                })
                                break
                    
                    if auto_filled:
                        break

            # Если удалось что-то автозаполнить, обновляем состояние
            if auto_filled:
                logger.info("[ПОИСК] Выполнено автозаполнение")
                await state.update_data(
                    search_result=search_result,
                    current_ssd=current_ssd,
                    known_values=standardized_values
                )
                # Показываем следующие доступные поля или модификац��и
                search_message = await message.answer("Выпо��няется поиск...")
                await self.show_available_fields(search_message, state)
                return

            # Если автозаполнение не сработало, показываем все доступные поля
            keyboard = []
            for idx, (field_name, _) in enumerate(fields, 1):
                display_name = response_logger.get_parameter_key(field_name)
                keyboard.append([InlineKeyboardButton(
                    text=display_name,
                    callback_data=f"field_{idx}"
                )])
            
            keyboard.append([InlineKeyboardButton(
                text="Показать текущие модификации",
                callback_data="show_modifications"
            )])
            
            search_message = await message.answer(
                "Выберите поле для уточнения:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
            
            await state.update_data(
                search_result=search_result,
                current_ssd=None,
                known_values=standardized_values,
                message_id=search_message.message_id
            )
            await state.set_state(CarSearchStates.selecting_field)

    @staticmethod
    async def handle_region_selection(callback_query: types.CallbackQuery, state: FSMContext):
        """Обработчик выбора региона"""
        region = callback_query.data.replace("region_", "")
        data = await state.get_data()
        part_number = data.get("part_number")
        
        if not part_number:
            await callback_query.message.answer("Ошибка: номер де��али не найден. Начните писк заново.")
            await state.clear()
            return
        
        await callback_query.answer()
        
        # Здесь должна быть логика поиска моифиаций
        # Временно используем тестовые данные
        modifications = [
            {"id": 1, "name": "Modification 1", "price": 100},
            {"id": 2, "name": "Modification 2", "price": 200},
        ]
        
        if not modifications:
            await callback_query.message.answer(
                "По вашему запосу ничего не найдено. Попробуйте другой артикул или регион."
            )
            await state.clear()
            return
        
        # Сохраняем данны�� в состояни��
        await state.update_data(
            region=region,
            modifications=modifications,
            current_page=1
        )
        
        # Показываем первую страницу результатов
        keyboard = create_modifications_keyboard(modifications)
        await callback_query.message.answer(
            f"Най����ены следующие ваианты дл артику��а {part_number}:",
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

    async def handle_modification_selection(self, callback_query: types.CallbackQuery, state: FSMContext):
        """Обработка выбор�� конкретной модифик��ции"""
        try:
            mod_id = callback_query.data.split('_')[2]
            data = await state.get_data()
            modifications = data.get('modifications', [])
            
            # Находим выбранную модификацию
            selected_mod = next((mod for mod in modifications if str(mod['id']) == mod_id), None)
            
            if not selected_mod:
                await callback_query.answer("Модифкация не найдена")
                return
            
            try:
                parser = AutodocCarParser()
                brand_code = data['search_result'].get('brand_code')
                logger.info(f"Getting parts list for brand_code={brand_code}, car_id={selected_mod['id']}, ssd={selected_mod['car_ssd']}")
                parts_data = await parser.get_parts_list(
                    brand_code, 
                    selected_mod['id'],
                    selected_mod['car_ssd']
                )
                
                # Логируем данные о ереве запчастей
                response_logger.log_parts_data(parts_data)
                
                if not parts_data or 'data' not in parts_data:
                    await callback_query.answer("Список запч��ст��й недоступен")
                    return

                # Получае�� корневые категории
                root_categories = parts_data['data']
                
                # Сохраняем данные в состоянии
                await state.update_data(
                    current_parts_data=root_categories,
                    current_path=[],
                    selected_modification=selected_mod
                )
                
                # Формируем текст со спецификацией
                spec_text = f"🚗 {selected_mod.get('grade', 'Н/Д')} {selected_mod.get('transmission', 'Н/Д')}"
                if selected_mod.get('doors') != 'Н/Д':
                    spec_text += f" ({selected_mod.get('doors', 'Н/Д')})"
                
                # Создаем клавиатуру для корневых категорий
                keyboard = []
                
                # Добавляем только категории верхнего уровня
                for idx, category in enumerate(root_categories):
                    if isinstance(category, dict) and 'name' in category:
                        name = category['name']
                        if len(name) > 30:
                            name = name[:27] + "..."
                        keyboard.append([InlineKeyboardButton(
                            text=f"📦 {name}",
                            callback_data=f"parts_select_{idx}"
                        )])
                        logger.info(f"Added category button: {name}")
                
                # Добавляем кнопку возврата
                keyboard.append([InlineKeyboardButton(
                    text="���️ К модификациям",
                    callback_data="back_to_modifications"
                )])
                
                await callback_query.message.edit_text(
                    spec_text,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
                )
                
                await state.set_state(CarSearchStates.viewing_parts_tree)
                await callback_query.answer()
                
            except Exception as e:
                logger.error(f"Error getting parts list: {e}", exc_info=True)
                await callback_query.answer("Ошибка при получении списк запчастей")
                return
                
        except Exception as e:
            logger.error(f"Error handling modification selection: {e}", exc_info=True)
            await callback_query.answer("Пр��из��шла ошибка пр�� получении данных")

    async def handle_parts_navigation(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка навигации по дереву запчастей"""
        try:
            data = await state.get_data()
            current_path = data.get('current_path', [])
            parts_data = data.get('current_parts_data', [])
            
            # Удаляем все сообщения со списком запчастей, кроме последнего
            message_ids = data.get('spare_parts_messages', [])
            if message_ids:
                # Удаляем все сообщения кроме последнего
                for msg_id in message_ids[:-1]:
                    try:
                        await callback.message.bot.delete_message(
                            chat_id=callback.message.chat.id,
                            message_id=msg_id
                        )
                    except Exception as e:
                        logger.error(f"Error deleting message {msg_id}: {e}")
            
            if callback.data == "parts_back":
                # Возвращаемся на уровень выше
                if current_path:
                    current_path.pop()
                    await state.update_data(current_path=current_path)
                    await self.show_parts_level(callback.message, state)
                else:
                    # Если мы ��а верхнем уровне, возвращаемся к модификациям
                    # Удаляем последнее сообщение со списком запчастей
                    if message_ids and len(message_ids) > 0:
                        try:
                            await callback.message.bot.delete_message(
                                chat_id=callback.message.chat.id,
                                message_id=message_ids[-1]
                            )
                        except Exception as e:
                            logger.error(f"Error deleting last message: {e}")
                    await self.handle_back_to_modifications(callback, state)
            else:
                # Переходим на уровень ниже
                selected_idx = int(callback.data.split('_')[2])
                
                # Получаем текущий уровень
                current_level = parts_data
                for index in current_path:
                    current_level = current_level[index].get('children', [])
                
                selected_item = current_level[selected_idx]
                
                # Проверяем наличие подуровней и возможность поиска
                if 'children' in selected_item and selected_item['children']:
                    current_path.append(selected_idx)
                    await state.update_data(current_path=current_path)
                    await self.show_parts_level(callback.message, state)
                elif selected_item.get('canBeSearched', False):
                    # Если это конечный узел и можно искать, показываем список запчастей
                    await self.show_spare_parts_list(callback, selected_item, state)
                else:
                    await callback.answer("Эта категория недоступна для поиска")
            
            await callback.answer()
            
        except Exception as e:
            logger.error(f"Error in parts navigation: {e}", exc_info=True)
            await callback.answer("Произошла ошибка при навигации")

    async def handle_car_search(self, message: types.Message, state: FSMContext):
        """Начало поиска по марке/модели/году"""
        await message.answer("Введите марку автомобил��:", reply_markup=types.ReplyKeyboardMarkup(
            keyboard=[[types.KeyboardButton(text="🏠 Главное меню")]], 
            resize_keyboard=True
        ))
        await state.set_state(CarSearchStates.waiting_for_brand)

    async def handle_brand_input(self, message: types.Message, state: FSMContext):
        """Обработка ввода мари"""
        if message.text == "🏠 Главное меню":
            await self.handle_main_menu(message, state)
            return
            
        await state.update_data(brand=message.text.upper())
        await message.answer("Тепь введите модль автомобиля:")
        await state.set_state(CarSearchStates.waiting_for_model)

    async def handle_model_input(self, message: types.Message, state: FSMContext):
        """О��р����ботка ввода ����дели"""
        if message.text == "🏠 Главное меню":
            await self.handle_main_menu(message, state)
            return
            
        await state.update_data(model=message.text)
        await message.answer("Ведите год выпуска:")
        await state.set_state(CarSearchStates.waiting_for_year)

    async def handle_year_input(self, message: types.Message, state: FSMContext):
        """Обработка в��ода го��а"""
        if message.text == "🏠 Главное меню":
            await self.handle_main_menu(message, state)
            return
            
        if not message.text.isdigit():
            await message.answer("Пожалуйста, вве��ите корректны�� год")
            return
            
        data = await state.get_data()
        brand = data['brand']
        model = data['model']
        year = message.text
        
        parser = AutodocCarParser()
        initial_query = f"{brand} {model} {year}"
        
        search_result = await parser.step_by_step_search(initial_query)
        # Отправляем первое сообщени��� и сохраняем его ID
        search_message = await message.answer("Выпо��няется поиск...")
        await state.update_data(
            search_result=search_result,
            current_ssd=None,
            known_values={'Модель': model, 'Год': year},
            message_id=search_message.message_id
        )
        
        await self.show_available_fields(search_message, state)

    async def show_available_fields(self, message: types.Message, state: FSMContext):
        """Показать доступые поля для выбора"""
        data = await state.get_data()
        search_result = data['search_result']
        fields = list(search_result.get('available_fields', {}).items())
        
        if not fields:
            if data.get('current_ssd'):
                await self.show_modifications(message, state)
            else:
                await message.edit_text("Поиск заверше��!")
                await state.clear()
            return

        # Проверяем можно ли автозаполнить какие-то п��ля
        known_values = data.get('known_values', {})
        current_ssd = data.get('current_ssd')
        auto_filled = False
        parser = AutodocCarParser()
        
        for field_name, field_data in fields:
            if field_name in known_values:
                target_value = known_values[field_name]
                for option in field_data['options']:
                    if target_value.upper() in option['value'].upper():
                        current_ssd = option['key']
                        search_result = await parser.step_by_step_search({
                            'brand_code': search_result.get('brand_code'),
                            'ssd': current_ssd
                        })
                        auto_filled = True
                        await state.update_data(
                            search_result=search_result,
                            current_ssd=current_ssd
                        )
                        logger.info(f"Auto filled: {search_result}, current_ssd: {current_ssd}")
                        await self.show_available_fields(message, state)
                        return
                if auto_filled:
                    return
            
        # Если ничего не автозаполнилось, показываем доступные поля
        keyboard = []
        for idx, (field_name, _) in enumerate(fields, 1):
            keyboard.append([InlineKeyboardButton(
                text=field_name,
                callback_data=f"field_{idx}"
            )])
        
        keyboard.append([InlineKeyboardButton(
            text="Показать тек��щие модификации",
            callback_data="show_modifications"
        )])
        
        await message.edit_text(
            "Выберите поле для уточнения:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        await state.set_state(CarSearchStates.selecting_field)

    async def handle_field_selection(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка выбора поля"""
        try:
            # Проверяем специальные callback_data
            if callback.data == "show_modifications":
                await self.show_modifications(callback.message, state)
                await callback.answer()
                return
            elif callback.data == "back_to_fields":
                await self.handle_back_to_fields(callback, state)
                await callback.answer()
                return
            
            # Обработка выбо��а конкретного поля
            parts = callback.data.split('_')
            if len(parts) < 2 or not parts[1].isdigit():
                logger.error(f"Invalid callback data format: {callback.data}")
                await callback.answer("Неверный формат данных")
                return
            
            field_idx = int(parts[1]) - 1
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
                    
                keyboard.append([InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data="back_to_fields"
                )])
                    
                await callback.message.edit_text(
                    f"Выберите значение для {field_name}:",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
                )
                await state.set_state(CarSearchStates.selecting_field_value)
                await callback.answer()
            else:
                await callback.answer("Неверны индекс поля")
                
        except Exception as e:
            logger.error(f"Error in field selection: {e}", exc_info=True)
            await callback.answer("Произошла ошибка при выборе по��я")

    async def handle_field_value_selection(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработ��а выбора значения поля"""
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
        
        # Пр��веряем можно ли автозаполнить какие-то поля
        known_values = data.get('known_values', {})
        available_fields = search_result.get('available_fields', {})
        
        # Цикл автозаполнения - проверяем вс�� поля
        while True:
            auto_filled = False
            current_fields = list(search_result.get('available_fields', {}).items())
            
            for field_name, field_data in current_fields:
                if field_name in known_values:
                    target_value = known_values[field_name]
                    for option in field_data['options']:
                        if target_value.upper() in option['value'].upper():
                            current_ssd = option['key']
                            search_result = await parser.step_by_step_search({
                                'brand_code': search_result.get('brand_code'),
                                'ssd': current_ssd
                            })
                            auto_filled = True
                            await state.update_data(
                                search_result=search_result,
                                current_ssd=current_ssd
                            )
                            break
                    if auto_filled:
                        break
            
            # Если ничего не автозаполнилось, выходим из цикла
            if not auto_filled:
                break
        
        # Показываем обновле��ные по��я
        fields = list(search_result.get('available_fields', {}).items())
        if not fields:
            if current_ssd:
                await self.show_modifications(callback.message, state)
            else:
                await callback.message.edit_text("Поиск завершен!")
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
        
        await callback.message.edit_text(
            "Выберите пол�� для уточнения:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        await state.set_state(CarSearchStates.selecting_field)
        await callback.answer()

    async def search_modifications(self, brand_code: str, current_ssd: str) -> str:
        """Поиск модификаций и полчение списка запчастей"""
        logger.info(f"Searching modifications with brand_code={brand_code}, current_ssd={current_ssd}")
        parser = AutodocCarParser()
        
        if current_ssd:
            logger.info("Getting modifications...")
            mod_result = await parser.display_modifications(brand_code, current_ssd)
            logger.info(f"Got modifications result: {mod_result}")
            
            if mod_result:
                car_id, ssd = mod_result
                logger.info(f"Getting parts list for car_id={car_id}, ssd={ssd}")
                parts_data = await parser.get_parts_list(brand_code, car_id, ssd)
                logger.info(f"Got parts data: {parts_data}")
                return parser.display_parts_tree(parts_data)
        return None

    async def show_modifications(self, message: types.Message, state: FSMContext):
        """Пок��зать мо��ификации"""
        try:
            data = await state.get_data()
            logger.info(f"[МОДИФИКАЦИИ] Данные состояния: {data}")
            
            if not data.get('current_ssd'):
                logger.error("[МОДИФИКАЦИИ] Отсутствует current_ssd в данных состояния")
                await message.edit_text(
                    "Сначала нужно выбрать все необходимые параметры автомобиля.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_fields")
                    ]])
                )
                return
            
            parser = AutodocCarParser()
            brand_code = data['search_result'].get('brand_code')
            current_ssd = data.get('current_ssd')
            
            logger.info(f"[МОДИ����КАЦИИ] Запрос модификаций: brand_code={brand_code}, ssd={current_ssd}")
            modifications = await parser.get_wizard_modifications(brand_code, current_ssd)
            
            # Логируем полученные данные для анализа
            response_logger.log_modification_data(modifications)
            
            logger.info(f"[МОДИФИКАЦИИ] Получен ответ: {modifications}")
            
            if not modifications or not modifications.get('specificAttributes'):
                logger.warning("[МОДИФИКАЦИИ] Модификации не найдены в ответе")
                await message.edit_text(
                    "Модификации не найдены",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_fields")
                    ]])
                )
                return
            
            # Анализруем структуру данных
            specific_attrs = modifications.get('specificAttributes', [])
            logger.info(f"[МОДИФИКАЦИИ] Количество модификаций: {len(specific_attrs)}")
            if specific_attrs:
                logger.info(f"[МОДИФИКАЦИИ] Пример атрибутов первой модификации: {specific_attrs[0].get('attributes', [])}")
            
            # Форматируем модификации для отображени��
            formatted_mods = []
            keyboard = []
            
            for mod in specific_attrs:
                try:
                    attributes = {attr['key']: attr['value'] for attr in mod.get('attributes', [])}
                    car_id = mod.get('carId')
                    car_ssd = next((attr['value'] for attr in mod.get('attributes', []) if attr['key'] == 'Ssd'), None)
                    
                    formatted_mod = {
                        'id': car_id,
                        'car_ssd': car_ssd
                    }
                    
                    # Получаем отформатированную инфомацию о подфикации
                    info_parts = response_logger.get_modification_info(attributes)
                    formatted_mod.update(attributes)  # Сохраняем все атрибуты
                    formatted_mods.append(formatted_mod)
                    
                    # Создаем текст для кнопки
                    button_text = " | ".join(info_parts) if info_parts else "Комплектация не указана"
                    if len(button_text) > 35:
                        button_text = button_text[:32] + "..."
                    
                    keyboard.append([InlineKeyboardButton(
                        text=button_text,
                        callback_data=f"select_mod_{formatted_mod['id']}"
                    )])
                    
                except Exception as e:
                    logger.error(f"[МОДИФИКАЦИИ] Ошибка форматирования модификации: {e}", exc_info=True)
                    continue
            
            # Добавляем кнопку "Назад"
            keyboard.append([InlineKeyboardButton(
                text="◀️ Назад к полям",
                callback_data="back_to_fields"
            )])
            
            # Формируем текст с общей информацией
            common_info = parser.format_common_info(modifications.get('commonAttributes', []))
            logger.info(f"[МОДИФИКАЦИИ] Общая информация: {common_info}")
            
            info_text = "📋 Общая информация:\n"
            important_fields = ['Бренд', 'Модель', 'Гд', 'Регион']
            for key, value in common_info.items():
                if key in important_fields and value and value != 'Н/Д':
                    info_text += f"• {key}: {value}\n"
            
            info_text += "\nДоступные модификации:"
            
            await message.edit_text(
                info_text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
            
            # Сохраняем модификации в состоянии
            await state.update_data(modifications=formatted_mods)
            await state.set_state(CarSearchStates.viewing_modifications)
            
        except Exception as e:
            logger.error(f"[МОДИФИКАЦИИ] Ошибка ��тображения модификаций: {e}", exc_info=True)
            await message.edit_text(
                "Произошла ошибка при получении модификаций",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_fields")
                ]])
            )

    # Добавляем обработчик переключения страниц
    async def handle_modification_page(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка переключения страниц модификаций"""
        try:
            page = int(callback.data.split('_')[2])
            await self.show_modifications(callback.message, state, page)
            await callback.answer()
        except Exception as e:
            logger.error(f"Error handling modification page: {e}", exc_info=True)
            await callback.answer("Произошла ошибка при переключени страницы")

    async def handle_back_to_fields(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка возврата к выбору полей"""
        data = await state.get_data()
        search_result = data.get('search_result', {})
        fields = list(search_result.get('available_fields', {}).items())
        
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
        
        await callback.message.edit_text(
            "Выберите пол для уточнения:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        await state.set_state(CarSearchStates.selecting_field)
        await callback.answer()

    def format_parts_tree(self, parts_data, level=0):
        """Фо��матиро��ание дере��а зачастей в текст"""
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
            # Реисрируем обраотчики
            await self.register_handlers()
            
            # апуск бота
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
            "🤖 Как пльзоваться ботом:\n\n"
            "1. Поиск запчастей - писк ��о артикулу или VIN\n"
            "2. Подписка - информация о тарифах\n"
            "3. Профиль - ваи данные и настройки\n"
            "4. Реферальная программа - приглашайте друзей\n\n"
            "По всем вопросам обраща��тесь к @admin"
        )
        await message.answer(help_text)

    async def handle_referral(self, message: types.Message):
        """Обработчик кнопки реферальной программы"""
        await message.answer("Информация о реферальной программе")

    async def handle_new_search(self, message: types.Message):
        """Обработчик кнопки нового поиска"""
        await self.search_parts(message)

    async def handle_search_history(self, message: types.Message):
        """Обработчик кнопки истории поиска"""
        await message.answer("История ваших писков")

    async def handle_main_menu(self, message: types.Message):
        """Обработчик кнопки главного меню"""
        await message.answer(
            "Главное меню",
            reply_markup=get_main_keyboard()
        )

    async def handle_search_stats(self, message: types.Message):
        """Обработчик кн��пки статистики оска"""
        await message.answer("Статистика ваших писков")

    async def handle_settings(self, message: types.Message):
        """Обработчик кнопки настроек"""
        await message.answer("Настройки пр��фил")

    async def handle_back_to_modifications(self, callback: types.CallbackQuery, state: FSMContext):
        """Обрботчи возврата к списку модификаций"""
        try:
            await self.show_modifications(callback.message, state)
            await callback.answer()
        except Exception as e:
            logger.error(f"Error handling back to modifications: {e}")
            await callback.answer("Произошла ошибка при возврате к списку модификаций")

    async def show_part_details(self, callback: types.CallbackQuery, part_info: dict):
        """Показть детальную информаци о запчасти"""
        try:
            info_text = f"📦 Деталь: {part_info['name']}\n\n"
            
            # Добавляем основную информацию
            if 'article' in part_info:
                info_text += f"Артикул: {part_info['article']}\n"
            if 'oem' in part_info:
                info_text += f"OEM: {part_info['oem']}\n"
            
            # Добавляем дополнительную информацию в сокращенном виде
            if 'description' in part_info and part_info['description']:
                desc = part_info['description']
                if len(desc) > 100:
                    desc = desc[:97] + "..."
                info_text += f"\nОписание: {desc}\n"
            
            # Создаем клавиатуру
            keyboard = [
                [InlineKeyboardButton(text="🔍 Найти аналоги", callback_data=f"find_analogs_{part_info.get('article', '')}")],
                [InlineKeyboardButton(text="🛒 Купить", callback_data=f"buy_part_{part_info.get('article', '')}")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="parts_back")]
            ]
            
            await callback.message.edit_text(
                info_text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
            
        except Exception as e:
            logger.error(f"Error showing part details: {e}", exc_info=True)
            await callback.answer("Произошла ошибка при отображении информации о детали")

    async def show_spare_parts_list(self, callback: types.CallbackQuery, part_info: dict, state: FSMContext):
        """Показать список запчастей для выбранной категории"""
        try:
            data = await state.get_data()
            selected_mod = data.get('selected_modification', {})
            brand_code = data['search_result'].get('brand_code')
            
            parts_data = await self.get_group_parts(
                brand_code,
                selected_mod['id'],
                part_info['quickGroupId'],
                selected_mod['car_ssd']
            )
            
            response_logger.log_spare_parts_data(parts_data)
            
            if not parts_data or 'items' not in parts_data:
                await callback.answer("Список запчастей недоступен")
                return
            
            items = parts_data['items']
            
            # Формируем информацию о текущем узле с HTML-разметкой
            unit_info = ""
            
            # Добавляем схему узла в начало сообщения, если она есть
            if items and 'imageUrl' in items[0]:
                image_url = items[0]['imageUrl'].replace('%size%', 'source')
                unit_info = f'<a href="{image_url}">⁠</a>'
            
            unit_info += f"📦 {part_info['name']}\n\n"
            
            # Группируем запчасти по позициям
            positions = {}
            for item in items:
                spare_parts = item.get('spareParts', [])
                for part in spare_parts:
                    code = part.get('codeOnImage', 'Без номера')
                    if code not in positions:
                        positions[code] = []
                    
                    article_info = {
                        'number': part.get('partNumber', 'Н/Д'),
                        'name': part.get('name', ''),
                        'manufacturer': part.get('manufacturer', 'Оригинал')
                    }
                    positions[code].append(article_info)
            
            # Сортируем позиции по номеру
            def get_position_number(pos):
                try:
                    return int(pos) if pos != 'Без номера' else float('inf')
                except ValueError:
                    return float('inf')
            
            sorted_positions = sorted(positions.items(), key=lambda x: get_position_number(x[0]))
            
            MAX_MESSAGE_LENGTH = 4096
            messages = []
            current_message = ""
            
            # Добавляем заголовок и схему в первое сообщение
            current_message = ""
            if items and 'imageUrl' in items[0]:
                image_url = items[0]['imageUrl'].replace('%size%', 'source')
                current_message = f'<a href="{image_url}">⁠</a>'
            
            current_message += f"📦 {part_info['name']}\n\n"
            
            # Формируем сообщения с артикулами
            for code, articles in sorted_positions:
                # Формируем блок для текущей позиции
                position_block = ""
                if code != 'Без номера':
                    position_block += f"📍 Позиция {code}:\n"
                else:
                    position_block += f"\n📍 Дополнительные артикулы:\n"
                
                sorted_articles = sorted(articles, 
                    key=lambda x: (x['manufacturer'] != 'Оригинал', x['manufacturer'], x['name']))
                
                for article in sorted_articles:
                    article_line = f"• {article['name']} - {article['number']}"
                    if article['manufacturer'] != 'Оригинал':
                        article_line += f" ({article['manufacturer']})"
                    article_line += "\n"
                    position_block += article_line
                position_block += "\n"
                
                # Проверяем, поместится ли блок в текущее сообщение
                if len(current_message + position_block) > MAX_MESSAGE_LENGTH:
                    # Если текущее сообщение не пустое, сохраняем его
                    if current_message:
                        messages.append(current_message)
                    current_message = position_block
                else:
                    current_message += position_block
            
            # Добавляем последнее сообщение, если оно не пустое
            if current_message:
                messages.append(current_message)
            
            # Создаем клавиатуру
            keyboard = [
                [InlineKeyboardButton(text="◀️ Назад", callback_data="parts_back")]
            ]
            
            # Отправляем сообщения
            message_ids = []  # Сохраняем ID всех отправленных сообщений
            first_message = True
            for idx, message_text in enumerate(messages):
                if first_message:
                    # Первое сообщение редактируем
                    edited_msg = await callback.message.edit_text(
                        text=message_text,
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard) if idx == len(messages) - 1 else None,
                        parse_mode="HTML",
                        link_preview_options={"is_disabled": False, "show_above_text": True, "force": True}
                    )
                    message_ids.append(edited_msg.message_id)
                    first_message = False
                else:
                    # Остальные отправляем как новые
                    new_msg = await callback.message.answer(
                        text=message_text,
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard) if idx == len(messages) - 1 else None,
                        parse_mode="HTML"
                    )
                    message_ids.append(new_msg.message_id)
            
            # Сохраняем ID сообщений в состоянии
            await state.update_data(
                current_spare_parts=items,
                spare_parts_messages=message_ids
            )
            
        except Exception as e:
            logger.error(f"Error showing spare parts list: {e}", exc_info=True)
            await callback.answer("Произошла ошибка при отображении списка запчастей")

    async def handle_find_analogs(self, callback: types.CallbackQuery, article: str):
        """Обработка поиск аналогов"""
        try:
            await callback.answer("Поиск аналогов в разработке")
        except Exception as e:
            logger.error(f"Error finding analogs: {e}", exc_info=True)
            await callback.answer("Произошла ошибка при поиске аналогов")

    async def handle_buy_part(self, callback: types.CallbackQuery, article: str):
        """Обработка покупки запчасти"""
        try:
            await callback.answer("Функция покупки в разработке")
        except Exception as e:
            logger.error(f"Error handling buy part: {e}", exc_info=True)
            await callback.answer("Поизошла ошибка при обработке покупки")

    async def show_parts_level(self, message: types.Message, state: FSMContext):
        """Показать текущий уровень дерева запчастей"""
        try:
            data = await state.get_data()
            parts_data = data.get('current_parts_data', [])
            current_path = data.get('current_path', [])
            selected_mod = data.get('selected_modification', {})
            
            # Получаем текущий уровень дерева
            current_level = parts_data
            for index in current_path:
                current_level = current_level[index].get('children', [])
            
            # Создаем клавиатуру
            keyboard = []
            
            # Добавляем кнопки ля каждого элемента текущего уровня
            for idx, item in enumerate(current_level):
                name = item['name']
                if len(name) > 30:
                    name = name[:27] + "..."
                    
                keyboard.append([InlineKeyboardButton(
                    text=f"📦 {name}",
                    callback_data=f"parts_select_{idx}"
                )])
            
            # Добавляем навигац��онные кнопки
            nav_row = []
            if current_path:
                nav_row.append(InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data="parts_back"
                ))
            else:
                nav_row.append(InlineKeyboardButton(
                    text="◀️ К модификациям",
                    callback_data="back_to_modifications"
                ))
            keyboard.append(nav_row)
            
            # Формируем текст со спецификацией, показывая толко доступные поля
            spec_parts = []
            
            # Проверяем каждое поле и добавляем только если но есть и не равно 'Н/Д'
            if selected_mod.get('grade') and selected_mod['grade'] != 'Н/Д':
                spec_parts.append(selected_mod['grade'])
            
            if selected_mod.get('transmission') and selected_mod['transmission'] != 'Н/Д':
                spec_parts.append(selected_mod['transmission'])
            
            if selected_mod.get('doors') and selected_mod['doors'] != 'Н/Д':
                spec_parts.append(f"({selected_mod['doors']})")
            
            if selected_mod.get('engine') and selected_mod['engine'] != 'Н/Д':
                spec_parts.append(f"Двгатеь: {selected_mod['engine']}")
            
            if selected_mod.get('power') and selected_mod['power'] != 'Н/Д':
                spec_parts.append(f"{selected_mod['power']} л.с.")
            
            if selected_mod.get('year') and selected_mod['year'] != 'Н/Д':
                spec_parts.append(f"{selected_mod['year']} г.")
            
            # Собираем спецификацию из доступных полей
            spec_text = "🚗 " + " ".join(spec_parts) if spec_parts else "🚗 Модификация"
            
            # Добавляем текущий путь, если он есть
            if current_path:
                path_level = parts_data
                path_names = []
                for index in current_path:
                    path_names.append(path_level[index]['name'])
                    path_level = path_level[index].get('children', [])
                spec_text += f"\n📍 {' → '.join(path_names)}"
            
            await message.edit_text(
                spec_text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
            
        except Exception as e:
            logger.error(f"Error showing parts level: {e}", exc_info=True)
            await message.edit_text(
                "Произошла ошибка пр�� отображении списка запчастей",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_modifications")
                ]])
            )

    async def handle_spare_part_selection(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка выбор конкретной запчасти"""
        try:
            part_idx = int(callback.data.split('_')[2])
            data = await state.get_data()
            spare_parts = data.get('current_spare_parts', [])
            
            if 0 <= part_idx < len(spare_parts):
                selected_part = spare_parts[part_idx]
                
                # Формируем информацию о группе запчастей
                info_text = f"📦 {selected_part.get('groupName', '')}\n\n"
                
                # Добавляем схему для сверки номеров
                if selected_part.get('schemaUrl'):
                    info_text += f"🖼 [Схема для сверки номерв]({selected_part['schemaUrl']})\n\n"
                
                # Группируем артикулы по позициям на схеме
                positions = {}
                for part in spare_parts:
                    code = part.get('codeOnImage', 'Без номера')
                    if code not in positions:
                        positions[code] = []
                    
                    article_info = {
                        'number': part.get('partNumber', 'Н/Д'),
                        'name': part.get('name', ''),
                        'manufacturer': part.get('manufacturer', 'Оригинал')
                    }
                    positions[code].append(article_info)
                
                # Добавляем информацию о артикулах по позициям
                for code, articles in sorted(positions.items()):
                    if code != 'Без номера':
                        info_text += f"📍 Позиция {code}:\n"
                    else:
                        info_text += f"📍 Дополнительные артикулы:\n"
                    
                    for article in articles:
                        info_text += f"• {article['name']} - {article['number']}"
                        if article['manufacturer'] != 'Оригинал':
                            info_text += f" ({article['manufacturer']})"
                        info_text += "\n"
                    info_text += "\n"
                
                keyboard = [
                    [InlineKeyboardButton(text="◀️ Назад к списку", callback_data="parts_back")]
                ]
                
                await callback.message.edit_text(
                    info_text,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
                    parse_mode="Markdown"
                )
            else:
                await callback.answer("Група запчастей не найдена")
                
        except Exception as e:
            logger.error(f"Error handling spare part selection: {e}", exc_info=True)
            await callback.answer("Произошла ошибка при отображении информации о запчастях")

    async def get_group_parts(self, brand_code: str, car_id: str, quick_group_id: str, car_ssd: str) -> Dict:
        """Получение списка запчастей для выбранной группы"""
        try:
            parser = AutodocCarParser()
            parts_data = await parser.get_group_parts(
                brand_code=brand_code,
                car_id=car_id,
                quick_group_id=quick_group_id,
                car_ssd=car_ssd
            )
            
            if not parts_data:
                logger.error("[ОТВЕТ] Пустой ответ от API запчастей")
                return {}
            
            return parts_data
            
        except Exception as e:
            logger.error(f"[ОШИБКА] Ошибка при получении зпчастей: {e}")
            return {}
