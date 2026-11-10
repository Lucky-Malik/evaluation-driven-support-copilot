from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from support_copilot.evaluation.artifacts import json_hash, read_run, write_json


class ReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: str
    result_sha256: str
    result: dict
    decision: Literal["pending", "agree", "disagree", "unable_to_assess"]
    notes: str


class ReviewPacket(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    format_version: Literal[1]
    run_id: str
    seed: int
    reviewer: str
    instructions: str
    items: list[ReviewItem]


def prepare_review(run_folder: Path, output: Path, count: int, seed: int) -> dict:
    if count < 1 or output.exists():
        raise ValueError("Use a positive sample size and a new review packet filename")
    manifest, records = read_run(run_folder)
    buckets = {}
    for record in records:
        if record["judge"]["status"] == "completed":
            buckets.setdefault(record["case"]["category"], []).append(record)
    for bucket in buckets.values():
        bucket.sort(key=lambda record: json_hash([seed, record["case"]["id"]]))
    selected = []
    while len(selected) < count and any(buckets.values()):
        for category in sorted(buckets):
            if buckets[category] and len(selected) < count:
                selected.append(buckets[category].pop(0))
    if not selected:
        raise ValueError("This run has no successful judge decisions to review")
    packet = {
        "format_version": 1,
        "run_id": manifest["run_id"],
        "seed": seed,
        "reviewer": "",
        "instructions": (
            "Read each result, set decision to agree, disagree, or unable_to_assess, "
            "and add notes. Pending items are not recorded."
        ),
        "items": [
            {
                "case_id": record["case"]["id"],
                "result_sha256": json_hash(record),
                "result": record,
                "decision": "pending",
                "notes": "",
            }
            for record in selected
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, packet)
    return {"packet": str(output), "sampled": len(selected), "reviewed": 0}


def record_review(run_folder: Path, packet_path: Path) -> dict:
    manifest, results = read_run(run_folder)
    by_id = {record["case"]["id"]: record for record in results}
    packet = ReviewPacket.model_validate_json(packet_path.read_text()).model_dump()
    if packet["format_version"] != 1 or packet["run_id"] != manifest["run_id"]:
        raise ValueError("Review packet belongs to a different run")
    reviewer = packet["reviewer"].strip()
    if not reviewer:
        raise ValueError("An identified reviewer must supply the decisions")
    submitted = []
    seen = set()
    for item in packet["items"]:
        case_id = item["case_id"]
        if case_id in seen or case_id not in by_id:
            raise ValueError("Duplicate or unknown review case")
        seen.add(case_id)
        original = by_id[case_id]
        if item["result_sha256"] != json_hash(original) or item["result"] != original:
            raise ValueError("Review context was changed; edit only decisions and notes")
        if original["judge"]["status"] != "completed":
            raise ValueError("Only completed judge decisions can be reviewed")
        decision = item["decision"]
        if decision not in {"pending", "agree", "disagree", "unable_to_assess"}:
            raise ValueError("Unknown review decision")
        if decision == "pending":
            continue
        if decision != "agree" and not item["notes"].strip():
            raise ValueError("Disagreement or uncertainty needs a note explaining why")
        submitted.append(
            {
                "case_id": case_id,
                "result_sha256": item["result_sha256"],
                "decision": decision,
                "notes": item["notes"],
            }
        )
    if not submitted:
        raise ValueError("No completed review decisions were supplied")
    review = {
        "format_version": 1,
        "run_id": manifest["run_id"],
        "reviewer": reviewer,
        "recorded_at": datetime.now(UTC).isoformat(),
        "decisions": submitted,
        "scope": "judge_decisions_not_dataset_label_review",
    }
    directory = run_folder / "reviews"
    directory.mkdir(exist_ok=True)
    destination = directory / f"{uuid4()}.json"
    write_json(destination, review)
    counts = Counter(item["decision"] for item in submitted)
    denominator = counts["agree"] + counts["disagree"]
    return {
        "review_file": str(destination),
        "counts": dict(counts),
        "agreement_rate": counts["agree"] / denominator if denominator else None,
        "agreement_denominator": denominator,
        "note": "Describes this submitted sample only.",
    }
