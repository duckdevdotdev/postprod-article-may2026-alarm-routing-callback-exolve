import os
from dotenv import load_dotenv

# Загружаем переменные из файла .env
load_dotenv()


class Config:
    # Сессии Flask и безопасность авторизации диспетчера
    SECRET_KEY = os.environ.get("SECRET_KEY", "change_me")
    DB_NAME = os.environ.get("DB_NAME", "uk_calls.db")

    # Авторизация диспетчера для доступа к странице /queue
    QUEUE_USERNAME = os.environ.get("QUEUE_USERNAME", "admin")
    QUEUE_PASSWORD = os.environ.get("QUEUE_PASSWORD", "change_me")

    # Токен проверки подлинности вебхуков от робота
    WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "change_me")

    # Ключи и АТС-настройки МТС Exolve
    EXOLVE_API_KEY = os.environ.get("EXOLVE_API_KEY", "your_api_key_here")
    EXOLVE_NUMBER = os.environ.get("EXOLVE_NUMBER", "78005553535")

    # Ресурс Callback МТС Exolve (должен быть создан заранее)
    EXOLVE_CALLBACK_RESOURCE_ID = os.environ.get("EXOLVE_CALLBACK_RESOURCE_ID", "123456")
    EXOLVE_CLIENT_AUDIO_RESOURCE_ID = os.environ.get("EXOLVE_CLIENT_AUDIO_RESOURCE_ID", "")

    # Эмуляция (Mock) телефонии для локального запуска без реальных вызовов
    EXOLVE_MOCK = os.environ.get("EXOLVE_MOCK", "true").lower() == "true"
    EXOLVE_TIMEOUT = int(os.environ.get("EXOLVE_TIMEOUT", "10"))

    # Номера перенаправления по умолчанию
    EMERGENCY_SERVICE_PHONE = os.environ.get("EMERGENCY_SERVICE_PHONE", "79991112233")
    DEFAULT_OPERATOR_PHONE = os.environ.get("DEFAULT_OPERATOR_PHONE", "79991114455")
