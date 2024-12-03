from handlers.base_handler import BaseHandler
from services.subscription_service import SubscriptionService
from utils.metrics import metrics
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from decimal import Decimal

class SubscriptionHandler(BaseHandler):
    def __init__(self, db_session):
        super().__init__(db_session)
        self.subscription_service = SubscriptionService(db_session)
    
    async def handle_subscription_command(self, message: types.Message):
        """Обработка команды подписки"""
        metrics.user_commands.labels(command="subscription").inc()
        
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("Месяц - 299₽", callback_data="sub_month"),
            InlineKeyboardButton("Год - 2990₽", callback_data="sub_year")
        )
        
        await message.reply(
            "Выберите период подписки:",
            reply_markup=keyboard
        )
    
    async def handle_subscription_callback(self, callback_query: types.CallbackQuery):
        """Обработка выбора периода подписки"""
        user_id = callback_query.from_user.id
        period = callback_query.data.split('_')[1]
        
        try:
            with self.measure_time("subscription_creation"):
                subscription = await self.subscription_service.create_subscription(
                    user_id=user_id,
                    period=period
                )
                
                if not subscription:
                    await callback_query.message.edit_text(
                        "У вас уже есть активная подписка."
                    )
                    return
                
                # Создаем платежную ссылку (заглушка)
                payment_url = f"https://payment.example.com/{subscription['id']}"
                
                keyboard = InlineKeyboardMarkup()
                keyboard.add(
                    InlineKeyboardButton(
                        "Оплатить",
                        url=payment_url
                    )
                )
                
                await callback_query.message.edit_text(
                    f"Подписка на {period}:\n"
                    f"Стоимость: {subscription['price']}₽\n"
                    f"Действует до: {subscription['end_date']}\n\n"
                    "Для активации нажмите кнопку оплаты:",
                    reply_markup=keyboard
                )
                
        except Exception as e:
            await self.handle_error(e, {"user_id": user_id, "period": period})
            await callback_query.message.edit_text(
                "Произошла ошибка при создании подписки. Попробуйте позже."
            )
    
    async def handle_payment_notification(self, data: dict):
        """Обработка уведомления об оплате"""
        try:
            with self.measure_time("payment_processing"):
                success = await self.subscription_service.process_payment(
                    subscription_id=int(data['subscription_id']),
                    amount=Decimal(data['amount']),
                    transaction_id=data['transaction_id']
                )
                
                if success:
                    # Отправляем уведомление пользователю
                    user_id = data.get('user_id')
                    if user_id:
                        # Здесь должна быть отправка сообщения через бота
                        pass
                    
                return success
                
        except Exception as e:
            await self.handle_error(e, {"payment_data": data})
            return False
