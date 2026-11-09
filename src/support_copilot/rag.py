from time import perf_counter

import psycopg
from openai import OpenAI, OpenAIError
from pydantic import ValidationError

from support_copilot.contracts import Answer, AnswerDraft, Citation, Trace
from support_copilot.corpus import sha256
from support_copilot.errors import CopilotError
from support_copilot.events import emit
from support_copilot.provider import embed, generate, provider_error
from support_copilot.retrieval import corpus_status, retrieve
from support_copilot.settings import Settings, config_hash, load_prompt


def answer_question(
    question: str,
    settings: Settings,
    url: str,
    client: OpenAI,
    request_id: str,
) -> Answer:
    started = perf_counter()
    stage_started = started
    stage = "corpus_check"
    prompt = load_prompt(settings)
    trace = Trace(
        request_id=request_id,
        pipeline_version=settings.pipeline_version,
        config_sha256=config_hash(settings),
        prompt_version=settings.prompt_file,
        prompt_sha256=sha256(prompt.encode()),
        snapshot_id=settings.snapshot_id,
        snapshot_hash=None,
        embedding_model=settings.embedding_model,
        embedding_dimensions=settings.embedding_dimensions,
        generation_model=settings.generation_model,
        top_k=settings.top_k,
        reasoning_effort=settings.reasoning_effort,
        max_output_tokens=settings.max_output_tokens,
        timings_ms={},
        provider_calls=[],
    )
    try:
        status = corpus_status(url, settings)
        trace.snapshot_hash = status["snapshot_hash"]
        if not status["ready"]:
            raise CopilotError(
                "corpus_not_ready", "Ingest and embed every chunk of the configured snapshot first."
            )
        trace.timings_ms[stage] = round((perf_counter() - stage_started) * 1000, 3)
        stage, stage_started = "query_embedding", perf_counter()
        embedding = embed(client, [question], settings)
        trace.provider_calls.append(embedding.call)
        trace.timings_ms[stage] = round((perf_counter() - stage_started) * 1000, 3)
        stage, stage_started = "retrieval", perf_counter()
        passages = retrieve(url, embedding.vectors[0], settings)
        trace.timings_ms[stage] = round((perf_counter() - stage_started) * 1000, 3)
        stage, stage_started = "generation", perf_counter()
        if passages:
            generation = generate(client, question, passages, settings, prompt)
            trace.provider_calls.append(generation.call)
            if generation.failure:
                raise CopilotError(
                    generation.failure,
                    "Provider did not return a complete answer. Retry or adjust the output budget.",
                    502,
                )
            draft = generation.draft
        else:
            draft = AnswerDraft(
                status="insufficient_evidence",
                answer=None,
                clarification_question=None,
                citation_ids=[],
                reason="No passages were retrieved from the configured corpus.",
            )
        trace.timings_ms[stage] = round((perf_counter() - stage_started) * 1000, 3)
        stage, stage_started = "citation_check", perf_counter()
        if draft is None:
            raise CopilotError(
                "invalid_provider_output", "Provider returned no structured answer.", 502
            )
        by_id = {passage.chunk_id: passage for passage in passages}
        if any(chunk_id not in by_id for chunk_id in draft.citation_ids):
            raise CopilotError(
                "invalid_citation", "Provider cited evidence that was not retrieved.", 502
            )
        citations = [
            Citation(
                chunk_id=item.chunk_id,
                source_url=item.source_url,
                title=item.title,
                section=item.section,
            )
            for item in (by_id[key] for key in dict.fromkeys(draft.citation_ids))
        ]
        trace.timings_ms[stage] = round((perf_counter() - stage_started) * 1000, 3)
        trace.timings_ms["total"] = round((perf_counter() - started) * 1000, 3)
        emit(
            "answer_completed",
            request_id=request_id,
            status=draft.status,
            retrieved_chunks=len(passages),
            total_ms=trace.timings_ms["total"],
        )
        return Answer(
            status=draft.status,
            answer=draft.answer,
            clarification_question=draft.clarification_question,
            reason=draft.reason,
            citations=citations,
            retrieved_passages=passages,
            trace=trace,
        )
    except (CopilotError, OpenAIError, psycopg.Error, ValidationError) as error:
        if isinstance(error, CopilotError):
            failure = error
        elif isinstance(error, OpenAIError):
            failure = provider_error(error)
        elif isinstance(error, psycopg.Error):
            failure = CopilotError(
                "database_unavailable",
                "Database operation failed. Check readiness and schema initialization.",
            )
        else:
            failure = CopilotError(
                "invalid_provider_output", "Provider returned an invalid structured response.", 502
            )
        trace.timings_ms[stage] = round((perf_counter() - stage_started) * 1000, 3)
        trace.timings_ms["total"] = round((perf_counter() - started) * 1000, 3)
        failure.trace = trace.model_dump()
        emit("answer_failed", request_id=request_id, stage=stage, error_code=failure.code)
        raise failure from None
