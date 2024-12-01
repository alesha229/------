from aiogram import Router, types
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from models import User, Subscription, Payment
from services.robokassa import RobokassaPayment
from keyboards.subscription import get_subscription_keyboard

router = Router()
robokassa = RobokassaPayment()

SUBSCRIPTION_PRICES = {
    "month": 299.0,
    "year": 2990.0
}

@router.message(lambda m: m.text == "💎 Подписка")
async def show_subscription_info(message: types.Message, session: AsyncSession):
    """Показать информацию о подписке"""
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
        await session.refresh(user)
    
    if not user.subscription:
        keyboard = get_subscription_keyboard()
        return await message.answer(
            "У вас нет активной подписки.\n\n"
            "Выберите тариф для оформления подписки:",
            reply_markup=keyboard
        )
    
    if user.subscription.is_active:
        expires_at = user.subscription.start_date + timedelta(days=30 if user.subscription.period == 'month' else 365)
        days_left = (expires_at - datetime.utcnow()).days
        
        return await message.answer(
            f"У вас активная подписка.\n"
            f"Осталось дней: {days_left}\n\n"
            f"Для продления подписки выберите тариф:",
            reply_markup=get_subscription_keyboard()
        )
    else:
        keyboard = get_subscription_keyboard()
        return await message.answer(
            "У вас нет активной подписки.\n\n"
            "Выберите тариф для оформления подписки:",
            reply_markup=keyboard
        )

@router.callback_query(lambda c: c.data.startswith('subscribe_'))
async def process_subscription_payment(callback: types.CallbackQuery, session: AsyncSession):
    """Обработка выбора периода подписки"""
    period = callback.data.split('_')[1]
    
    if period not in SUBSCRIPTION_PRICES:
        return await callback.answer("Неверный период подписки")
    
    # Получаем или создаем пользователя
    result = await session.execute(
        select(User)
        .options(selectinload(User.subscription))
        .where(User.telegram_id == callback.from_user.id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        user = User(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    
    amount = SUBSCRIPTION_PRICES[period]
    description = period
    
    # Создаем запись о платеже
    payment = Payment(
        amount=amount,
        status='pending',
        subscription_id=user.subscription.id if user.subscription else None
    )
    session.add(payment)
    await session.commit()
    
    # Генерируем ссылку для оплаты
    payment_link = robokassa.generate_payment_link(
        amount=amount,
        description=description,
        user_id=user.id
    )
    
    await callback.message.answer(
        f"Для оплаты подписки перейдите по ссылке:\n{payment_link}\n\n"
        f"После оплаты ваша подписка будет автоматически активирована."
    )
    await callback.answer()

async def handle_payment_notification(data: dict, session: AsyncSession):
    """Обработка уведомления об оплате от Robokassa"""
    try:
        # Проверяем подпись
        amount = float(data.get('OutSum', 0))
        invoice_id = data.get('InvId', '')
        signature = data.get('SignatureValue', '')
        
        if not robokassa.verify_payment(amount, invoice_id, signature):
            return {'error': 'Invalid signature'}
        
        # Получаем ID пользователя из invoice_id
        user_id = int(invoice_id.split('_')[0])
        
        # Находим пользователя
        result = await session.execute(
            select(User)
            .options(selectinload(User.subscription))
            .where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            return {'error': 'User not found'}
        
        # Определяем период подписки по сумме
        period = 'month' if amount == SUBSCRIPTION_PRICES['month'] else 'year'
        
        # Создаем или обновляем подписку
        if not user.subscription:
            subscription = Subscription(
                user_id=user.id,
                is_active=True,
                start_date=datetime.utcnow(),
                period=period
            )
            session.add(subscription)
        else:
            user.subscription.is_active = True
            user.subscription.start_date = datetime.utcnow()
            user.subscription.period = period
        
        # Обновляем статус платежа
        payment = Payment(
            subscription_id=user.subscription.id,
            amount=amount,
            transaction_id=invoice_id,
            status='completed'
        )
        session.add(payment)
        
        await session.commit()
        return {'status': 'success'}
        
    except Exception as e:
        return {'error': str(e)}
