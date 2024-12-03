import os
from typing import List
from dataclasses import dataclass, field
import logging
from dotenv import load_dotenv

# Загружаем переменные окружения из файла .env
load_dotenv()

@dataclass
class Config:
    # Основные настройки бота
    BOT_TOKEN: str = ""
    ADMIN_IDS: List[int] = field(default_factory=lambda: [])
    
    # Настройки базы данных
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "bot_db"
    DB_USER: str = "postgres"
    DB_PASS: str = ""
    
    # Настройки логирования
    LOG_LEVEL: str = "INFO"
    
    # Настройки мониторинга
    PROMETHEUS_PORT: int = 8000
    
    # Настройки поиска
    SEARCH_TIMEOUT: int = 30
    MAX_SEARCH_RESULTS: int = 10
    
    # Настройки подписки
    TRIAL_PERIOD_DAYS: int = 1
    SUBSCRIPTION_PRICE: float = 100.0
    
    # Настройки Robokassa
    ROBOKASSA_LOGIN: str = ""
    ROBOKASSA_PASS1: str = ""
    ROBOKASSA_PASS2: str = ""
    ROBOKASSA_TEST_MODE: bool = True
    
    def __post_init__(self):
        """Загрузка значений из переменных окружения после инициализации"""
        self.BOT_TOKEN = os.getenv("BOT_TOKEN", self.BOT_TOKEN)
        admin_ids = os.getenv("ADMIN_IDS", "")
        self.ADMIN_IDS = [int(id) for id in admin_ids.split(",") if id]
        
        self.DB_HOST = os.getenv("DB_HOST", self.DB_HOST)
        self.DB_PORT = int(os.getenv("DB_PORT", str(self.DB_PORT)))
        self.DB_NAME = os.getenv("DB_NAME", self.DB_NAME)
        self.DB_USER = os.getenv("DB_USER", self.DB_USER)
        self.DB_PASS = os.getenv("DB_PASS", self.DB_PASS)
        
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", self.LOG_LEVEL)
        self.PROMETHEUS_PORT = int(os.getenv("PROMETHEUS_PORT", str(self.PROMETHEUS_PORT)))
        
        self.SEARCH_TIMEOUT = int(os.getenv("SEARCH_TIMEOUT", str(self.SEARCH_TIMEOUT)))
        self.MAX_SEARCH_RESULTS = int(os.getenv("MAX_SEARCH_RESULTS", str(self.MAX_SEARCH_RESULTS)))
        
        self.TRIAL_PERIOD_DAYS = int(os.getenv("TRIAL_PERIOD_DAYS", str(self.TRIAL_PERIOD_DAYS)))
        self.SUBSCRIPTION_PRICE = float(os.getenv("SUBSCRIPTION_PRICE", str(self.SUBSCRIPTION_PRICE)))
        
        self.ROBOKASSA_LOGIN = os.getenv("ROBOKASSA_LOGIN", self.ROBOKASSA_LOGIN)
        self.ROBOKASSA_PASS1 = os.getenv("ROBOKASSA_PASS1", self.ROBOKASSA_PASS1)
        self.ROBOKASSA_PASS2 = os.getenv("ROBOKASSA_PASS2", self.ROBOKASSA_PASS2)
        
        # Исправляем обработку булевого значения
        robokassa_test = os.getenv("ROBOKASSA_TEST_MODE", "1")
        self.ROBOKASSA_TEST_MODE = robokassa_test.lower() in ('true', '1', 't', 'y', 'yes')
        
        self.validate()
    
    def validate(self) -> None:
        """Проверка корректности конфигурации"""
        missing_vars = []
        
        if not self.BOT_TOKEN:
            missing_vars.append("BOT_TOKEN")
            
        if not self.ADMIN_IDS:
            missing_vars.append("ADMIN_IDS")
            
        if not self.DB_PASS:
            missing_vars.append("DB_PASS")
        
        if missing_vars:
            raise ValueError(
                "Отсутствуют обязательные переменные окружения: " + 
                ", ".join(missing_vars) + 
                "\nСоздайте файл .env на основе .env.example"
            )
            
        if self.TRIAL_PERIOD_DAYS < 1:
            raise ValueError("TRIAL_PERIOD_DAYS должен быть больше 0")
            
        if self.SUBSCRIPTION_PRICE <= 0:
            raise ValueError("SUBSCRIPTION_PRICE должен быть больше 0")
            
        # Проверка настроек Robokassa в боевом режиме
        if not self.ROBOKASSA_TEST_MODE:
            missing_robokassa = []
            if not self.ROBOKASSA_LOGIN:
                missing_robokassa.append("ROBOKASSA_LOGIN")
            if not self.ROBOKASSA_PASS1:
                missing_robokassa.append("ROBOKASSA_PASS1")
            if not self.ROBOKASSA_PASS2:
                missing_robokassa.append("ROBOKASSA_PASS2")
                
            if missing_robokassa:
                raise ValueError(
                    "Для работы с Robokassa в боевом режиме необходимо установить: " +
                    ", ".join(missing_robokassa)
                )
    
    @property
    def DATABASE_URL(self) -> str:
        """Получение URL для подключения к базе данных"""
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASS}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

# Создание экземпляра конфигурации
config = Config()
