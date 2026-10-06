# Kvitto Payments API

Учебный API оплаты курсов по тестовому заданию Junior Python / FastAPI.
Python 3.11+ (Docker и CI: 3.14.6), FastAPI, Pydantic v2, SQLAlchemy 2,
SQLite, Alembic; проверки — pytest + httpx и ruff.

## Docker

Из корня репозитория, при работающем Docker:

```zsh
docker compose up --build
```

Файл `.env` не обязателен. API: http://127.0.0.1:8000,
Swagger UI: http://127.0.0.1:8000/docs. При занятом порте:
`API_PORT=18000 docker compose up --build`.
Миграции выполняются перед сервером; затем приложение добавляет отсутствующие
тарифы. SQLite хранится в именованном volume в `/data`.
Остановка: Ctrl+C или `docker compose stop` из другого терминала.
Не используйте `down -v` для обычной остановки: он удаляет данные.

## Локальный запуск (macOS zsh)

Рекомендуется Python 3.14.6 для совпадения с фиксацией зависимостей.
Выполняйте команды из корня репозитория:

```zsh
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-runtime.txt
python -m pip install -c requirements-runtime.txt ".[dev]"
python -m pip check
export DATABASE_URL='sqlite:///./kvitto.db'
export WEBHOOK_SECRET=''
python -m alembic upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

После изменения кода:

```zsh
python -m pytest
ruff check .
ruff format --check .
```

Тесты создают отдельные временные SQLite-базы через реальные миграции.
`requirements-runtime.txt` фиксирует runtime-зависимости, включая транзитивные;
constraints сохраняют эти версии при установке dev-инструментов.
CI выполняет те же проверки на push и pull_request.

## Переменные окружения

- `DATABASE_URL`: локально по умолчанию `sqlite:///./kvitto.db`;
  Compose задаёт `sqlite:////data/kvitto.db`.
- `WEBHOOK_SECRET`: отсутствующее или пустое значение отключает HMAC.
  Непустое значение требует `X-Signature`: hex HMAC-SHA256 исходных байтов тела.
  Отсутствующая, неверная или некорректная подпись — 401.

Приложение само не загружает `.env`; задавайте переменные через `export`.
Compose умеет читать `.env` для подстановок, но этот файл необязателен.
`.env.example` содержит только образец, не секрет. Секрет считывается при создании
приложения: после его изменения перезапустите сервер; для Compose — пересоздайте
контейнер через `docker compose up -d --force-recreate`.

## Примеры API

Следующие команды выполняются в другом терминале с активированной `.venv`.

```zsh
export API_URL='http://127.0.0.1:8000'
curl -fsS "$API_URL/tariffs"
TARIFF_ID=$(curl -fsS "$API_URL/tariffs" | python -c 'import json,sys; print(next(t["id"] for t in json.load(sys.stdin) if t["title"] == "standard"))')
KEY=$(python -c 'import uuid; print(uuid.uuid4())')
PAYLOAD="{\"tariff_id\":$TARIFF_ID,\"email\":\"student@example.com\",\"method\":\"installment\",\"installment_months\":3,\"promo_code\":\"kvitto10\"}"
PAYMENT=$(curl -fsS "$API_URL/payments" -H 'Content-Type: application/json' -H "Idempotency-Key: $KEY" -d "$PAYLOAD")
printf '%s\n' "$PAYMENT"
PAYMENT_ID=$(printf '%s' "$PAYMENT" | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')
# Повтор: 200 и та же запись; первый запрос — 201.
curl -fsS "$API_URL/payments" -H 'Content-Type: application/json' -H "Idempotency-Key: $KEY" -d "$PAYLOAD"
curl -fsS "$API_URL/payments/$PAYMENT_ID"
curl -fsS --get "$API_URL/payments" --data-urlencode 'email=student@example.com' --data-urlencode 'status=pending'
# Без подписи допустимо только при отключённой проверке HMAC.
curl -fsS "$API_URL/webhooks/bank" -H 'Content-Type: application/json' -d "{\"payment_id\":$PAYMENT_ID,\"status\":\"succeeded\"}"
```

### Подписанный вебхук

Перед запуском сервера задайте непустой секрет, например:
`export WEBHOOK_SECRET=$(python -c 'import secrets; print(secrets.token_hex(32))')`.
Клиент должен получить то же значение через окружение; не печатайте его и не
добавляйте в Git. Для Compose экспортируйте секрет до запуска.
Пример ниже использует стандартную библиотеку Python, создаёт новый платёж,
берёт его реальный ID и подписывает именно отправляемые байты:

```python
import hashlib
import hmac
import json
import os
from urllib.request import Request, urlopen

base = os.environ.get("API_URL", "http://127.0.0.1:8000")
secret = os.environ["WEBHOOK_SECRET"]
assert secret, "Задайте тот же непустой WEBHOOK_SECRET, что у сервера"


def request(path, body=None, headers=None):
    with urlopen(
        Request(base + path, data=body, headers=headers or {}), timeout=10
    ) as response:
        return response.status, json.load(response)


tariff_id = next(t["id"] for t in request("/tariffs")[1] if t["title"] == "standard")
content_type = {"Content-Type": "application/json"}
create_body = json.dumps(
    {"tariff_id": tariff_id, "email": "signed@example.com", "method": "card"}
).encode()
code, payment = request("/payments", create_body, content_type)
assert code == 201
body = json.dumps({"payment_id": payment["id"], "status": "succeeded"}).encode()
signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
code, result = request(
    "/webhooks/bank", body, {**content_type, "X-Signature": signature}
)
assert code == 200 and result == {"result": "ok"}
print("Платёж", payment["id"], "вебхук:", code, result)
```

Запустите этот код через `python` или сохраните в отдельный временный скрипт.
HMAC подтверждает целостность и знание секрета, но не шифрует содержимое.

## Правила и принятые решения

Требования PDF: все деньги — целые копейки; KVITTO10 даёт 10% без учёта регистра.
Рассрочка только на 3/6/12 месяцев: `divmod` распределяет лишние копейки по первым
платежам; сумма графика равна сумме к оплате. Тарифы: basic — 990000,
standard — 1990000, premium — 2990000; существующие тарифы не перезаписываются.

Новый платёж — pending. Разрешены только pending → succeeded, pending → failed,
succeeded → refunded. Повтор статуса и остальные переходы дают ровно
409 `{"error":"invalid_transition"}`, запись не меняется. Успех вебхука —
200 `{"result":"ok"}`; отсутствующий платёж — 404. Обновление условное по исходному
статусу: проигравшее конкурентное событие получает 409 без автоматического повтора.

Наши решения для неоднозначностей:
- `amount` — после скидки, `discount` — размер скидки; для других цен скидка
  вычисляется как `price // 10`, то есть округляется вниз до копейки.
- Неизвестный `tariff_id` — стандартный 422 с `detail` и `body.tariff_id`.
- Отсутствующий/null промокод — без скидки; пустой, неизвестный и код с пробелами — 422.
  Для card/sbp срок отсутствует/null, график — null; ID и срок не принимают bool/float.
- Idempotency-Key чувствителен к регистру, непустой сохраняется без изменения;
  пустой/пробельный — 422. UNIQUE в БД защищает от гонок. Повтор возвращает текущую
  запись с 200 даже при другом валидном теле и неизвестном положительном tariff_id;
  невалидное тело сначала получает стандартный 422. Без ключа создаётся новая запись.
- Фильтры списка — точное равенство после валидации EmailStr, вместе AND;
  порядок по id, без совпадений `[]`, пагинации нет.
- В SQLite время хранится без пояса по договорённости UTC; API явно выдаёт UTC (`Z`).
- Пустой секрет отключает HMAC; подпись — 64 hex-символа без префикса.

## Ограничения

Учебный сервис на файловой SQLite с одним процессом приложения. Нет авторизации,
фронтенда, реального банка и деплоя. Тесты проходят с предупреждением Starlette
об использовании httpx в TestClient; оно не подавлено. Сборка и запуск Docker,
права UID 10001, сохранение платежа при пересоздании и штатное завершение проверены
локально. Команды CI проверены в чистом временном окружении. Результаты
GitHub Actions доступны во вкладке Actions репозитория для каждого коммита.
