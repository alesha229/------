from aiogram import Router, types
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from models import User

router = Router()

@router.message(Command("referral"))
async def show_referral_info(message: types.Message, session: AsyncSession):
    """Показать реферальную информацию пользователя"""
    user = await session.execute(
        select(User).where(User.telegram_id == message.from_user.id)
    )
    user = user.scalar_one_or_none()
    
    if not user:
        return await message.answer("Пользователь не найден")
    
    # Получаем количество рефералов
    referrals_count = await session.execute(
        select(func.count()).where(User.referrer_id == user.id)
    )
    referrals_count = referrals_count.scalar()
    
    bot = await message.bot.get_me()
    referral_link = f"https://t.me/{bot.username}?start=ref{user.id}"
    
    text = (
        "📊 Ваша реферальная статистика:\n\n"
        f"🔗 Ваша реферальная ссылка:\n{referral_link}\n\n"
        f"👥 Количество рефералов: {referrals_count}\n\n"
        "За каждого приглашенного пользователя, который оформит подписку, "
        "вы получите дополнительные дни подписки!"
    )
    
    await message.answer(text)

async def process_referral(user: User, referrer_id: int, session: AsyncSession):
    """Обработка реферальной системы при регистрации"""
    if user.referrer_id or user.id == referrer_id:
        return
    
    referrer = await session.execute(
        select(User).where(User.id == referrer_id)
    )
    referrer = referrer.scalar_one_or_none()
    
    if referrer:
        user.referrer_id = referrer.id
        await session.commit()
