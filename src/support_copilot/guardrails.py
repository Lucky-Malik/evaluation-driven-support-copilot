import json

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from support_copilot.contracts import AnswerDraft, Citation, Passage
from support_copilot.errors import CopilotError

MAX_BODY_BYTES = 16384
MAX_GENERATION_BYTES = 64000


def bounded_payload(value: dict, limit: int = MAX_GENERATION_BYTES) -> str:
    payload = json.dumps(value, ensure_ascii=False)
    if len(payload.encode("utf-8")) > limit:
        raise CopilotError("context_too_large", "The evidence exceeds the request size limit.", 413)
    return payload


def validated_citations(draft: AnswerDraft, passages: list[Passage]) -> list[Citation]:
    by_id = {passage.chunk_id: passage for passage in passages}
    if any(chunk_id not in by_id for chunk_id in draft.citation_ids):
        raise CopilotError(
            "invalid_citation", "Provider cited evidence that was not retrieved.", 502
        )
    return [
        Citation(
            chunk_id=item.chunk_id,
            source_url=item.source_url,
            title=item.title,
            section=item.section,
        )
        for item in (by_id[key] for key in dict.fromkeys(draft.citation_ids))
    ]


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                response = JSONResponse(status_code=413, content={"error": "request_too_large"})
                await response(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay() -> dict:
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)
