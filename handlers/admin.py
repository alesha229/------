from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta

from models import User, Subscription, Payment
from config import ADMIN_IDS

router = Router()

class AdminStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_subscription_days = State()

def admin_filter(message: types.Message):
    return message.from_user.id in ADMIN_IDS

@router.message(Command("admin"), admin_filter)
async def show_admin_menu(message: types.Message):
    """Показать админ-меню"""
    text = (
        "🔑 Админ-панель\n\n"
        "Доступные команды:\n"
        "/admin_stats - Статистика пользователей\n"
        "/admin_add_subscription - Добавить подписку пользователю\n"
        "/admin_search_user - Поиск пользователя\n"
        "/admin_broadcast - Рассылка сообщений"
    )
    await message.answer(text)

@router.message(Command("admin_stats"), admin_filter)
async def show_stats(message: types.Message, session: AsyncSession):
    """Показать статистику пользователей"""
    total_users = await session.execute(select(func.count()).select_from(User))
    total_users = total_users.scalar()
    
    active_subscriptions = await session.execute(
        select(func.count())
        .select_from(Subscription)
        .where(Subscription.is_active == True)
        .where(Subscription.end_date > datetime.utcnow())
    )
    active_subscriptions = active_subscriptions.scalar()
    
    today_payments = await session.execute(
        select(func.sum(Payment.amount))
        .where(Payment.created_at >= datetime.utcnow().date())
        .where(Payment.status == 'completed')
    )
    today_payments = today_payments.scalar() or 0
    
    text = (
        "📊 Статистика:\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"✅ Активных подписок: {active_subscriptions}\n"
        f"💰 Оплат за сегодня: {today_payments}₽"
    )
    await message.answer(text)

@router.message(Command("admin_add_subscription"), admin_filter)
async def add_subscription_start(message: types.Message, state: FSMContext):
    """Начало процесса добавления подписки"""
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

@router.message(Command("admin_search_user"), admin_filter)
async def search_user(message: types.Message, session: AsyncSession):
    """Поиск пользователя по ID или юзернейму"""
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
