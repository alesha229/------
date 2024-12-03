from aiogram import types, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta
from utils.metrics import metrics
from utils.logger import logger
from config import config
from services.subscription_service import SubscriptionService

router = Router()

class AdminStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_subscription_days = State()
    waiting_broadcast_message = State()

@router.message(Command("admin"))
async def show_admin_menu(message: types.Message):
    """Показать админ-меню"""
    if message.from_user.id not in config.ADMIN_IDS:
        await message.reply("У вас нет доступа к админ-панели.")
        return
        
    text = (
        "🔑 Админ-панель\n\n"
        "Доступные команды:\n"
        "/admin_stats - Статистика пользователей\n"
        "/admin_add_subscription - Добавить подписку пользователю\n"
        "/admin_search_user - Поиск пользователя\n"
        "/admin_broadcast - Рассылка сообщений"
    )
    await message.answer(text)

@router.message(Command("admin_stats"))
async def admin_command(message: types.Message):
    """Обработка команды /admin"""
    if message.from_user.id not in config.ADMIN_IDS:
        await message.reply("У вас нет доступа к админ-панели.")
        return
        
    metrics.user_commands.labels(command="admin").inc()
    
    stats = await get_admin_stats()
    await message.reply(
        f"📊 Статистика:\n"
        f"Активных пользователей: {stats['active_users']}\n"
        f"Активных подписок: {stats['active_subscriptions']}\n"
        f"Выручка за сегодня: {stats['today_revenue']}₽\n"
        f"Всего запросов: {stats['total_requests']}"
    )

async def get_admin_stats():
    """Получение статистики для админ-панели"""
    try:
        # Получаем метрики из Prometheus
        active_users = metrics.active_users._value.get()
        active_subs = metrics.active_subscriptions._value.get()
        total_revenue = metrics.subscription_revenue._value.get()
        total_requests = sum(
            m.value for m in metrics.user_commands.collect()[0].samples
        )
        
        return {
            "active_users": int(active_users),
            "active_subscriptions": int(active_subs),
            "today_revenue": round(float(total_revenue), 2),
            "total_requests": int(total_requests)
        }
    except Exception as e:
        logger.error("admin_stats_error", error=str(e))
        return {
            "active_users": 0,
            "active_subscriptions": 0,
            "today_revenue": 0,
            "total_requests": 0
        }

@router.message(Command("admin_add_subscription"))
async def add_subscription_start(message: types.Message, state: FSMContext):
    """Начало процесса добавления подписки"""
    if message.from_user.id not in config.ADMIN_IDS:
        return
        
    await message.answer("Введите ID пользователя:")
    await state.set_state(AdminStates.waiting_for_user_id)

@router.message(AdminStates.waiting_for_user_id)
async def process_user_id(message: types.Message, state: FSMContext):
    """Обработка введенного ID пользователя"""
    try:
        user_id = int(message.text)
        await state.update_data(user_id=user_id)
        await message.answer("Введите количество дней подписки:")
        await state.set_state(AdminStates.waiting_for_subscription_days)
    except ValueError:
        await message.answer("Ошибка! Введите числовой ID пользователя")

@router.message(AdminStates.waiting_for_subscription_days)
async def process_subscription_days(message: types.Message, state: FSMContext, session: AsyncSession):
    """Обработка количества дней подписки"""
    try:
        days = int(message.text)
        data = await state.get_data()
        user_id = data['user_id']
        
        user = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = user.scalar_one_or_none()
        
        if not user:
            await message.answer("Пользователь не найден!")
            await state.clear()
            return
        
        if not user.subscription:
            subscription = Subscription(user_id=user.id)
            session.add(subscription)
        else:
            subscription = user.subscription
        
        now = datetime.utcnow()
        if subscription.end_date and subscription.end_date > now:
            subscription.end_date += timedelta(days=days)
        else:
            subscription.start_date = now
            subscription.end_date = now + timedelta(days=days)
        
        subscription.is_active = True
        await session.commit()
        
        await message.answer(f"Подписка успешно добавлена пользователю {user_id} на {days} дней")
    except ValueError:
        await message.answer("Ошибка! Введите числовое количество дней")
    finally:
        await state.clear()

@router.message(Command("admin_search_user"))
async def search_user(message: types.Message, session: AsyncSession):
    """Поиск пользователя по ID или юзернейму"""
    if message.from_user.id not in config.ADMIN_IDS:
        return
        
    search_query = message.text.replace("/admin_search_user", "").strip()
    if not search_query:
        await message.answer("Укажите ID или username пользователя")
        return
    
    try:
        user_id = int(search_query)
        query = select(User).where(User.telegram_id == user_id)
    except ValueError:
        query = select(User).where(User.username == search_query.lstrip("@"))
    
    user = await session.execute(query)
    user = user.scalar_one_or_none()
    
    if not user:
        await message.answer("Пользователь не найден")
        return
    
    subscription_status = "Нет подписки"
    if user.subscription and user.subscription.is_active:
        if user.subscription.end_date > datetime.utcnow():
            subscription_status = f"Активна до {user.subscription.end_date.strftime('%d.%m.%Y')}"
        else:
            subscription_status = "Истекла"
    
    text = (
        f"👤 Пользователь {user.username or 'без username'}\n"
        f"ID: {user.telegram_id}\n"
        f"Имя: {user.first_name} {user.last_name or ''}\n"
        f"Подписка: {subscription_status}\n"
        f"Дата регистрации: {user.created_at.strftime('%d.%m.%Y')}"
    )
    await message.answer(text)

@router.message(Command("admin_broadcast"))
async def broadcast_command(message: types.Message, state: FSMContext):
    """Отправка сообщения всем пользователям"""
    if message.from_user.id not in config.ADMIN_IDS:
        return
        
    await message.reply(
        "Отправьте сообщение для рассылки или /cancel для отмены"
    )
    await state.set_state(AdminStates.waiting_broadcast_message)

@router.message(AdminStates.waiting_broadcast_message)
async def process_broadcast_message(message: types.Message, state: FSMContext):
    """Обработка сообщения для рассылки"""
    if message.text == "/cancel":
        await state.finish()
        await message.reply("Рассылка отменена")
        return
        
    try:
        # Здесь будет логика рассылки
        metrics.user_commands.labels(command="broadcast").inc()
        await message.reply("Рассылка начата")
    except Exception as e:
        logger.error("broadcast_error", error=str(e))
        metrics.error_count.labels(type="broadcast").inc()
        await message.reply("Произошла ошибка при рассылке")
