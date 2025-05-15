# main.py
import asyncio
import signal
import sys
from logger import logger
import db
import clients
import parser
import moderation
import requesty
import publisher
import direct_news
import alarm  # Импортируем модуль alarm
from clients import start_clients, close_clients, loop

async def on_shutdown():
    """
    Корректное завершение работы
    """
    logger.info("Завершение работы сервиса...")
    await close_clients()
    await db.close_db()
    logger.info("Сервис остановлен")

async def main():
    """
    Основная точка входа в приложение
    """
    try:
        logger.info("Запуск сервиса...")
        
        # Инициализируем базу данных
        await db.init_db()
        
        # Запускаем все клиенты
        await start_clients()
        
        # Регистрируем обработчики модерации
        await moderation.register_handlers()
        
        # Запускаем парсер сообщений из Telegram
        await parser.start_parser()
        
        # Запускаем парсер тревог
        await alarm.start_alarm_bot()
        
        # Запускаем задачу очистки старых записей
        asyncio.create_task(db.schedule_cleanup(1))
        
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