from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base, create_db_engine, create_session_factory
from app.models import Payment, Tariff


@pytest.fixture
def migration_config(tmp_path: Path) -> Config:
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'schema.db'}")
    return config


def test_migration_lifecycle(migration_config: Config, tmp_path: Path, monkeypatch):
    # Explicit Config URL must take precedence over the environment URL.
    other = tmp_path / "unused.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{other}")
    engine = create_db_engine(migration_config.get_main_option("sqlalchemy.url"))
    try:
        command.upgrade(migration_config, "head")
        command.upgrade(migration_config, "head")
        assert set(inspect(engine).get_table_names()) == {
            "tariffs",
            "payments",
            "alembic_version",
        }
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
                == "0001"
            )
            assert (
                connection.execute(text("SELECT count(*) FROM tariffs")).scalar_one()
                == 0
            )
        command.downgrade(migration_config, "base")
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}
        command.upgrade(migration_config, "head")
        command.check(migration_config)
        inspector = inspect(engine)
        for name, table in Base.metadata.tables.items():
            actual_checks = {
                item["name"]: item["sqltext"]
                for item in inspector.get_check_constraints(name)
            }
            expected_checks = {
                constraint.name: str(constraint.sqltext)
                for constraint in table.constraints
                if hasattr(constraint, "sqltext")
            }
            assert actual_checks == expected_checks
            assert {
                item["name"] for item in inspector.get_unique_constraints(name)
            } == {
                constraint.name
                for constraint in table.constraints
                if constraint.__class__.__name__ == "UniqueConstraint"
            }
        assert inspector.get_foreign_keys("payments")[0]["referred_table"] == "tariffs"
        assert not other.exists()
    finally:
        engine.dispose()


@pytest.fixture
def session(migration_config: Config) -> Iterator[Session]:
    command.upgrade(migration_config, "head")
    engine = create_db_engine(migration_config.get_main_option("sqlalchemy.url"))
    try:
        with create_session_factory(engine)() as session:
            session.add(Tariff(id=1, title="test", price=100))
            session.commit()
            yield session
    finally:
        engine.dispose()


def payment(**overrides) -> Payment:
    values = dict(tariff_id=1, email="test@example.com", amount=100, method="card")
    values.update(overrides)
    return Payment(**values)


@pytest.mark.parametrize(
    "values",
    [
        {"tariff_id": 999},
        {"amount": 0},
        {"amount": -1},
        {"discount": -1},
        {"status": "unknown"},
        {"method": "unknown"},
        {"method": "installment", "installment_months": None},
        {"method": "installment", "installment_months": 0},
        {"method": "installment", "installment_months": 4},
        {"method": "card", "installment_months": 3},
        {"method": "sbp", "installment_months": 6},
    ],
)
def test_invalid_payment(session: Session, values: dict) -> None:
    session.add(payment(**values))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    assert session.scalars(select(Payment)).all() == []


@pytest.mark.parametrize("price", [0, -1])
def test_invalid_tariff_price(session: Session, price: int) -> None:
    session.add(Tariff(title="invalid", price=price))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    assert len(session.scalars(select(Tariff)).all()) == 1


def test_duplicate_key(session: Session) -> None:
    first = payment(idempotency_key="same")
    session.add(first)
    session.commit()
    first_id = first.id
    session.add(payment(idempotency_key="same"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    assert [item.id for item in session.scalars(select(Payment))] == [first_id]


def test_null_keys(session: Session) -> None:
    session.add_all([payment(), payment()])
    session.commit()
    payments = session.scalars(select(Payment)).all()
    assert len(payments) == 2
    assert all(item.idempotency_key is None for item in payments)


@pytest.mark.parametrize("months", [3, 6, 12])
def test_valid_installment(session: Session, months: int) -> None:
    item = payment(method="installment", installment_months=months)
    session.add(item)
    session.commit()
    session.refresh(item)
    assert item.installment_months == months
