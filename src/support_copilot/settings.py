import json
import os
from importlib.resources import files
from typing import Literal, Self

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, model_validator

from support_copilot.corpus import sha256
from support_copilot.errors import CopilotError


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    pipeline_version: str
    snapshot_id: str
    embedding_model: str = Field(min_length=1)
    embedding_dimensions: int = Field(ge=1, le=2000)
    generation_model: str = Field(min_length=1)
    reasoning_effort: str
    top_k: int = Field(ge=1, le=20)
    max_output_tokens: int = Field(ge=256)
    timeout_seconds: float = Field(gt=0)
    embedding_batch_size: int = Field(ge=1, le=64)
    prompt_file: str = Field(pattern=r"^answer-v[0-9]+\.txt$")
    retrieval_mode: Literal["vector", "keyword", "hybrid"] = "vector"
    retrieval_version: str = "postgres-english-or-rrf-v1"
    candidate_k: int = Field(default=20, ge=1, le=100)
    rrf_k: int = Field(default=60, ge=1, le=1000)
    section_filter: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def candidate_budget(self) -> Self:
        if self.retrieval_mode == "hybrid" and self.candidate_k < self.top_k:
            raise ValueError("Hybrid candidate_k must be at least top_k")
        return self


def load_settings() -> Settings:
    load_dotenv()
    raw = files("support_copilot").joinpath("config/baseline-v1.json").read_text()
    data = json.loads(raw)
    data.update(
        json.loads(files("support_copilot").joinpath("config/retrieval-v1.json").read_text())
    )
    for field in (
        "generation_model",
        "embedding_model",
        "embedding_dimensions",
        "top_k",
        "retrieval_mode",
        "candidate_k",
        "rrf_k",
        "snapshot_id",
        "section_filter",
    ):
        value = os.environ.get(f"COPILOT_{field.upper()}")
        if value is not None:
            data[field] = value
    if data.get("retrieval_mode", "vector") != "vector":
        data["pipeline_version"] = f"{data['retrieval_mode']}-retrieval-v1"
    return Settings.model_validate(data)


def load_prompt(settings: Settings) -> str:
    return files("support_copilot").joinpath(f"prompts/{settings.prompt_file}").read_text()


def config_hash(settings: Settings) -> str:
    return sha256(json.dumps(settings.model_dump(), sort_keys=True).encode())


def api_key() -> str:
    load_dotenv()
    value = os.environ.get("OPENAI_API_KEY", "").strip()
    if not value:
        raise CopilotError(
            "missing_api_key", "Set OPENAI_API_KEY on the server to enable paid calls."
        )
    return value
