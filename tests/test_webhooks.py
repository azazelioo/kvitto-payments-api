from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock, get_ident

import pytest
from fastapi.testclient import TestClient

from app import webhooks
from app.main import create_app
from app.models import Payment
from app.schemas import PaymentResponse

STATUSES = ("pending", "succeeded", "failed", "refunded")
ALLOWED = {("pending", "succeeded"), ("pending", "failed"), ("succeeded", "refunded")}


def create_payment(client: TestClient) -> int:
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
    return response.json()["id"]


@pytest.mark.parametrize("source", STATUSES)
@pytest.mark.parametrize("target", STATUSES)
def test_all_transitions(database_url: str, source: str, target: str) -> None:
    application = create_app(database_url)
    with TestClient(application) as client:
        payment_id = create_payment(client)
        with application.state.session_factory() as session:
            payment = session.get(Payment, payment_id)
            payment.status = source
            session.commit()
            before = PaymentResponse.model_validate(payment).model_dump()
        response = client.post(
            "/webhooks/bank", json={"payment_id": payment_id, "status": target}
        )
        allowed = (source, target) in ALLOWED
        assert response.status_code == (200 if allowed else 409)
        assert response.json() == (
            {"result": "ok"} if allowed else {"error": "invalid_transition"}
        )
        with application.state.session_factory() as session:
            after = PaymentResponse.model_validate(
                session.get(Payment, payment_id)
            ).model_dump()
            expected = {**before, "status": target} if allowed else before
            assert after == expected


def test_missing_payment(database_url: str) -> None:
    with TestClient(create_app(database_url)) as client:
        response = client.post(
            "/webhooks/bank", json={"payment_id": 999999, "status": "succeeded"}
        )
        assert response.status_code == 404


@pytest.mark.parametrize(
    "updates",
    [
        {"payment_id": 0},
        {"payment_id": -1},
        {"payment_id": True},
        {"payment_id": 1.5},
        {"payment_id": 1.0},
        {"payment_id": "1"},
        {"payment_id": None},
        {"status": "unknown"},
        {"status": None},
    ],
)
def test_invalid_body(database_url: str, updates: dict) -> None:
    application = create_app(database_url)
    with TestClient(application) as client:
        payment_id = create_payment(client)
        response = client.post(
            "/webhooks/bank",
            json={"payment_id": payment_id, "status": "succeeded", **updates},
        )
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)
        with application.state.session_factory() as session:
            assert session.get(Payment, payment_id).status == "pending"


@pytest.mark.parametrize("body", [{}, {"payment_id": 1}, {"status": "succeeded"}, []])
def test_incomplete_body(database_url: str, body) -> None:
    with TestClient(create_app(database_url)) as client:
        response = client.post("/webhooks/bank", json=body)
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)


def test_concurrent_transitions(database_url: str, monkeypatch) -> None:
    application = create_app(database_url)
    barrier = Barrier(2)
    lock = Lock()
    sessions = []
    threads = set()
    original_rule = webhooks.can_transition

    def synchronized_rule(source, target):
        assert source == "pending"
        with lock:
            threads.add(get_ident())
        barrier.wait(timeout=10)
        return original_rule(source, target)

    original_update = webhooks.update_payment_status

    def record_session(session, payment_id, target):
        with lock:
            sessions.append(session)
        return original_update(session, payment_id, target)

    monkeypatch.setattr(webhooks, "can_transition", synchronized_rule)
    monkeypatch.setattr(webhooks, "update_payment_status", record_session)
    with TestClient(application) as client:
        payment_id = create_payment(client)

        def send(target):
            return client.post(
                "/webhooks/bank", json={"payment_id": payment_id, "status": target}
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                target: executor.submit(send, target)
                for target in ("succeeded", "failed")
            }
            responses = {
                target: future.result(timeout=20) for target, future in futures.items()
            }
        assert sorted(response.status_code for response in responses.values()) == [
            200,
            409,
        ]
        winner = next(
            target
            for target, response in responses.items()
            if response.status_code == 200
        )
        for response in responses.values():
            assert response.json() == (
                {"result": "ok"}
                if response.status_code == 200
                else {"error": "invalid_transition"}
            )
        assert len(threads) == 2
        assert len(sessions) == 2 and sessions[0] is not sessions[1]
        assert all(session.is_active for session in sessions)
        with application.state.session_factory() as session:
            assert session.get(Payment, payment_id).status == winner
