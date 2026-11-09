import json
import math
from dataclasses import dataclass

from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    OpenAIError,
    RateLimitError,
)

from support_copilot.contracts import AnswerDraft, Passage, ProviderCall, Usage
from support_copilot.errors import CopilotError
from support_copilot.settings import Settings


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    call: ProviderCall


@dataclass(frozen=True)
class GenerationResult:
    draft: AnswerDraft | None
    call: ProviderCall
    failure: str | None


def validate_vector(vector: list[float], dimensions: int) -> None:
    if len(vector) != dimensions or not all(math.isfinite(v) and abs(v) <= 3e38 for v in vector):
        raise CopilotError("invalid_embedding", "Provider returned an invalid embedding.", 502)
    if not any(abs(v) >= 1e-38 for v in vector):
        raise CopilotError("invalid_embedding", "Provider returned a zero embedding.", 502)


def embed(client: OpenAI, texts: list[str], settings: Settings) -> EmbeddingResult:
    response = client.embeddings.create(
        model=settings.embedding_model,
        input=texts,
        dimensions=settings.embedding_dimensions,
        encoding_format="float",
    )
    ordered = sorted(response.data, key=lambda item: item.index)
    if [item.index for item in ordered] != list(range(len(texts))):
        raise CopilotError(
            "invalid_embedding", "Provider returned an incomplete embedding batch.", 502
        )
    vectors = [item.embedding for item in ordered]
    for vector in vectors:
        validate_vector(vector, settings.embedding_dimensions)
    usage = None
    if response.usage is not None:
        usage = Usage(
            input_tokens=response.usage.prompt_tokens,
            output_tokens=0,
            total_tokens=response.usage.total_tokens,
        )
    call = ProviderCall(
        operation="embedding",
        requested_model=settings.embedding_model,
        returned_model=response.model,
        request_id=response._request_id,
        usage=usage,
    )
    return EmbeddingResult(vectors, call)


def generate(
    client: OpenAI,
    question: str,
    passages: list[Passage],
    settings: Settings,
    prompt: str,
) -> GenerationResult:
    evidence = [
        {
            "chunk_id": item.chunk_id,
            "title": item.title,
            "section": item.section,
            "content": item.content,
        }
        for item in passages
    ]
    response = client.responses.parse(
        model=settings.generation_model,
        instructions=prompt,
        input=json.dumps({"question": question, "evidence": evidence}, ensure_ascii=False),
        text_format=AnswerDraft,
        reasoning={"effort": settings.reasoning_effort},
        max_output_tokens=settings.max_output_tokens,
        store=False,
    )
    usage = None
    if response.usage is not None:
        usage = Usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=response.usage.total_tokens,
            cached_input_tokens=response.usage.input_tokens_details.cached_tokens,
            reasoning_tokens=response.usage.output_tokens_details.reasoning_tokens,
        )
    call = ProviderCall(
        operation="generation",
        requested_model=settings.generation_model,
        returned_model=response.model,
        request_id=response._request_id,
        usage=usage,
    )
    if response.status != "completed":
        return GenerationResult(None, call, "provider_incomplete")
    if response.output_parsed is None:
        return GenerationResult(None, call, "provider_refusal_or_empty_output")
    return GenerationResult(response.output_parsed, call, None)


def provider_error(error: OpenAIError) -> CopilotError:
    if isinstance(error, APITimeoutError):
        return CopilotError(
            "provider_timeout", "The model provider timed out. Try again later.", 504
        )
    if isinstance(error, AuthenticationError):
        return CopilotError("provider_authentication", "Check the server's OpenAI API credentials.")
    if isinstance(error, RateLimitError):
        return CopilotError(
            "provider_rate_limit", "OpenAI rate or quota limit reached. Check billing."
        )
    if isinstance(error, APIConnectionError):
        return CopilotError("provider_connection", "Could not reach the model provider.")
    return CopilotError("provider_error", "The model provider could not complete the request.", 502)
