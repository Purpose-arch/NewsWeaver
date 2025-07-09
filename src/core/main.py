# main.py
import asyncio
import signal
import sys
import os # Импортируем модуль os для доступа к переменным окружения
from aiohttp import web # Импортируем веб-модуль aiohttp
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

async def health_check(request):
    """
    Обработчик для проверки состояния здоровья.
    """
    return web.Response(text="OK")

async def start_web_server():
    """
    Запускает минимальный HTTP-сервер для проверки состояния здоровья.
    """
    port = int(os.environ.get("PORT", 8080)) # Получаем порт из переменной окружения или используем 8080 по умолчанию
    app = web.Application()
    app.router.add_get("/health", health_check) # Добавляем маршрут /health
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port) # Привязываемся ко всем сетевым интерфейсам
    logger.info(f"HTTP-сервер запущен на порту {port}")
    await site.start()
    return runner # Возвращаем runner для корректного завершения

async def main():
    """
    Основная точка входа в приложение
    """
    web_server_runner = None # Инициализируем переменную для runner веб-сервера
    try:
        logger.info("Запуск сервиса...")
        
        # Запускаем HTTP-сервер в фоновом режиме
        web_server_runner = await start_web_server()

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
        if web_server_runner: # Корректно завершаем веб-сервер при завершении работы
            await web_server_runner.cleanup()

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