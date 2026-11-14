from uuid import uuid4

import psycopg
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from openai import OpenAI, OpenAIError

from support_copilot.contracts import Answer, Question
from support_copilot.db import check_ready, database_url
from support_copilot.errors import CopilotError
from support_copilot.events import configure_logging, emit
from support_copilot.guardrails import BodyLimitMiddleware
from support_copilot.provider import provider_error
from support_copilot.rag import answer_question
from support_copilot.settings import api_key, load_settings

configure_logging()
app = FastAPI(title="Evaluation-Driven Technical Support Copilot", version="0.5.0")
app.add_middleware(BodyLimitMiddleware)


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


@app.post("/ask", response_model=Answer)
def ask(question: Question) -> JSONResponse:
    request_id = str(uuid4())
    try:
        settings = load_settings()
        with OpenAI(api_key=api_key(), timeout=settings.timeout_seconds, max_retries=0) as client:
            answer = answer_question(
                question.question, settings, database_url(), client, request_id
            )
        return JSONResponse(content=answer.model_dump(), headers={"X-Request-ID": request_id})
    except (CopilotError, OpenAIError, ValueError) as error:
        if isinstance(error, CopilotError):
            failure = error
        elif isinstance(error, OpenAIError):
            failure = provider_error(error)
        else:
            failure = CopilotError(
                "invalid_configuration", "Check the server's model and database configuration."
            )
        emit("request_failed", request_id=request_id, error_code=failure.code)
        return JSONResponse(
            status_code=failure.status_code,
            headers={"X-Request-ID": request_id},
            content={
                "error": {"code": failure.code, "message": failure.message},
                "request_id": request_id,
                "trace": failure.trace,
            },
        )
