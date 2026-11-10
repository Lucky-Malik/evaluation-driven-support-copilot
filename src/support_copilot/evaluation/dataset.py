from collections import Counter
from datetime import date
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from support_copilot.contracts import Passage
from support_copilot.corpus import PIPELINE_VERSION, extract_html, make_chunks, sha256, stable_id
from support_copilot.snapshot import load_snapshot


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk_id: str
    quote: str = Field(min_length=1)


class LabelProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authored_by: Literal["agent", "user"]
    review_status: Literal["machine_generated", "agent_inspected", "user_reviewed"]
    reviewer: str | None
    reviewed_on: date | None
    note: str = Field(min_length=1)

    @model_validator(mode="after")
    def review_is_identified(self) -> Self:
        if self.review_status != "machine_generated" and (
            not self.reviewer or not self.reviewed_on
        ):
            raise ValueError("Inspected labels need an identified reviewer and date")
        return self


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    split: Literal["dev", "test"]
    category: Literal["ordinary", "exact_identifier", "ambiguity", "missing_evidence"]
    group_id: str
    question: str = Field(min_length=1)
    expected_status: Literal["answered", "needs_clarification", "insufficient_evidence"]
    evidence: list[Evidence]
    answer_criteria: list[str] = Field(min_length=1)
    prohibited_claims: list[str]
    provenance: LabelProvenance

    @model_validator(mode="after")
    def evidence_matches_outcome(self) -> Self:
        if (self.expected_status == "answered") != bool(self.evidence):
            raise ValueError("Only answered cases have positive retrieval labels")
        if len({item.chunk_id for item in self.evidence}) != len(self.evidence):
            raise ValueError("Duplicate labelled evidence")
        if any(not item.strip() for item in self.answer_criteria):
            raise ValueError("Answer criteria cannot be blank")
        return self


class DatasetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format_version: Literal[1]
    dataset_id: str
    snapshot_id: str
    snapshot_hash: str
    pipeline_version: str
    relevance_unit: Literal["chunk"]
    files: dict[str, str]


def corpus_passages(snapshot: Path) -> tuple[str, str, dict[str, Passage]]:
    manifest, raw_pages = load_snapshot(snapshot)
    passages = {}
    for page, raw in zip(manifest.pages, raw_pages, strict=True):
        _, sections = extract_html(raw)
        document_id = stable_id(manifest.snapshot_id, page.source_url)
        for chunk in make_chunks(document_id, sections):
            passages[chunk.id] = Passage(
                chunk_id=chunk.id,
                document_id=document_id,
                source_url=page.source_url + (f"#{chunk.anchor}" if chunk.anchor else ""),
                title=page.title,
                section=chunk.section,
                snapshot_id=manifest.snapshot_id,
                content_sha256=chunk.content_sha256,
                content=chunk.content,
                cosine_distance=0,
            )
    return manifest.snapshot_id, manifest.snapshot_hash, passages


def load_dataset(
    folder: Path, snapshot: Path
) -> tuple[DatasetManifest, list[Case], dict[str, Passage], str]:
    raw_manifest = (folder / "manifest.json").read_bytes()
    manifest = DatasetManifest.model_validate_json(raw_manifest)
    snapshot_id, snapshot_hash, passages = corpus_passages(snapshot)
    if (manifest.snapshot_id, manifest.snapshot_hash, manifest.pipeline_version) != (
        snapshot_id,
        snapshot_hash,
        PIPELINE_VERSION,
    ):
        raise ValueError("Dataset corpus or chunking version does not match the saved snapshot")
    if set(manifest.files) != {"dev.jsonl", "test.jsonl"}:
        raise ValueError("Dataset must contain dev.jsonl and test.jsonl")
    cases = []
    fingerprint_bytes = raw_manifest
    for name in ("dev.jsonl", "test.jsonl"):
        raw = (folder / name).read_bytes()
        if sha256(raw) != manifest.files[name]:
            raise ValueError(f"Dataset checksum mismatch: {name}")
        fingerprint_bytes += raw
        parsed = [Case.model_validate_json(line) for line in raw.splitlines() if line.strip()]
        if not parsed or any(case.split != name.removesuffix(".jsonl") for case in parsed):
            raise ValueError("Cases must belong to the declared nonempty split")
        cases.extend(parsed)
    ids = [case.id for case in cases]
    questions = [" ".join(case.question.casefold().split()) for case in cases]
    if len(set(ids)) != len(ids) or len(set(questions)) != len(questions):
        raise ValueError("Duplicate case IDs or questions")
    dev_groups = {case.group_id for case in cases if case.split == "dev"}
    test_groups = {case.group_id for case in cases if case.split == "test"}
    if dev_groups & test_groups:
        raise ValueError("A question family crosses development and held-out splits")
    for case in cases:
        for evidence in case.evidence:
            if evidence.chunk_id not in passages:
                raise ValueError(f"Unknown evidence chunk in {case.id}")
            if evidence.quote not in passages[evidence.chunk_id].content:
                raise ValueError(f"Evidence quote is not present in {case.id}")
    return manifest, cases, passages, sha256(fingerprint_bytes)


def validation_report(folder: Path, snapshot: Path) -> dict:
    manifest, cases, passages, digest = load_dataset(folder, snapshot)
    return {
        "kind": "dataset_validation_not_a_benchmark",
        "dataset_id": manifest.dataset_id,
        "dataset_sha256": digest,
        "snapshot_id": manifest.snapshot_id,
        "snapshot_hash": manifest.snapshot_hash,
        "cases": len(cases),
        "splits": dict(Counter(case.split for case in cases)),
        "categories": dict(Counter(case.category for case in cases)),
        "review_status": dict(Counter(case.provenance.review_status for case in cases)),
        "labelled_evidence_references": sum(len(case.evidence) for case in cases),
        "corpus_chunks": len(passages),
        "checks": "passed",
        "model_calls": 0,
    }
