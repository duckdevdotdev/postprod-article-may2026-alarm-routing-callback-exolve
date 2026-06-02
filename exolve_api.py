import logging
import requests
from typing import Any, Dict, Optional
from config import Config

logger = logging.getLogger("ExolveAPI")

MAKE_CALLBACK_URL = "https://api.exolve.ru/call/v1/MakeCallback"


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {Config.EXOLVE_API_KEY}",
        "Content-Type": "application/json",
    }


def _normalize_phone(phone: str, field_name: str) -> str:
    """Приводит номер к цифровому виду и проверяет его длину во избежание отправки пустых полей."""
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(digits) < 10:
        raise ValueError(f"Номер телефона {field_name} некорректен (менее 10 цифр): '{phone}'")
    return digits


def _to_int(value: str, field_name: str) -> int:
    """Переводит строковое значение в целочисленный тип, требуемый для REST API МТС Exolve."""
    clean_val = str(value).strip()
    if not clean_val:
        raise ValueError(f"Параметр {field_name} отсутствует в конфигурации.")
    try:
        return int(clean_val)
    except ValueError as exc:
        raise ValueError(f"Параметр {field_name} должен содержать только цифры. Получено: '{clean_val}'") from exc


def build_make_callback_payload(
    tenant_phone: str,
    destination_phone: str,
    client_audio_resource_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Формирует спецификацию Callback-вызова под стандарт API МТС Exolve."""
    exolve_number = _normalize_phone(Config.EXOLVE_NUMBER, "EXOLVE_NUMBER")
    tenant_phone = _normalize_phone(tenant_phone, "tenant_phone")
    destination_phone = _normalize_phone(destination_phone, "destination_phone")

    payload: Dict[str, Any] = {
        "number_code": _to_int(exolve_number, "EXOLVE_NUMBER"),
        "callback_resource_id": _to_int(Config.EXOLVE_CALLBACK_RESOURCE_ID, "EXOLVE_CALLBACK_RESOURCE_ID"),
        "line_1": {
            "destinations": [{"number": tenant_phone}],
            "display_number": exolve_number,
        },
        "line_2": {
            "destinations": [{"number": destination_phone}],
            "display_number": exolve_number,
        },
    }

    # Подключаем аудиоприветствие для жильца, если ресурс настроен в .env
    if client_audio_resource_id:
        payload["line_1"]["audio"] = {
            "media_resource_id": _to_int(client_audio_resource_id, "EXOLVE_CLIENT_AUDIO_RESOURCE_ID")
        }

    return payload


def initiate_callback(tenant_phone: str, destination_phone: str) -> bool:
    """Инициирует сеанс связи Callback на платформе МТС Exolve."""
    if Config.EXOLVE_MOCK:
        logger.info(f"[MOCK] Запуск Callback: {tenant_phone} <-> {destination_phone}")
        return True

    try:
        payload = build_make_callback_payload(
            tenant_phone=tenant_phone,
            destination_phone=destination_phone,
            client_audio_resource_id=Config.EXOLVE_CLIENT_AUDIO_RESOURCE_ID or None,
        )
    except ValueError as exc:
        logger.error(f"Ошибка параметров API МТС Exolve: {exc}")
        return False

    try:
        logger.info(f"Запрос Callback в Exolve: {tenant_phone} -> {destination_phone}")
        response = requests.post(
            MAKE_CALLBACK_URL,
            headers=_headers(),
            json=payload,
            timeout=Config.EXOLVE_TIMEOUT,
        )

        if response.status_code < 200 or response.status_code >= 300:
            logger.error(f"АТС ответила ошибкой {response.status_code}. Тело ответа: {response.text}")
            return False

        logger.info("Обратный звонок успешно зарегистрирован платформой МТС Exolve.")
        return True

    except requests.RequestException as exc:
        logger.error(f"Сбой сетевого соединения при работе с API МТС Exolve: {exc}")
        return False
