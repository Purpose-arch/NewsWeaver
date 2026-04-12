# Используем лёгкий официальный образ
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app

# Устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код
COPY src /app/src

# Запуск бота
CMD ["python", "src/core/main.py"]