from fastapi import FastAPI


def create_app() -> FastAPI:
    return FastAPI(title="Kvitto Payments API")


app = create_app()
