import json
import os
from importlib.resources import files

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

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


def load_settings() -> Settings:
    load_dotenv()
    raw = files("support_copilot").joinpath("config/baseline-v1.json").read_text()
    data = json.loads(raw)
    for field in ("generation_model", "embedding_model", "embedding_dimensions", "top_k"):
        value = os.environ.get(f"COPILOT_{field.upper()}")
        if value is not None:
            data[field] = value
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
