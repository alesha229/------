from services.base_service import BaseService
from models import User, Subscription, Payment
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from sqlalchemy import select
from utils.metrics import metrics
from decimal import Decimal

class SubscriptionService(BaseService):
    SUBSCRIPTION_PERIODS = {
        'month': 30,
        'year': 365
    }
    
    SUBSCRIPTION_PRICES = {
        'month': Decimal('299.00'),
        'year': Decimal('2990.00')
    }
    
    @BaseService.measure_execution_time("subscription.create")
    @BaseService.log_errors("subscription.create")
    async def create_subscription(
        self,
        user_id: int,
        period: str,
        is_trial: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Создание подписки для пользователя"""
        if period not in self.SUBSCRIPTION_PERIODS:
            raise ValueError(f"Invalid subscription period: {period}")
            
        async with self.session.begin():
            user = await self._get_user(user_id)
            if not user:
                return None
                
            # Проверяем существующую подписку
            if await self._has_active_subscription(user.id):
                return None
                
            days = self.SUBSCRIPTION_PERIODS[period]
            start_date = datetime.utcnow()
            end_date = start_date + timedelta(days=days)
            
            subscription = Subscription(
                user_id=user.id,
                is_active=True,
                start_date=start_date,
                end_date=end_date,
                period=period,
                is_trial=is_trial
            )
            
            self.session.add(subscription)
            metrics.active_subscriptions.inc()
            
            await self.log_operation(
                "subscription_created",
                {
                    "user_id": user_id,
                    "period": period,
                    "is_trial": is_trial
                }
            )
            
            return {
                "id": subscription.id,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "period": period,
                "price": float(self.SUBSCRIPTION_PRICES[period])
            }
    
    @BaseService.measure_execution_time("subscription.payment")
    @BaseService.log_errors("subscription.payment")
    async def process_payment(
        self,
        subscription_id: int,
        amount: Decimal,
        transaction_id: str
    ) -> bool:
        """Обработка платежа за подписку"""
        async with self.session.begin():
            subscription = await self._get_subscription(subscription_id)
            if not subscription:
                return False
                
            payment = Payment(
                subscription_id=subscription_id,
                amount=amount,
                transaction_id=transaction_id,
                status='completed'
            )
            
            self.session.add(payment)
            metrics.subscription_revenue.inc()
            
            await self.log_operation(
                "payment_processed",
                {
                    "subscription_id": subscription_id,
                    "amount": float(amount),
                    "transaction_id": transaction_id
                }
            )
            
            return True
    
    @BaseService.measure_execution_time("subscription.validate")
    async def validate(self, user_id: int) -> bool:
        """Проверка возможности создания подписки"""
        user = await self._get_user(user_id)
        if not user:
            return False
            
        if await self._has_active_subscription(user.id):
            return False
            
        return True
    
    async def _get_user(self, user_id: int) -> Optional[User]:
        """Получение пользователя по ID"""
        query = select(User).where(User.telegram_id == user_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
    
    async def _get_subscription(self, subscription_id: int) -> Optional[Subscription]:
        """Получение подписки по ID"""
        query = select(Subscription).where(Subscription.id == subscription_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
    
    async def _has_active_subscription(self, user_id: int) -> bool:
        """Проверка наличия активной подписки"""
        query = select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.is_active == True,
            Subscription.end_date > datetime.utcnow()
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none() is not None
