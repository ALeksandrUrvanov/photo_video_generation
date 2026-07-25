# Слой 0: Базовый образ
FROM python:3.10-slim

# Слой 1: Системные зависимости
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    curl \
    libgl1 \
    libglib2.0-0 \
    libjpeg-dev \
    libpng-dev \
    && apt-get clean \
    && rm -rf /tmp/* \
    && rm -rf /var/tmp/*

# Слой 2: Рабочая директория
WORKDIR /app

# Слой 3: Настройка окружения
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DOCKER_ENV=true

# Слой 4: Python зависимости
COPY requirements.txt .

RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --upgrade pip && \
    python -m pip install --timeout=300 --retries=10 \
        -r requirements.txt && \
    apt-get update && \
    apt-get remove -y build-essential && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    rm -rf /tmp/* && \
    rm -rf /var/tmp/*

# Слой 5: Проверка установки
RUN python -c "import fastapi; print('✓ FastAPI установлен:', fastapi.__version__)" && \
    python -c "import openai; print('✓ OpenAI установлен:', openai.__version__)" && \
    python -c "import PIL; print('✓ Pillow установлен:', PIL.__version__)" && \
    python -c "import boto3; print('✓ boto3 установлен:', boto3.__version__)"

# Слой 6: Код приложения
COPY . .

# Слой 7: Настройка entrypoint (entrypoint.sh уже скопирован через COPY . .)
RUN chmod +x /app/entrypoint.sh

# Слой 8: Экспонирование порта
EXPOSE 8080

# Слой 9: Healthcheck для оркестраторов
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Слой 10: Точка входа (запуск всех сервисов)
CMD ["/app/entrypoint.sh"]
