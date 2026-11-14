import json
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from time import perf_counter
from uuid import uuid4

from openai import OpenAI

from support_copilot import db
from support_copilot.contracts import Passage
from support_copilot.corpus import sha256
from support_copilot.errors import CopilotError
from support_copilot.evaluation.artifacts import (
    environment_identity,
    json_hash,
    read_run,
    write_json,
)
from support_copilot.evaluation.dataset import Case, load_dataset
from support_copilot.evaluation.judge import JudgeSettings, judge_answer, judge_prompt
from support_copilot.evaluation.metrics import METRICS_VERSION, deterministic_scores, summarize
from support_copilot.events import emit
from support_copilot.rag import answer_question
from support_copilot.retrieval import corpus_status
from support_copilot.settings import Settings, config_hash, load_prompt


def verify_database(
    url: str, settings: Settings, passages: dict[str, Passage], snapshot_hash: str
) -> None:
    status = corpus_status(url, settings)
    if not status["ready"] or status["snapshot_hash"] != snapshot_hash:
        raise CopilotError(
            "corpus_not_ready", "Ingest and embed the dataset's exact snapshot first."
        )
    with db.connect(url) as connection:
        rows = connection.execute(
            """SELECT c.id, c.content_sha256, c.content FROM chunks c
               JOIN documents d ON d.id = c.document_id WHERE d.snapshot_id = %s""",
            (settings.snapshot_id,),
        ).fetchall()
    actual = {row[0]: (row[1], row[2]) for row in rows}
    expected = {key: (value.content_sha256, value.content) for key, value in passages.items()}
    if actual != expected:
        raise ValueError("Stored corpus differs from the dataset's pinned local evidence")


def evaluate_case(
    case: Case,
    passages: dict[str, Passage],
    settings: Settings,
    judge: JudgeSettings,
    url: str,
    client: OpenAI,
    judge_client: OpenAI,
) -> dict:
    started = perf_counter()
    answer = None
    application = {
        "status": "completed",
        "answer": None,
        "error": None,
        "trace": None,
        "raw_candidate": None,
        "retrieved_passages": [],
        "retrieval_completed": False,
        "elapsed_ms": 0.0,
    }
    try:
        answer = answer_question(case.question, settings, url, client, str(uuid4()))
        application.update(
            answer=answer.model_dump(),
            trace=answer.trace.model_dump(),
            retrieved_passages=[p.model_dump() for p in answer.retrieved_passages],
            retrieval_completed=True,
        )
    except CopilotError as error:
        application.update(
            status="error",
            error={"code": error.code, "message": error.message},
            trace=error.trace,
            retrieved_passages=error.retrieved_passages,
            retrieval_completed=error.retrieval_completed,
            raw_candidate=error.candidate_draft,
        )
    application["elapsed_ms"] = round((perf_counter() - started) * 1000, 3)
    retrieved = [Passage.model_validate(p) for p in application["retrieved_passages"]]
    scores = deterministic_scores(
        case, answer, retrieved, application["retrieval_completed"], settings.top_k
    )
    gold = [passages[item.chunk_id] for item in case.evidence]
    judgment = {
        "status": "not_run",
        "verdict": None,
        "provider_call": None,
        "error": "application_error",
        "elapsed_ms": 0.0,
    }
    if answer is not None:
        judgment = judge_answer(judge_client, case, answer, gold, judge)
    for name in (
        "answer_correctness",
        "faithfulness",
        "citation_support",
        "response_appropriateness",
    ):
        value = judgment["verdict"][name]["score"] if judgment["verdict"] else None
        scores[name] = value / 2 if value is not None else None
    tags = []
    if application["error"]:
        tags.append("application:" + application["error"]["code"])
    if judgment["status"] == "failed":
        tags.append("judge:" + judgment["error"])
    tags.extend(name for name, value in scores.items() if value is not None and value < 1)
    return {
        "case": case.model_dump(mode="json"),
        "gold_passages": [p.model_dump() for p in gold],
        "application": application,
        "judge": judgment,
        "scores": scores,
        "failure_tags": tags,
    }


def run_evaluation(
    dataset: Path,
    snapshot: Path,
    output: Path,
    split: str,
    limit: int | None,
    settings: Settings,
    judge: JudgeSettings,
    url: str,
    client: OpenAI,
    judge_client: OpenAI,
) -> dict:
    manifest, all_cases, passages, dataset_hash = load_dataset(dataset, snapshot)
    if settings.snapshot_id != manifest.snapshot_id or split not in {"dev", "test"}:
        raise ValueError("Evaluation settings must select the dataset's corpus and a valid split")
    if limit is not None and limit < 1:
        raise ValueError("Case limit must be positive")
    cases = [case for case in all_cases if case.split == split][:limit]
    if not cases or len(cases) > 100:
        raise ValueError("Select between 1 and 100 cases per run")
    if output.exists():
        raise ValueError("Run output directory already exists; choose a new directory")
    verify_database(url, settings, passages, manifest.snapshot_hash)
    output.mkdir(parents=True, exist_ok=False)
    prompt = load_prompt(settings)
    rubric = judge_prompt(judge)
    run = {
        "format_version": 1,
        "kind": "live_evaluation",
        "run_id": str(uuid4()),
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "dataset_id": manifest.dataset_id,
        "dataset_sha256": dataset_hash,
        "split": split,
        "case_ids": [case.id for case in cases],
        "snapshot_id": manifest.snapshot_id,
        "snapshot_hash": manifest.snapshot_hash,
        "metrics_version": METRICS_VERSION,
        "relevance_unit": "chunk",
        "k": settings.top_k,
        "application_settings": settings.model_dump(),
        "config_sha256": config_hash(settings),
        "prompt_sha256": sha256(prompt.encode()),
        "judge_settings": judge.model_dump(),
        "judge_config_sha256": json_hash(judge.model_dump()),
        "judge_prompt_sha256": sha256(rubric.encode()),
        "environment": environment_identity(),
    }
    write_json(output / "run.json", run)
    write_json(output / "selected_cases.json", [case.model_dump(mode="json") for case in cases])
    write_json(output / "dataset_manifest.json", manifest.model_dump())
    (output / "answer_prompt.txt").write_text(prompt)
    (output / "judge_prompt.txt").write_text(rubric)
    records = []
    completed = False
    try:
        with (output / "cases.jsonl").open("x") as stream:
            for case in cases:
                record = evaluate_case(case, passages, settings, judge, url, client, judge_client)
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
                records.append(record)
                emit(
                    "evaluation_case_completed",
                    run_id=run["run_id"],
                    case_id=case.id,
                    application_status=record["application"]["status"],
                    judge_status=record["judge"]["status"],
                )
        completed = True
    finally:
        summary = summarize(records)
        write_json(output / "summary.json", summary)
        run.update(
            status="completed" if completed else "interrupted",
            completed_cases=len(records),
            finished_at=datetime.now(UTC).isoformat(),
            results_sha256=sha256((output / "cases.jsonl").read_bytes()),
        )
        write_json(output / "run.json", run)
    return {"run_directory": str(output), "run_id": run["run_id"], **summary}


def compare_runs(left: Path, right: Path) -> dict:
    left_meta, left_records = read_run(left)
    right_meta, right_records = read_run(right)
    for field in (
        "dataset_sha256",
        "snapshot_hash",
        "split",
        "case_ids",
        "metrics_version",
        "k",
        "judge_config_sha256",
        "judge_prompt_sha256",
    ):
        if left_meta[field] != right_meta[field]:
            raise ValueError(f"Cannot compare runs with different {field}")
    pairs = {}
    for metric in left_records[0]["scores"]:
        values = [
            (a["scores"][metric], b["scores"][metric])
            for a, b in zip(left_records, right_records, strict=True)
            if a["scores"][metric] is not None and b["scores"][metric] is not None
        ]
        pairs[metric] = {
            "n_pairs": len(values),
            "left_mean": mean(a for a, _ in values) if values else None,
            "right_mean": mean(b for _, b in values) if values else None,
            "delta": mean(b - a for a, b in values) if values else None,
        }
    return {
        "left_run": left_meta["run_id"],
        "right_run": right_meta["run_id"],
        "left_settings": left_meta["application_settings"],
        "right_settings": right_meta["application_settings"],
        "paired_metrics": pairs,
        "left_summary": summarize(left_records),
        "right_summary": summarize(right_records),
        "note": "Positive metric deltas favor the right run; these are not significance tests.",
    }
