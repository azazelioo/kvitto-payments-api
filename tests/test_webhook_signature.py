import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Payment

TEST_SECRET = "test-only-secret"


def sign(body: bytes) -> str:
    return hmac.new(TEST_SECRET.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def signed_client(database_url: str):
    with TestClient(create_app(database_url, webhook_secret=TEST_SECRET)) as client:
        tariff_id = client.get("/tariffs").json()[0]["id"]
        response = client.post(
            "/payments",
            json={
                "tariff_id": tariff_id,
                "email": "student@example.com",
                "method": "card",
            },
        )
        assert response.status_code == 201
        yield client, response.json()["id"]


def body(payment_id: int, status: str = "succeeded") -> bytes:
    return f'{{"payment_id":{payment_id},"status":"{status}"}}'.encode()


def send(client, content: bytes, signature=None):
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["X-Signature"] = signature
    return client.post("/webhooks/bank", content=content, headers=headers)


def stored_status(client, payment_id):
    with client.app.state.session_factory() as session:
        return session.get(Payment, payment_id).status


@pytest.mark.parametrize("formatting", [False, True])
def test_correct_signature(signed_client, formatting):
    client, payment_id = signed_client
    content = (
        f'{{\n  "status": "succeeded", "payment_id": {payment_id}\n}}'.encode()
        if formatting
        else body(payment_id)
    )
    response = send(client, content, sign(content))
    assert response.status_code == 200
    assert response.json() == {"result": "ok"}
    assert stored_status(client, payment_id) == "succeeded"


@pytest.mark.parametrize(
    "signature", [None, "0" * 64, "", "bad", "g" * 64, "a" * 63, b"\xff" * 64]
)
def test_bad_signature(signed_client, signature):
    client, payment_id = signed_client
    response = send(client, body(payment_id), signature)
    assert response.status_code == 401
    assert stored_status(client, payment_id) == "pending"


def test_changed_body(signed_client):
    client, payment_id = signed_client
    response = send(client, body(payment_id, "failed"), sign(body(payment_id)))
    assert response.status_code == 401
    assert stored_status(client, payment_id) == "pending"


def test_disabled_secret(database_url: str, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", TEST_SECRET)
    with TestClient(create_app(database_url, webhook_secret="")) as client:
        tariff_id = client.get("/tariffs").json()[0]["id"]
        payment_id = client.post(
            "/payments",
            json={
                "tariff_id": tariff_id,
                "email": "student@example.com",
                "method": "card",
            },
        ).json()["id"]
        response = send(client, body(payment_id))
        assert response.status_code == 200
        assert stored_status(client, payment_id) == "succeeded"


def test_signed_invalid_transition(signed_client):
    client, payment_id = signed_client
    content = body(payment_id, "pending")
    response = send(client, content, sign(content))
    assert response.status_code == 409
    assert response.json() == {"error": "invalid_transition"}
    assert stored_status(client, payment_id) == "pending"


@pytest.mark.parametrize(
    "content",
    [
        b"{}",
        b'{"payment_id":true,"status":"succeeded"}',
        b'{"payment_id":1,"status":"unknown"}',
    ],
)
def test_signed_invalid_body(signed_client, content):
    client, payment_id = signed_client
    response = send(client, content, sign(content))
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert stored_status(client, payment_id) == "pending"


def test_secret_read_at_creation(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", TEST_SECRET)
    application = create_app()
    monkeypatch.setenv("WEBHOOK_SECRET", "changed")
    assert application.state.webhook_secret == TEST_SECRET
    assert create_app(webhook_secret="explicit").state.webhook_secret == "explicit"
    monkeypatch.delenv("WEBHOOK_SECRET")
    assert create_app().state.webhook_secret == ""
    monkeypatch.setenv("WEBHOOK_SECRET", "")
    assert create_app().state.webhook_secret == ""
