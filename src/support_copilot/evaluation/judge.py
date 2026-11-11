import json
import os
from importlib.resources import files
from time import perf_counter
from typing import Literal

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from support_copilot.contracts import Answer, Passage, ProviderCall, Usage
from support_copilot.errors import CopilotError
from support_copilot.evaluation.dataset import Case
from support_copilot.guardrails import bounded_payload
from support_copilot.provider import provider_error


class JudgeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: str
    model: str = Field(min_length=1)
    reasoning_effort: str
    max_output_tokens: int = Field(ge=256)
    timeout_seconds: float = Field(gt=0)
    prompt_file: str = Field(pattern=r"^judge-v[0-9]+\.txt$")


class Assessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    score: Literal[0, 1, 2] | None
    rationale: str = Field(min_length=1)


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer_correctness: Assessment
    faithfulness: Assessment
    citation_support: Assessment
    response_appropriateness: Assessment


def load_judge_settings() -> JudgeSettings:
    data = json.loads(files("support_copilot").joinpath("config/judge-v1.json").read_text())
    if os.environ.get("COPILOT_JUDGE_MODEL"):
        data["model"] = os.environ["COPILOT_JUDGE_MODEL"]
    return JudgeSettings.model_validate(data)


def judge_prompt(settings: JudgeSettings) -> str:
    return files("support_copilot").joinpath(f"prompts/{settings.prompt_file}").read_text()


def judge_answer(
    client: OpenAI, case: Case, answer: Answer, gold: list[Passage], settings: JudgeSettings
) -> dict:
    started = perf_counter()
    result = {
        "status": "failed",
        "verdict": None,
        "provider_call": None,
        "error": None,
        "elapsed_ms": 0.0,
    }
    payload = {
        "question": case.question,
        "expected_status": case.expected_status,
        "answer_criteria": case.answer_criteria,
        "prohibited_claims": case.prohibited_claims,
        "reference_passages": [p.model_dump() for p in gold],
        "retrieved_passages": [p.model_dump() for p in answer.retrieved_passages],
        "candidate": answer.model_dump(exclude={"trace", "retrieved_passages"}),
    }
    try:
        response = client.responses.create(
            model=settings.model,
            instructions=judge_prompt(settings),
            input=bounded_payload(payload, limit=128000),
            store=False,
            reasoning={"effort": settings.reasoning_effort},
            max_output_tokens=settings.max_output_tokens,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "support_judge_v1",
                    "strict": True,
                    "schema": Verdict.model_json_schema(),
                }
            },
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
        result["provider_call"] = ProviderCall(
            operation="judge",
            requested_model=settings.model,
            returned_model=response.model,
            request_id=response._request_id,
            usage=usage,
        ).model_dump()
        if response.status != "completed":
            result["error"] = "judge_incomplete"
        elif not response.output_text:
            result["error"] = "judge_refusal_or_empty_output"
        else:
            verdict = Verdict.model_validate_json(response.output_text)
            applicable = {
                "answer_correctness": case.expected_status == "answered",
                "faithfulness": answer.status == "answered",
                "citation_support": answer.status == "answered",
                "response_appropriateness": True,
            }
            for name, required in applicable.items():
                if (getattr(verdict, name).score is not None) != required:
                    raise ValueError("Judge returned an invalid applicability decision")
            result.update(status="completed", verdict=verdict.model_dump())
    except CopilotError as error:
        result["error"] = "judge_" + error.code
    except OpenAIError as error:
        result["error"] = provider_error(error).code
    except (ValidationError, ValueError):
        result["error"] = "invalid_judge_output"
    result["elapsed_ms"] = round((perf_counter() - started) * 1000, 3)
    return result
