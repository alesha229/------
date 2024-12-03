import structlog
import logging
from pythonjsonlogger import jsonlogger
import sys
from datetime import datetime
from config import config

def setup_logging():
    """Настройка структурированного логирования"""
    
    # Настройка базового логгера
    logger = logging.getLogger()
    handler = logging.StreamHandler(sys.stdout)
    
    # Форматирование JSON логов
    formatter = jsonlogger.JsonFormatter(
        fmt='%(asctime)s %(name)s %(levelname)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    
    # Установка уровня логирования из конфигурации
    logger.setLevel(config.LOG_LEVEL)
    logger.addHandler(handler)
    
    # Настройка structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.render_to_log_kwargs,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    return structlog.get_logger()

# Инициализация логгера
logger = setup_logging()
