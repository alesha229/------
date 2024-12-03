from handlers.base_handler import BaseHandler
from services.search_service import SearchService
from utils.metrics import metrics
from utils.logger import logger
from aiogram import types
from typing import List, Dict, Any

class SearchHandler(BaseHandler):
    def __init__(self, db_session):
        super().__init__(db_session)
        self.search_service = SearchService(db_session)
        self.logger = logger.bind(handler="SearchHandler")
    
    async def handle(self, message: types.Message):
        """Обработка поискового запроса"""
        user_id = message.from_user.id
        query = message.text
        
        metrics.user_commands.labels(command="search").inc()
        
        try:
            with self.measure_time("search_handler"):
                # Валидация пользователя
                if not await self.validate_user(user_id):
                    await message.reply("У вас нет доступа к поиску. Пожалуйста, оформите подписку.")
                    return
                
                # Поиск запчастей
                results = await self.search_service.search_parts(user_id, query)
                
                if not results:
                    await message.reply("По вашему запросу ничего не найдено.")
                    return
                
                # Форматирование и отправка результатов
                response = self._format_results(results)
                await message.reply(response, parse_mode="HTML")
                
        except Exception as e:
            await self.handle_error(e, {"user_id": user_id, "query": query})
            await message.reply("Произошла ошибка при поиске. Попробуйте позже.")
    
    async def show_history(self, message: types.Message):
        """Показать историю поиска пользователя"""
        user_id = message.from_user.id
        
        metrics.user_commands.labels(command="search_history").inc()
        
        try:
            with self.measure_time("search_history"):
                history = await self.search_service.get_search_history(user_id)
                
                if not history:
                    await message.reply("История поиска пуста.")
                    return
                
                response = self._format_history(history)
                await message.reply(response, parse_mode="HTML")
                
        except Exception as e:
            await self.handle_error(e, {"user_id": user_id})
            await message.reply("Не удалось получить историю поиска.")
    
    def _format_results(self, results: List[Dict[str, Any]]) -> str:
        """Форматирование результатов поиска"""
        formatted = ["<b>Результаты поиска:</b>\n"]
        
        for result in results:
            formatted.append(
                f"🔍 <b>{result['name']}</b>\n"
                f"Артикул: {result['number']}\n"
                f"Цена: {result['price']} руб.\n"
                f"Источник: {result['source']}\n"
                f"<a href='{result['url']}'>Подробнее</a>\n"
            )
        
        return "\n".join(formatted)
    
    def _format_history(self, history: List[Dict[str, Any]]) -> str:
        """Форматирование истории поиска"""
        formatted = ["<b>История поиска:</b>\n"]
        
        for item in history:
            formatted.append(
                f"🕒 {item['timestamp']}\n"
                f"Запрос: {item['query']}\n"
                f"Найдено результатов: {item['results_count']}\n"
            )
        
        return "\n".join(formatted)
