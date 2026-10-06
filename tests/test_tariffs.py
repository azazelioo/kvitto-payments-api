import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError

from app.db import create_db_engine, create_session_factory
from app.main import create_app
from app.models import Tariff
from app.tariffs import seed_tariffs

EXPECTED = {"basic": 990000, "standard": 1990000, "premium": 2990000}


def test_startup_seeds_tariffs(database_url: str) -> None:
    application = create_app(database_url)
    with TestClient(application):
        with application.state.session_factory() as session:
            rows = session.scalars(select(Tariff)).all()
            assert len(rows) == 3
            assert {row.title: row.price for row in rows} == EXPECTED


def test_get_tariffs(database_url: str) -> None:
    with TestClient(create_app(database_url)) as client:
        response = client.get("/tariffs")
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 3
        assert all(set(row) == {"id", "title", "price"} for row in rows)
        assert all(type(row["price"]) is int for row in rows)
        assert {row["title"]: row["price"] for row in rows} == EXPECTED
        assert [row["id"] for row in rows] == sorted(row["id"] for row in rows)
        assert client.get("/tariffs").json() == rows


def test_repeated_startup(database_url: str) -> None:
    with TestClient(create_app(database_url)) as client:
        first = client.get("/tariffs").json()
    with TestClient(create_app(database_url)) as client:
        assert client.get("/tariffs").json() == first
        with client.app.state.session_factory() as session:
            assert len(session.scalars(select(Tariff)).all()) == 3


def test_existing_tariff_is_preserved(database_url: str) -> None:
    engine = create_db_engine(database_url)
    try:
        with create_session_factory(engine)() as session:
            session.add(Tariff(id=42, title="standard", price=123456))
            session.commit()
        with TestClient(create_app(database_url)) as client:
            rows = client.get("/tariffs").json()
            assert len(rows) == 3
            assert {row["title"]: row["price"] for row in rows} == {
                **EXPECTED,
                "standard": 123456,
            }
            assert next(row for row in rows if row["title"] == "standard")["id"] == 42
    finally:
        engine.dispose()


def test_insert_conflict_recovers(database_url: str) -> None:
    engine = create_db_engine(database_url)
    factory = create_session_factory(engine)
    try:
        with factory() as session:
            # Simulate another startup inserting after our lookup, before our INSERT.
            def competing_insert(session, flush_context, instances):
                with factory() as competitor:
                    competitor.add(Tariff(title="basic", price=111))
                    competitor.commit()

            event.listen(session, "before_flush", competing_insert, once=True)
            seed_tariffs(session)
            rows = session.scalars(select(Tariff)).all()
            assert len(rows) == 3
            assert {row.title: row.price for row in rows} == {**EXPECTED, "basic": 111}
    finally:
        engine.dispose()


def test_other_integrity_error_is_not_hidden(database_url: str) -> None:
    engine = create_db_engine(database_url)
    try:
        with create_session_factory(engine)() as session:

            def invalid_price(session, flush_context, instances):
                for item in session.new:
                    item.price = -1

            event.listen(session, "before_flush", invalid_price, once=True)
            with pytest.raises(IntegrityError, match="ck_tariffs_price_positive"):
                seed_tariffs(session)
            assert session.is_active
            assert session.scalars(select(Tariff)).all() == []
    finally:
        engine.dispose()
