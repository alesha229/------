from aiohttp import web
from sqlalchemy.ext.asyncio import AsyncSession
from database import async_session_maker
from handlers.subscription import handle_payment_notification

async def handle_robokassa_webhook(request):
    """Обработчик вебхука от Robokassa"""
    data = await request.post()
    
    async with async_session_maker() as session:
        session: AsyncSession
        result = await handle_payment_notification(dict(data), session)
        
        if result.get('status') == 'success':
            return web.Response(text="OK")
        else:
            return web.Response(text=result.get('error', 'Error'), status=400)

app = web.Application()
app.router.add_post('/robokassa/result', handle_robokassa_webhook)

if __name__ == '__main__':
    web.run_app(app, host='0.0.0.0', port=8080)
