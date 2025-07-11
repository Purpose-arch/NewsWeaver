# main.py
import asyncio
import signal
import sys
import os # Import os to get environment variables
import aiohttp # Import aiohttp for client requests
from aiohttp import web # Import aiohttp for the web server
from src.core.logger import logger
import src.core.clients as clients
import src.integrations.parser as parser
import src.features.moderation as moderation
import src.integrations.requesty as requesty
import src.features.publisher as publisher
import src.features.direct_news as direct_news
import src.features.alarm as alarm  # Импортируем модуль alarm
from src.core.clients import start_clients, close_clients, loop
import src.utils.langdock_key_gen as langdock_key_gen # Импортируем генератор ключей Langdock

async def on_shutdown():
    """
    Корректное завершение работы
    """
    logger.info("Завершение работы сервиса...")
    await close_clients()
    logger.info("Сервис остановлен")

async def health_check_handler(request):
    """
    HTTP handler for health checks, returns OK.
    """
    return web.Response(text="OK")

async def send_keep_alive_request():
    """
    Sends a periodic HTTP GET request to the WEB_APP_URL to keep the container alive.
    """
    web_app_url = os.getenv("WEB_APP_URL")
    if not web_app_url:
        logger.warning("Переменная окружения WEB_APP_URL не установлена. Пропускаю keep-alive запрос.")
        return

    logger.info("Ожидание 30 секунд перед первым keep-alive запросом...")
    await asyncio.sleep(30) # Добавляем задержку перед первым запросом

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(web_app_url) as response:
                    logger.info(f"Keep-alive запрос к {web_app_url} завершен со статусом: {response.status}")
            except aiohttp.ClientError as e:
                logger.error(f"Ошибка при отправке keep-alive запроса к {web_app_url}: {e}")
            await asyncio.sleep(600)  # Отправлять запрос каждые 10 минут (600 секунд)

async def start_web_server():
    """
    Starts a minimal aiohttp web server for health checks.
    """
    app = web.Application()
    app.router.add_get('/', health_check_handler)
    # Get port from environment variable, default to 8080 for local development
    port = int(os.getenv("PORT", 8080))
    logger.info(f"Запуск веб-сервера на порту {port}...")
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info("Веб-сервер запущен.")

async def main():
    """
    Основная точка входа в приложение
    """
    try:
        logger.info("Запуск сервиса...")
        
        # Запускаем веб-сервер первым
        asyncio.create_task(start_web_server())
        
        # Убеждаемся, что 5 ключей Langdock API сгенерированы до запуска основных компонентов
        await langdock_key_gen.ensure_initial_keys_generated()
        
        # Запускаем все клиенты
        await start_clients()
        
        # Регистрируем обработчики модерации
        await moderation.register_handlers()
        
        # Запускаем парсер сообщений из Telegram
        await parser.start_parser()
        
        # Запускаем парсер тревог
        await alarm.start_alarm_bot()
        
        # Запускаем генератор ключей Langdock в фоновом режиме для поддержания их количества
        asyncio.create_task(langdock_key_gen.main_langdock_generator())


        # Запускаем задачу для отправки периодических keep-alive запросов
        asyncio.create_task(send_keep_alive_request())
        
        # DEPRECATED: asyncio.create_task(db.schedule_cleanup(1))  # Удалено автоудаление новостей
        
        logger.info("Сервис успешно запущен")
        
        # Бесконечный цикл, чтобы программа не завершалась
        while True:
            await asyncio.sleep(3600)  # Проверка каждый час
            
    except KeyboardInterrupt:
        logger.info("Получен сигнал прерывания")
    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске: {e}", exc_info=True)
    finally:
        await on_shutdown()

if __name__ == "__main__":
    # Обработка сигналов для корректного завершения
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(on_shutdown()))
    
    try:
        # Запускаем основной цикл
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Программа прервана пользователем")
    except Exception as e:
        logger.critical(f"Необработанная ошибка: {e}", exc_info=True)
    finally:
        # Закрываем цикл событий
        loop.close()
        sys.exit(0)
