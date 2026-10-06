import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import create_db_engine, create_session_factory


def create_app(database_url: str | None = None) -> FastAPI:
    url = (
        database_url
        if database_url is not None
        else os.environ.get("DATABASE_URL", "sqlite:///./kvitto.db")
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        engine = create_db_engine(url)
        application.state.engine = engine
        application.state.session_factory = create_session_factory(engine)
        try:
            yield
        finally:
            engine.dispose()

    return FastAPI(title="Kvitto Payments API", lifespan=lifespan)


app = create_app()
