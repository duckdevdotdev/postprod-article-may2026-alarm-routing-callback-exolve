import sqlite3
import time
import logging
from typing import Dict, List, Any
from config import Config

logger = logging.getLogger("Database")


def get_db_connection() -> sqlite3.Connection:
    """Создает соединение с SQLite для текущего потока приложения."""
    conn = sqlite3.connect(Config.DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Инициализация базы данных и индексов очереди."""
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS calls (
                call_id TEXT PRIMARY KEY,   -- Поле для защиты от дублирования вебхуков
                tenant_phone TEXT NOT NULL, -- Номер жильца
                priority INTEGER NOT NULL,  -- 1 = Срочно (Авария), 2 = Обычный вопрос
                status TEXT NOT NULL,       -- callback_pending, callback_started, queued, done, failed
                topic TEXT,                 -- Тема планового обращения
                department TEXT,            -- Ответственный отдел УК
                department_phone TEXT,      -- Телефонный номер отдела
                address TEXT,               -- Адрес
                description TEXT,           -- Описание проблемы
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_calls_status ON calls(status)")
        conn.commit()

    logger.info("База данных готова к работе.")


def create_call_record(
    call_id: str,
    tenant_phone: str,
    priority: int,
    status: str,
    **fields: Any,
) -> bool:
    """Запись вызова. Возвращает False при повторном вебхуке с идентичным call_id."""
    now = int(time.time())
    conn = get_db_connection()

    try:
        with conn:
            conn.execute(
                """
                INSERT INTO calls (
                    call_id,
                    tenant_phone,
                    priority,
                    status,
                    topic,
                    department,
                    department_phone,
                    address,
                    description,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    call_id,
                    tenant_phone,
                    priority,
                    status,
                    fields.get("topic"),
                    fields.get("department"),
                    fields.get("department_phone"),
                    fields.get("address"),
                    fields.get("description"),
                    now,
                    now,
                ),
            )
        return True

    except sqlite3.IntegrityError:
        logger.warning(f"Повторный запрос для call_id: {call_id} отклонен базой данных.")
        return False

    finally:
        conn.close()


def get_active_calls() -> List[Dict[str, Any]]:
    """Возвращает список активных необработанных вызовов в очереди."""
    conn = get_db_connection()

    try:
        rows = conn.execute(
            """
            SELECT * FROM calls
            WHERE status IN ('callback_pending', 'queued', 'callback_started', 'failed')
            ORDER BY priority ASC, created_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    finally:
        conn.close()


def get_archived_calls() -> List[Dict[str, Any]]:
    """Возвращает закрытые заявки для вывода в архив."""
    conn = get_db_connection()

    try:
        rows = conn.execute(
            """
            SELECT *
            FROM calls
            WHERE status = 'done'
            ORDER BY updated_at DESC
            LIMIT 50
            """
        ).fetchall()
        return [dict(row) for row in rows]

    finally:
        conn.close()


def update_call_status(call_id: str, status: str) -> None:
    """Принудительно меняет статус звонка."""
    now = int(time.time())

    with get_db_connection() as conn:
        conn.execute(
            """
            UPDATE calls
            SET status = ?,
                updated_at = ?
            WHERE call_id = ?
            """,
            (status, now, call_id),
        )
