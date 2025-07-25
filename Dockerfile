# Используем официальный образ Python (slim-версию для меньшего размера)
FROM python:3.9-slim

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Копируем файл зависимостей в контейнер
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем все файлы проекта в рабочую директорию контейнера
COPY . .

# Переменная окружения для немедленного вывода логов
ENV PYTHONUNBUFFERED=1

# Определяем команду для запуска бота
CMD ["python", "TXT_to_DXF_BOT.py"]
