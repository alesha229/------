import asyncio
from prometheus_client import start_http_server
from utils.metrics import metrics
from bot import TelegramBot


async def main():
    # Запускаем сервер метрик
    start_http_server(8000)
    
    # Создаем и запускаем бота
    bot = TelegramBot()
    await bot.start()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped")