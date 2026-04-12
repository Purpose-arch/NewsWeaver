# main.py
import asyncio
import signal
import sys
import os  # Import os to get environment variables
import aiohttp  # Import aiohttp for client requests
from aiohttp import web  # Import aiohttp for the web server
from src.core.logger import logger
import src.core.clients as clients
import src.integrations.parser as parser
import src.features.moderation as moderation
import src.integrations.requesty as requesty
import src.features.publisher as publisher
import src.features.direct_news as direct_news
import src.features.alarm as alarm
from src.core.clients import start_clients, close_clients, loop


async def on_shutdown():
    """
    Gracefully shuts down the service.
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
        logger.warning(
            "Переменная окружения WEB_APP_URL не установлена. Пропускаю keep-alive запрос."
        )
        return

    logger.info("Ожидание 30 секунд перед первым keep-alive запросом...")
    await asyncio.sleep(30)

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(web_app_url) as response:
                    logger.info(
                        f"Keep-alive запрос к {web_app_url} завершен со статусом: {response.status}"
                    )
            except aiohttp.ClientError as e:
                logger.error(
                    f"Ошибка при отправке keep-alive запроса к {web_app_url}: {e}"
                )
            await asyncio.sleep(600)


async def start_web_server():
    """
    Starts a minimal aiohttp web server for health checks.
    """
    app = web.Application()
    app.router.add_get("/", health_check_handler)
    # Get port from environment variable, default to 8080 for local development
    port = int(os.getenv("PORT", 8080))
    logger.info(f"Запуск веб-сервера на порту {port}...")
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Веб-сервер запущен.")


async def main():
    """
    Main entry point for the application.
    Initializes clients, registers handlers, and starts background tasks.
    """
    try:
        logger.info("Запуск сервиса...")

        asyncio.create_task(start_web_server())

        await start_clients()

        await moderation.register_handlers()

        await parser.start_parser()

        await alarm.start_alarm_bot()

        asyncio.create_task(send_keep_alive_request())

        logger.info("Сервис успешно запущен")

        # Keep the main loop running
        while True:
            await asyncio.sleep(3600)

    except KeyboardInterrupt:
        logger.info("Получен сигнал прерывания")
    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске: {e}", exc_info=True)
    finally:
        await on_shutdown()


if __name__ == "__main__":
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(on_shutdown()))

    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Программа прервана пользователем")
    except Exception as e:
        logger.critical(f"Необработанная ошибка: {e}", exc_info=True)
    finally:
        loop.close()
        sys.exit(0)
