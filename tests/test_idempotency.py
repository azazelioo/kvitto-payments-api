from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock, get_ident

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError

from app import payments
from app.main import create_app
from app.models import Payment


def body(**changes) -> dict:
    return {"tariff_id": 1, "email": "student@example.com", "method": "card", **changes}


def test_repeat_and_current_status(database_url: str) -> None:
    application = create_app(database_url)
    with TestClient(application) as client:
        headers = {"Idempotency-Key": "key"}
        first = client.post("/payments", json=body(), headers=headers)
        assert first.status_code == 201
        for payload in (
            body(),
            body(method="sbp", email="other@example.com"),
            body(tariff_id=999999),
        ):
            repeated = client.post("/payments", json=payload, headers=headers)
            assert repeated.status_code == 200
            assert repeated.json() == first.json()
        invalid = client.post("/payments", json=body(email="invalid"), headers=headers)
        assert invalid.status_code == 422
        assert isinstance(invalid.json()["detail"], list)
        with application.state.session_factory() as session:
            rows = session.scalars(select(Payment)).all()
            assert len(rows) == 1
            assert rows[0].idempotency_key == "key"
            rows[0].status = "succeeded"
            session.commit()
        current = client.post("/payments", json=body(), headers=headers)
        assert current.status_code == 200
        assert current.json()["id"] == first.json()["id"]
        assert current.json()["status"] == "succeeded"


def test_distinct_and_absent_keys(database_url: str) -> None:
    application = create_app(database_url)
    with TestClient(application) as client:
        responses = [
            client.post("/payments", json=body(), headers=headers)
            for headers in (
                {"Idempotency-Key": "key"},
                {"Idempotency-Key": "KEY"},
                {"Idempotency-Key": " key "},
                {},
                {},
            )
        ]
        assert all(response.status_code == 201 for response in responses)
        assert len({response.json()["id"] for response in responses}) == 5
        with application.state.session_factory() as session:
            rows = session.scalars(select(Payment).order_by(Payment.id)).all()
            assert [row.idempotency_key for row in rows] == [
                "key",
                "KEY",
                " key ",
                None,
                None,
            ]


@pytest.mark.parametrize("key", ["", " ", "   ", "\t"])
def test_blank_key(database_url: str, key: str) -> None:
    application = create_app(database_url)
    with TestClient(application) as client:
        response = client.post(
            "/payments", json=body(), headers={"Idempotency-Key": key}
        )
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["header", "Idempotency-Key"]
        with application.state.session_factory() as session:
            assert session.scalars(select(Payment)).all() == []


def test_concurrent_requests(database_url: str, monkeypatch) -> None:
    workers = 4
    start = Barrier(workers)
    looked_up = Barrier(workers)
    lock = Lock()
    sessions = []
    threads = set()
    conflicts = []
    original_lookup = payments.find_payment_by_key
    original_conflict = payments.is_key_conflict

    def synchronized_lookup(session, key):
        existing = original_lookup(session, key)
        with lock:
            first_lookup = session not in sessions
            if first_lookup:
                sessions.append(session)
                threads.add(get_ident())
        if first_lookup:
            assert existing is None
            looked_up.wait(timeout=10)
        return existing

    def record_conflict(error):
        result = original_conflict(error)
        with lock:
            conflicts.append(result)
        return result

    monkeypatch.setattr(payments, "find_payment_by_key", synchronized_lookup)
    monkeypatch.setattr(payments, "is_key_conflict", record_conflict)
    application = create_app(database_url)
    with TestClient(application) as client:

        def request():
            start.wait(timeout=10)
            return client.post(
                "/payments", json=body(), headers={"Idempotency-Key": "race"}
            )

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(request) for _ in range(workers)]
            responses = [future.result(timeout=20) for future in futures]
        assert sorted(response.status_code for response in responses) == [
            200,
            200,
            200,
            201,
        ]
        assert len({response.json()["id"] for response in responses}) == 1
        assert len(sessions) == workers
        assert len(threads) == workers
        assert conflicts == [True] * (workers - 1)
        with application.state.session_factory() as session:
            rows = session.scalars(select(Payment)).all()
            assert len(rows) == 1
            assert rows[0].idempotency_key == "race"


def test_other_integrity_error_propagates(database_url: str) -> None:
    application = create_app(database_url)
    with TestClient(application) as client:
        factory = application.state.session_factory
        sessions = []

        def invalid_amount(session, flush_context, instances):
            sessions.append(session)
            for item in session.new:
                if isinstance(item, Payment):
                    item.amount = -1

        event.listen(factory, "before_flush", invalid_amount)
        try:
            with pytest.raises(IntegrityError, match="ck_payments_amount_positive"):
                client.post(
                    "/payments", json=body(), headers={"Idempotency-Key": "key"}
                )
        finally:
            event.remove(factory, "before_flush", invalid_amount)
        assert sessions[0].is_active
        with factory() as session:
            assert session.scalars(select(Payment)).all() == []
