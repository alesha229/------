from prometheus_client import Counter, Histogram, Gauge
from typing import Dict

class Metrics:
    def __init__(self):
        # Метрики пользователей
        self.active_users = Gauge('bot_active_users_total', 'Total number of active users')
        self.user_commands = Counter('bot_user_commands_total', 'Total commands by users', ['command'])
        
        # Метрики поиска
        self.search_duration = Histogram(
            'bot_search_duration_seconds',
            'Search duration in seconds',
            buckets=(0.1, 0.5, 1.0, 2.0, 5.0)
        )
        self.search_results = Counter(
            'bot_search_results_total',
            'Number of search results',
            ['source']
        )
        
        # Метрики базы данных
        self.db_size = Gauge('bot_database_size_bytes', 'Database size in bytes')
        self.db_connections = Gauge('bot_database_connections', 'Number of active database connections')
        self.db_query_duration = Histogram(
            'bot_db_query_duration_seconds',
            'Database query duration in seconds',
            buckets=(0.01, 0.05, 0.1, 0.5, 1.0)
        )
        
        # Метрики подписок
        self.active_subscriptions = Gauge('bot_active_subscriptions', 'Number of active subscriptions')
        self.subscription_revenue = Counter('bot_subscription_revenue_total', 'Total subscription revenue')
        self.trial_subscriptions = Counter('bot_trial_subscriptions_total', 'Number of trial subscriptions')
        
        # Метрики производительности
        self.request_latency = Histogram(
            'bot_request_latency_seconds',
            'Request latency in seconds',
            ['endpoint'],
            buckets=(0.1, 0.5, 1.0, 2.0, 5.0)
        )
        self.error_count = Counter('bot_errors_total', 'Number of errors', ['type'])
        
        # Метрики парсинга
        self.parser_duration = Histogram(
            'bot_parser_duration_seconds',
            'Parser execution duration in seconds',
            ['parser'],
            buckets=(1.0, 5.0, 10.0, 30.0, 60.0)
        )
        self.parser_errors = Counter('bot_parser_errors_total', 'Number of parser errors', ['parser'])

    async def update_db_metrics(self, db_session):
        """Обновление метрик базы данных"""
        # Получение размера БД
        result = await db_session.execute("SELECT pg_database_size(current_database())")
        size = await result.scalar()
        self.db_size.set(size)
        
        # Получение активных подключений
        result = await db_session.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE state = 'active'"
        )
        connections = await result.scalar()
        self.db_connections.set(connections)

metrics = Metrics()
