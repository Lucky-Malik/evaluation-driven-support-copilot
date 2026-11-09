import psycopg
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from support_copilot.db import check_ready, database_url
from support_copilot.events import configure_logging, emit

configure_logging()
app = FastAPI(title="Evaluation-Driven Technical Support Copilot", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def readiness() -> JSONResponse:
    try:
        check_ready(database_url())
    except (psycopg.Error, ValueError) as error:
        emit("database_not_ready", error_type=type(error).__name__)
        return JSONResponse(status_code=503, content={"status": "not_ready"})
    return JSONResponse(content={"status": "ready"})
