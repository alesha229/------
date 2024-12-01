from dotenv import load_dotenv
import os

load_dotenv()

# Bot Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS = list(map(int, os.getenv('ADMIN_IDS', '').split(',')))

# Database Configuration
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'autoparts_bot')

DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Robokassa Configuration
ROBOKASSA_LOGIN = os.getenv('ROBOKASSA_LOGIN')
ROBOKASSA_PASSWORD1 = os.getenv('ROBOKASSA_PASSWORD1')
ROBOKASSA_TEST_MODE = os.getenv('ROBOKASSA_TEST_MODE', 'True').lower() == 'true'

# Monitoring Configuration
PROMETHEUS_PORT = int(os.getenv('PROMETHEUS_PORT', '8000'))
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

# Search Configuration
SEARCH_CACHE_TIME = int(os.getenv('SEARCH_CACHE_TIME', '3600'))  # 1 hour
MAX_SEARCH_RESULTS = int(os.getenv('MAX_SEARCH_RESULTS', '10'))

# Subscription Configuration
TRIAL_PERIOD_DAYS = 7
SUBSCRIPTION_PRICE = 299  # рублей в месяц
REFERRAL_BONUS_DAYS = 7  # дни бесплатной подписки за реферала

# Parser Configuration
PARSER_TIMEOUT = 30  # seconds
MAX_PARALLEL_REQUESTS = 10
