from services.base_service import BaseService
from models import SearchHistory, SearchResult, User
from typing import List, Dict, Any
from datetime import datetime
from sqlalchemy import select
from utils.metrics import metrics

class SearchService(BaseService):
    @BaseService.measure_execution_time("search_parts")
    async def search_parts(self, user_id: int, query: str) -> List[Dict[str, Any]]:
        """Поиск запчастей с метриками и логированием"""
        await self.log_operation(
            "search_started",
            {"user_id": user_id, "query": query}
        )
        
        try:
            # Валидация пользователя
            if not await self.validate(user_id):
                self.logger.warning("invalid_user", user_id=user_id)
                return []
            
            # Создание записи в истории поиска
            search_history = SearchHistory(
                user_id=user_id,
                query=query,
                timestamp=datetime.utcnow()
            )
            self.session.add(search_history)
            await self.session.flush()
            
            # Здесь будет логика поиска по разным источникам
            results = []  # Заглушка для демонстрации
            
            # Сохранение результатов
            for result in results:
                search_result = SearchResult(
                    search_id=search_history.id,
                    source=result["source"],
                    part_name=result["name"],
                    part_number=result["number"],
                    price=result["price"],
                    url=result["url"]
                )
                self.session.add(search_result)
                metrics.search_results.labels(source=result["source"]).inc()
            
            await self.session.commit()
            
            await self.log_operation(
                "search_completed",
                {
                    "user_id": user_id,
                    "query": query,
                    "results_count": len(results)
                }
            )
            
            return results
            
        except Exception as e:
            await self.session.rollback()
            self.logger.error(
                "search_failed",
                error=str(e),
                user_id=user_id,
                query=query
            )
            raise
    
    async def validate(self, user_id: int) -> bool:
        """Проверка пользователя и его прав"""
        query = select(User).where(User.telegram_id == user_id)
        result = await self.session.execute(query)
        user = result.scalar_one_or_none()
        
        if not user:
            return False
            
        if not user.is_active:
            metrics.error_count.labels(type="inactive_user").inc()
            return False
            
        return True
    
    @BaseService.measure_execution_time("get_search_history")
    async def get_search_history(self, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Получение истории поиска пользователя"""
        query = (
            select(SearchHistory)
            .where(SearchHistory.user_id == user_id)
            .order_by(SearchHistory.timestamp.desc())
            .limit(limit)
        )
        
        result = await self.session.execute(query)
        history = result.scalars().all()
        
        return [
            {
                "query": item.query,
                "timestamp": item.timestamp.isoformat(),
                "results_count": len(item.results)
            }
            for item in history
        ]
