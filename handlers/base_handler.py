from abc import ABC, abstractmethod
from typing import Any, Dict
from utils.metrics import metrics
import time
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class BaseHandler(ABC):
    def __init__(self, db_session):
        self.db_session = db_session
    
    @contextmanager
    def measure_time(self, metric_name: str):
        """Контекстный менеджер для измерения времени выполнения"""
        start_time = time.time()
        try:
            yield
        finally:
            duration = time.time() - start_time
            metrics.request_latency.labels(endpoint=metric_name).observe(duration)
    
    async def handle_error(self, error: Exception, context: Dict[str, Any] = None):
        """Обработка ошибок с логированием и метриками"""
        error_type = type(error).__name__
        metrics.error_count.labels(type=error_type).inc()
        
        error_msg = f"Error: {error_type} - {str(error)}"
        if context:
            error_msg += f"\nContext: {context}"
        
        logger.error(error_msg, exc_info=True)
        
    @abstractmethod
    async def handle(self, *args, **kwargs):
        """Абстрактный метод для обработки запроса"""
        pass
    
    async def validate_user(self, user_id: int) -> bool:
        """Проверка пользователя и его подписки"""
        try:
            user = await self.db_session.query(User).filter(User.telegram_id == user_id).first()
            if not user:
                return False
            
            if user.subscription and user.subscription.is_active:
                metrics.active_subscriptions.inc()
                return True
                
            return False
        except Exception as e:
            await self.handle_error(e, {"user_id": user_id})
            return False
