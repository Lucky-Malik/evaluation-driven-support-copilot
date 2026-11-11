from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=4000)


class AnswerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["answered", "needs_clarification", "insufficient_evidence"]
    answer: str | None
    clarification_question: str | None
    citation_ids: list[str]
    reason: str

    @model_validator(mode="after")
    def consistent_outcome(self) -> Self:
        if not self.reason.strip():
            raise ValueError("An outcome needs a reason")
        if self.status == "answered":
            if not self.answer or not self.answer.strip() or not self.citation_ids:
                raise ValueError("An answer needs text and citations")
            if self.clarification_question is not None:
                raise ValueError("An answer cannot also ask for clarification")
        else:
            if self.answer is not None or self.citation_ids:
                raise ValueError("Non-answer outcomes cannot include answers or citations")
            if self.status == "needs_clarification":
                if not self.clarification_question or not self.clarification_question.strip():
                    raise ValueError("Clarification needs a question")
            elif self.clarification_question is not None:
                raise ValueError("Insufficient evidence cannot also ask for clarification")
        return self


class Passage(BaseModel):
    chunk_id: str
    document_id: str
    source_url: str
    title: str
    section: str
    snapshot_id: str
    content_sha256: str
    content: str
    cosine_distance: float | None = None
    keyword_score: float | None = None
    rrf_score: float | None = None
    vector_rank: int | None = None
    keyword_rank: int | None = None


class Citation(BaseModel):
    chunk_id: str
    source_url: str
    title: str
    section: str


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None


class ProviderCall(BaseModel):
    operation: Literal["embedding", "generation", "judge"]
    requested_model: str
    returned_model: str | None
    request_id: str | None
    usage: Usage | None


class Cost(BaseModel):
    status: Literal["unavailable"] = "unavailable"
    estimated_usd: float | None = None
    reason: str = (
        "No verified pricing configuration is enabled. Token usage is reported separately."
    )


class Trace(BaseModel):
    request_id: str
    pipeline_version: str
    config_sha256: str
    prompt_version: str
    prompt_sha256: str
    snapshot_id: str
    snapshot_hash: str | None
    embedding_model: str
    embedding_dimensions: int
    generation_model: str
    top_k: int
    reasoning_effort: str
    max_output_tokens: int
    timings_ms: dict[str, float]
    provider_calls: list[ProviderCall]
    retrieval_mode: Literal["vector", "keyword", "hybrid"] = "vector"
    candidate_k: int = 20
    rrf_k: int = 60
    section_filter: str | None = None
    cost: Cost = Field(default_factory=Cost)


class Answer(BaseModel):
    status: Literal["answered", "needs_clarification", "insufficient_evidence"]
    answer: str | None
    clarification_question: str | None
    reason: str
    citations: list[Citation]
    retrieved_passages: list[Passage]
    trace: Trace
