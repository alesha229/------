from abc import ABC, abstractmethod
from typing import Any, Optional, Dict, Callable
from utils.logger import logger
from utils.metrics import metrics
from sqlalchemy.ext.asyncio import AsyncSession
import functools
import time

class BaseService(ABC):
    """Базовый класс для всех сервисов"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.logger = logger.bind(service=self.__class__.__name__)
    
    @staticmethod
    def measure_execution_time(operation_name: str) -> Callable:
        """Декоратор для измерения времени выполнения операций"""
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            async def wrapper(*args, **kwargs) -> Any:
                start_time = time.time()
                try:
                    result = await func(*args, **kwargs)
                    execution_time = time.time() - start_time
                    metrics.operation_duration.labels(
                        operation=operation_name,
                        status="success"
                    ).observe(execution_time)
                    return result
                except Exception as e:
                    execution_time = time.time() - start_time
                    metrics.operation_duration.labels(
                        operation=operation_name,
                        status="error"
                    ).observe(execution_time)
                    metrics.error_count.labels(
                        type=operation_name
                    ).inc()
                    logger.error(
                        f"{operation_name}_error",
                        error=str(e),
                        execution_time=execution_time
                    )
                    raise
            return wrapper
        return decorator
    
    @staticmethod
    def log_errors(operation_name: str) -> Callable:
        """Декоратор для логирования ошибок"""
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            async def wrapper(*args, **kwargs) -> Any:
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    logger.error(
                        f"{operation_name}_error",
                        error=str(e),
                        args=str(args),
                        kwargs=str(kwargs)
                    )
                    raise
            return wrapper
        return decorator
    
    async def log_operation(self, operation: str, details: Optional[Dict[str, Any]] = None):
        """Логирование операций с дополнительными деталями"""
        log_data = {"operation": operation}
        if details:
            log_data.update(details)
        self.logger.info("operation_executed", **log_data)
    
    @abstractmethod
    async def validate(self, *args, **kwargs):
        """Абстрактный метод валидации входных данных"""
        pass
