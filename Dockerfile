# ==========================================
# ЭТАП 1: BUILD (сборка зависимостей)
# ==========================================
FROM python:3.12-slim AS builder

# Переменные для Python в контейнере:
# - Не кэшируем .pyc файлы (экономим место)
# - Выводим логи сразу (не буферизуем, иначе в docker logs задержки)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on

WORKDIR /build

# 1. Копируем ТОЛЬКО файл зависимостей
#    Docker кэширует этот слой. Если requirements.txt не менялся → pip skip
COPY requirements.txt .

# 2. Устанавливаем зависимости в отдельную директорию
#    --prefix позволяет собрать всё в /install, чтобы потом скопировать только нужное
RUN pip install --prefix=/install -r requirements.txt

# ==========================================
# ЭТАП 2: RUNTIME (минимальный образ для прода)
# ==========================================
FROM python:3.12-slim AS runtime

# Безопасность: создаём непривилегированного пользователя
RUN groupadd -r appuser && useradd -r -g appuser -d /home/appuser -s /sbin/nologin appuser && \
    mkdir -p /app && chown -R appuser:appuser /app

WORKDIR /app

# Копируем только установленные пакеты из builder
COPY --from=builder /install /usr/local

# Копируем код приложения
COPY --chown=appuser:appuser . .

# Переключаемся на non-root пользователя
USER appuser

# Healthcheck: Docker будет проверять /healthz каждые 30 сек
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1

# Запуск приложения
# Используем exec-form CMD (чтобы сигналы SIGTERM доходили до uvicorn)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
