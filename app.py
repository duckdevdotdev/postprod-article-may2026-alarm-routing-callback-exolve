import logging
import os
from functools import wraps
from hmac import compare_digest
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string, redirect, url_for, Response
from config import Config
from database import (
    init_db,
    create_call_record,
    get_active_calls,
    get_archived_calls,
    update_call_status,
    get_db_connection,
)
from exolve_api import initiate_callback

# Сквозной логгер
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("Application")

app = Flask(__name__)
app.config.from_object(Config)

with app.app_context():
    init_db()

# Телефоны отделов заданы в демонстрационных целях прямо в коде.
# В промышленной среде их рекомендуется выносить в конфигурационный файл или базу данных.
TOPICS = {
    "1": {"topic": "Подать данные счетчиков", "dept": "Бухгалтерия", "phone": "79991114455"},
    "2": {"topic": "Оставить заявку на мастера", "dept": "Мастер участка", "phone": "79991114466"},
    "3": {"topic": "Пожаловаться", "dept": "Отдел контроля качества", "phone": "79991114477"},
    "4": {"topic": "Другое", "dept": "Общий отдел", "phone": "79991114488"},
}


# --- Защита интерфейса /queue (Basic Authentication) ---

def check_queue_auth(username: str, password: str) -> bool:
    """Проверяет логин и пароль для доступа к панели /queue."""
    return (
        compare_digest(username or "", Config.QUEUE_USERNAME)
        and compare_digest(password or "", Config.QUEUE_PASSWORD)
    )


def require_queue_auth(view_func):
    """Декоратор для защиты панели диспетчера через базовую аутентификацию."""
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_queue_auth(auth.username, auth.password):
            return Response(
                "Authentication required",
                401,
                {"WWW-Authenticate": 'Basic realm="UK Queue"'},
            )
        return view_func(*args, **kwargs)

    return wrapped


# --- Роутинг входящих вебхуков ---

@app.route("/webhook/call_input", methods=["POST"])
def handle_call_input():
    """Эндпоинт приема вебхуков от голосового робота."""
    token = request.args.get("token")
    if token != Config.WEBHOOK_SECRET:
        return "Unauthorized", 401

    data = request.json or {}
    call_id = data.get("call_id")
    tenant_phone = data.get("tenant_phone")
    urgency_dtmf = data.get("urgency_dtmf")
    topic_dtmf = data.get("topic_dtmf")
    address = data.get("address", "Адрес не указан")
    description = data.get("description", "Описание не заполнено")

    if not call_id or not tenant_phone:
        return jsonify({"error": "Bad Request. Missing call_id or tenant_phone"}), 400

    # СЦЕНАРИЙ 1: Явный выбор аварийной ситуации (Кнопка 1)
    if urgency_dtmf == "1":
        is_created = create_call_record(
            call_id=call_id,
            tenant_phone=tenant_phone,
            priority=1,
            status="callback_pending",  # Заявка создана, система готовится звонить
            topic="Авария",
            department="Аварийная служба",
            department_phone=Config.EMERGENCY_SERVICE_PHONE,
            address=address,
            description=description,
        )
        if not is_created:
            return jsonify({"status": "already_processed"}), 200

        success = initiate_callback(tenant_phone, Config.EMERGENCY_SERVICE_PHONE)
        if success:
            update_call_status(call_id, "callback_started")
            return jsonify({"status": "emergency_connected"}), 200

        update_call_status(call_id, "failed")
        return jsonify({"status": "emergency_failed"}), 500

    # СЦЕНАРИЙ 2: Обычное обращение (Кнопка 2) или fallback, если пользователь молчит.
    # Звонок не считается аварийным. Сохраняется в БД со статусом queued без автообзвона.
    topic_info = TOPICS.get(
        str(topic_dtmf),
        {
            "topic": "Другое (не определено)",
            "dept": "Общий отдел",
            "phone": Config.DEFAULT_OPERATOR_PHONE,
        },
    )

    is_created = create_call_record(
        call_id=call_id,
        tenant_phone=tenant_phone,
        priority=2,
        status="queued",
        topic=topic_info["topic"],
        department=topic_info["dept"],
        department_phone=topic_info["phone"],
        address=address,
        description=description,
    )
    if is_created:
        logger.info(f"[{call_id}] Заявка '{topic_info['topic']}' сохранена в очередь.")
        return jsonify({"status": "added_to_queue"}), 200

    return jsonify({"status": "already_processed"}), 200


# Панель очереди диспетчера
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Очередь заявок УК</title>
    <style>
        body { font-family: Arial, sans-serif; background: #f4f6f9; margin: 0; padding: 30px; }
        .container { max-width: 1100px; margin: 0 auto; }
        h1 { color: #2c3e50; border-bottom: 2px solid #bdc3c7; padding-bottom: 10px; }
        .security-notice { background: #dff9fb; border-left: 5px solid #22a6b3; padding: 12px; margin-bottom: 20px; font-size: 0.9rem; color: #130f40; }
        .card { background: white; border-radius: 6px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); padding: 20px; margin-bottom: 15px; border-left: 6px solid #ccc; }
        .card.priority-1 { border-left-color: #e74c3c; }
        .card.priority-2 { border-left-color: #3498db; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
        .phone { font-size: 1.2rem; font-weight: bold; }
        .status { font-size: 0.85rem; font-weight: bold; text-transform: uppercase; padding: 3px 8px; border-radius: 3px; }
        .status.callback_pending { background: #ffeaa7; color: #d63031; }
        .status.queued { background: #ffeaa7; color: #d63031; }
        .status.callback_started { background: #dfe6e9; color: #2d3436; }
        .status.failed { background: #fab1a0; color: #c0392b; }
        .status.done { background: #badc58; color: #27ae60; }
        .details { font-size: 0.95rem; line-height: 1.4; color: #34495e; margin-bottom: 15px; }
        .actions { display: flex; gap: 10px; }
        .btn { padding: 8px 15px; border: none; border-radius: 4px; font-weight: bold; cursor: pointer; text-decoration: none; font-size: 0.9rem; }
        .btn-call { background: #2ecc71; color: white; }
        .btn-done { background: #34495e; color: white; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Диспетчерская служба УК: Очередь заявок</h1>

        <div class="security-notice">
            <strong>Примечание:</strong> Панель /queue защищена Basic Auth. В production лучше дополнительно ограничить доступ через VPN, IP allowlist или полноценную авторизацию.
        </div>

        <div style="margin-bottom: 20px;">
            <a href="/queue" class="btn btn-done" style="background:#7f8c8d;">Обновить список</a>
        </div>

        <div class="section-title" style="font-weight:bold; margin-bottom:15px; font-size:1.1rem; color:#7f8c8d;">АКТИВНЫЕ ЗАЯВКИ</div>
        <div>
            {% for call in active_calls %}
            <div class="card priority-{{ call.priority }}">
                <div class="header">
                    <span class="phone">📞 {{ call.tenant_phone }}</span>
                    <span class="status {{ call.status }}">{{ call.status }}</span>
                </div>
                <div class="details">
                    <strong>Категория:</strong> {{ call.topic }} (Отдел: {{ call.department }})<br>
                    <strong>Адрес:</strong> {{ call.address }}<br>
                    <strong>Описание проблемы:</strong> {{ call.description }}<br>
                    <strong>Дата поступления:</strong> {{ datetime.fromtimestamp(call.created_at).strftime('%Y-%m-%d %H:%M:%S') }}
                </div>
                <div class="actions">
                    {% if call.status in ['queued', 'failed'] %}
                    <form action="/queue/call/{{ call.call_id }}" method="post" style="display:inline;">
                        <button type="submit" class="btn btn-call">Позвонить</button>
                    </form>
                    {% endif %}

                    <form action="/queue/complete/{{ call.call_id }}" method="post" style="display:inline;">
                        <button type="submit" class="btn btn-done">Выполнено</button>
                    </form>
                </div>
            </div>
            {% else %}
            <div style="color: #7f8c8d; font-style: italic; margin-bottom: 30px;">Активных заявок в очереди нет.</div>
            {% endfor %}
        </div>

        <div class="section-title" style="font-weight:bold; margin-bottom:15px; font-size:1.1rem; color:#7f8c8d;">ЗАКРЫТЫЕ ЗАЯВКИ (АРХИВ)</div>
        <div>
            {% for call in archived_calls %}
            <div class="card priority-{{ call.priority }}" style="opacity: 0.65;">
                <div class="header">
                    <span class="phone">📞 {{ call.tenant_phone }}</span>
                    <span class="status {{ call.status }}">{{ call.status }}</span>
                </div>
                <div class="details">
                    <strong>Категория:</strong> {{ call.topic }}<br>
                    <strong>Адрес:</strong> {{ call.address }}<br>
                    <strong>Выполнено:</strong> {{ datetime.fromtimestamp(call.updated_at).strftime('%Y-%m-%d %H:%M:%S') }}
                </div>
            </div>
            {% else %}
            <div style="color: #7f8c8d; font-style: italic;">Архив выполненных заявок пуст.</div>
            {% endfor %}
        </div>
    </div>
</body>
</html>
"""


@app.route("/queue", methods=["GET"])
@require_queue_auth
def view_queue():
    """Считывает очереди из БД и рендерит интерфейс."""
    active_calls = get_active_calls()
    archived_calls = get_archived_calls()
    return render_template_string(
        HTML_TEMPLATE,
        active_calls=active_calls,
        archived_calls=archived_calls,
        datetime=datetime,
    )


@app.route("/queue/call/<call_id>", methods=["POST"])
@require_queue_auth
def trigger_manual_callback(call_id: str):
    """Маршрут кнопки 'Позвонить' — инициирует Callback и возвращает на страницу очереди."""
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM calls WHERE call_id = ?", (call_id,)).fetchone()
        if not row:
            return "Заявка не найдена", 404

        call = dict(row)

        # Серверная защита от повторного запуска Callback.
        # Кнопка в UI скрыта для других статусов, но POST-запрос можно отправить вручную.
        if call["status"] not in ["queued", "failed"]:
            logger.warning(
                f"Попытка повторного Callback для заявки {call_id} со статусом {call['status']}"
            )
            return redirect(url_for("view_queue"))

        if not call.get("department_phone"):
            logger.error(f"Для заявки {call_id} не указан телефон отдела.")
            update_call_status(call_id, "failed")
            return redirect(url_for("view_queue"))

        success = initiate_callback(call["tenant_phone"], call["department_phone"])
        if success:
            update_call_status(call_id, "callback_started")
            logger.info(f"Диспетчер запустил Callback для: {call_id}")
        else:
            update_call_status(call_id, "failed")
            logger.error(f"Не удалось запустить Callback для: {call_id}")

    finally:
        conn.close()

    return redirect(url_for("view_queue"))


@app.route("/queue/complete/<call_id>", methods=["POST"])
@require_queue_auth
def mark_as_completed(call_id: str):
    """Маршрут кнопки 'Выполнено' — закрывает заявку."""
    update_call_status(call_id, "done")
    logger.info(f"Заявка {call_id} закрыта.")
    return redirect(url_for("view_queue"))


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=5000, debug=debug)
