import logging
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import time
from functools import wraps
from typing import Callable
import traceback
import asyncio
from aiohttp import web

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Метрики Prometheus
REQUESTS_TOTAL = Counter(
    'bot_requests_total',
    'Total number of requests',
    ['command']
)

ERRORS_TOTAL = Counter(
    'bot_errors_total',
    'Total number of errors',
    ['type']
)

RESPONSE_TIME = Histogram(
    'bot_response_time_seconds',
    'Response time in seconds',
    ['command']
)

async def metrics_handler(request):
    """Обработчик для отдачи метрик Prometheus"""
    resp = web.Response(body=generate_latest())
    resp.content_type = CONTENT_TYPE_LATEST
    return resp

async def start_monitoring(port: int = 8000):
    """Запуск сервера метрик Prometheus"""
    app = web.Application()
    app.router.add_get('/metrics', metrics_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    logger.info(f"Prometheus metrics server started on port {port}")

def log_command(f: Callable):
    """Декоратор для логирования команд и сбора метрик"""
    @wraps(f)
    async def wrapper(*args, **kwargs):
        command_name = f.__name__
        start_time = time.time()
        
        try:
            result = await f(*args, **kwargs)
            REQUESTS_TOTAL.labels(command=command_name).inc()
            RESPONSE_TIME.labels(command=command_name).observe(time.time() - start_time)
            return result
        except Exception as e:
            ERRORS_TOTAL.labels(type=type(e).__name__).inc()
            logger.error(f"Error in {command_name}: {str(e)}\n{traceback.format_exc()}")
            raise
    
    return wrapper

class ErrorLogger:
    """Класс для логирования ошибок парсеров"""
    
    @staticmethod
    def log_parser_error(parser_name: str, error: Exception, part_number: str = None):
        """Логирование ошибок парсера"""
        ERRORS_TOTAL.labels(type=f"parser_{parser_name}").inc()
        error_msg = f"Parser {parser_name} error"
        if part_number:
            error_msg += f" for part {part_number}"
        error_msg += f": {str(error)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
    
    @staticmethod
    def log_payment_error(user_id: int, error: Exception):
        """Логирование ошибок платежей"""
        ERRORS_TOTAL.labels(type="payment").inc()
        error_msg = f"Payment error for user {user_id}: {str(error)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
