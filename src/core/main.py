# main.py
import asyncio
import signal
import sys
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

async def main():
    """
    Основная точка входа в приложение
    """
    try:
        logger.info("Запуск сервиса...")
        
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