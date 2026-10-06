import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import create_db_engine, create_session_factory
from app.payments import router as payments_router
from app.tariffs import router as tariffs_router
from app.tariffs import seed_tariffs
from app.webhooks import router as webhooks_router


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
            with application.state.session_factory() as session:
                seed_tariffs(session)
            yield
        finally:
            engine.dispose()

    application = FastAPI(title="Kvitto Payments API", lifespan=lifespan)
    application.include_router(tariffs_router)
    application.include_router(payments_router)
    application.include_router(webhooks_router)
    return application


app = create_app()
