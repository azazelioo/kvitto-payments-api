import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Tariff

DEFAULT_TARIFFS = (("basic", 990000), ("standard", 1990000), ("premium", 2990000))
router = APIRouter()


class TariffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    price: int


def seed_tariffs(session: Session) -> None:
    for title, price in DEFAULT_TARIFFS:
        if session.scalar(select(Tariff.id).where(Tariff.title == title)) is not None:
            continue
        session.add(Tariff(title=title, price=price))
        try:
            session.commit()
        except IntegrityError as error:
            session.rollback()
            original = error.orig
            sqlite_title_conflict = (
                isinstance(original, sqlite3.IntegrityError)
                and original.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE
                and str(original) == "UNIQUE constraint failed: tariffs.title"
            )
            diagnostic = getattr(original, "diag", None)
            postgres_title_conflict = (
                getattr(diagnostic, "constraint_name", None) == "uq_tariffs_title"
            )
            if not (sqlite_title_conflict or postgres_title_conflict):
                raise
            if session.scalar(select(Tariff.id).where(Tariff.title == title)) is None:
                raise


@router.get("/tariffs", response_model=list[TariffResponse])
def get_tariffs(session: Annotated[Session, Depends(get_session)]) -> list[Tariff]:
    return list(session.scalars(select(Tariff).order_by(Tariff.id)))
