"""Order Processing API v0.2
Минимальное production-ready приложение с:
- healthcheck эндпоинтами для Kubernetes
- graceful shutdown (корректное завершение при рестарте)
- настройками через .env файл
"""

# one one
# === ИМПОРТЫ ===
import os           # Работа с переменными окружения
import signal       # Обработка сигналов ОС (SIGTERM, SIGINT)
import asyncio      # Асинхронность для graceful shutdown
from contextlib import asynccontextmanager  # Менеджер контекста для lifespan
from fastapi import FastAPI                 # Веб-фреймворк
from pydantic_settings import BaseSettings  # Валидация конфигов

# === КОНФИГУРАЦИЯ ЧЕРЕЗ PYDANTIC ===
class Settings(BaseSettings):
    """
    Настройки приложения.
    Pydantic автоматически:
    1. Читает переменные окружения (APP_ENV, DB_HOST и т.д.)
    2. Применяет значения по умолчанию, если переменная не задана
    3. Валидирует типы (str, int, bool)
    """
    APP_ENV: str = "production"      # Окружение: development/staging/production
    DB_HOST: str = "localhost"       # Хост базы данных
    DB_PORT: int = 5432              # Порт PostgreSQL
    REDIS_URL: str = "redis://localhost:6379/0"  # URL для Redis/Celery

    class Config:
        env_file = ".env"  # Дополнительно читаем переменные из файла .env

# Создаём экземпляр настроек (глобальный, используется во всём приложении)
settings = Settings()

# === GRACEFUL SHUTDOWN: флаг для асинхронной остановки ===
# Это asyncio.Event() — примитив синхронизации.
# Когда придёт сигнал SIGTERM, мы "установим" этот флаг,
# и асинхронные задачи смогут корректно завершиться.
shutdown_event = asyncio.Event()

# === LIFESPAN: контекст запуска/остановки приложения ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan manager — выполняется:
    - ДО старта сервера: подключение к БД, инициализация кеша
    - ПОСЛЕ получения сигнала остановки: закрытие соединений, очистка ресурсов
    
    Аналог __enter__/__exit__ в Python, но для асинхронного веб-сервера.
    """
    # === STARTUP ===
    print("🚀 Application startup: connecting to DB, cache, queue...")
    # Здесь был бы код: await db.connect(), await redis.ping() и т.д.
    
    yield  # <--- Приложение принимает запросы ЗДЕСЬ
    
    # === SHUTDOWN ===
    print("🛑 Graceful shutdown initiated...")
    shutdown_event.set()  # Сообщаем всем задачам: "пора завершаться"
    
    # Имитация закрытия ресурсов (в проде: await db.disconnect())
    await asyncio.sleep(1)
    print("✅ Shutdown complete: all connections closed")

# === ИНИЦИАЛИЗАЦИЯ FASTAPI ===
app = FastAPI(
    title="Order Processing API",
    version="0.2.0",
    description="REST API для управления заказами",
    lifespan=lifespan  # Подключаем наш менеджер жизненного цикла
)

# === ЭНДПОИНТЫ ===

@app.get("/healthz")
def healthcheck():
    """
    Kubernetes LIVENESS probe.
    Отвечает на вопрос: "Приложение живо? (процесс не завис)"
    
    Если этот эндпоинт не отвечает — K8s убьёт под и перезапустит.
    """
    return {
        "status": "ok",
        "env": settings.APP_ENV,
        "python": os.sys.version.split()[0]  # Версия Python для дебага
    }

@app.get("/live")
def liveness():
    """
    Альтернативный liveness-чек (для совместимости с разными системами).
    """
    return {"alive": True}

@app.get("/ready")
def readiness():
    """
    Kubernetes READINESS probe.
    Отвечает на вопрос: "Готов ли сервис принимать трафик?"
    
    Здесь можно проверить:
    - Подключение к базе данных
    - Доступность очереди сообщений
    - Загружены ли кэши
    
    Если /ready возвращает ошибку — K8s НЕ будет направлять трафик на этот под,
    но НЕ будет его перезапускать (в отличие от liveness).
    """
    # В проде: попробовать подключиться к БД, поймать исключение при ошибке
    return {
        "ready": True,
        "checks": {
            "db": "ok",      # await db.healthcheck()
            "queue": "ok"    # await redis.ping()
        }
    }

@app.get("/api/orders")
async def list_orders():
    """
    Бизнес-эндпоинт: список заказов.
    Пока возвращает заглушку, позже — данные из БД.
    """
    # Имитация работы с БД (в проде: await db.fetch_all("SELECT ..."))
    await asyncio.sleep(0.05)
    return {
        "orders": [],
        "meta": {"total": 0, "page": 1, "per_page": 50}
    }

# === ОБРАБОТКА СИГНАЛОВ ОС для graceful shutdown ===
def handle_shutdown(signum, frame):
    """
    Обработчик сигналов SIGTERM / SIGINT.
    
    Почему это важно:
    - При деплое / рестарте systemd / K8s шлёт SIGTERM
    - Если приложение не обработает сигнал — оно убьётся сразу (SIGKILL)
    - Активные запросы прервутся → клиенты получат 502/504
    - С graceful shutdown: приложение дожидается завершения запросов
    
    signum: номер сигнала (15 = SIGTERM, 2 = SIGINT)
    frame: текущий стек вызовов (не используем, но обязателен в сигнатуре)
    """
    print(f"📡 Received signal {signum} ({'SIGTERM' if signum == 15 else 'SIGINT'}), initiating graceful shutdown")
    shutdown_event.set()  # Асинхронно уведомляем задачи о завершении

# Регистрируем обработчики для сигналов завершения
signal.signal(signal.SIGTERM, handle_shutdown)  # systemd / K8s
signal.signal(signal.SIGINT, handle_shutdown)   # Ctrl+C при локальной отладке

# === ЗАПУСК СЕРВЕРА ===
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",        # Слушать все интерфейсы (для Docker)
        port=8000,             # Порт приложения
        timeout_keep_alive=30, # Сколько ждать завершения запросов при shutdown
        workers=2              # Количество worker-процессов (для CPU-bound задач)
    )

