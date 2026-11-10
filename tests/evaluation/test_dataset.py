import json
import shutil
from pathlib import Path

import pytest

from support_copilot.corpus import sha256
from support_copilot.evaluation.dataset import load_dataset, validation_report

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "data/evaluation/fastapi-support-v1"
SNAPSHOT = ROOT / "data/snapshots/fastapi-d4f83a093dd1b2ab"


def test_starter_dataset_and_provenance():
    report = validation_report(DATASET, SNAPSHOT)
    assert report["cases"] == 30
    assert report["splits"] == {"dev": 20, "test": 10}
    assert report["review_status"] == {"agent_inspected": 30}
    assert report["labelled_evidence_references"] == 21
    assert report["model_calls"] == 0


def rewrite_dev(folder, mutate):
    path = folder / "dev.jsonl"
    cases = [json.loads(line) for line in path.read_text().splitlines()]
    mutate(cases)
    path.write_text("".join(json.dumps(case) + "\n" for case in cases))
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["dev.jsonl"] = sha256(path.read_bytes())
    manifest_path.write_text(json.dumps(manifest))


def test_file_tampering_rejected(tmp_path):
    folder = tmp_path / "dataset"
    shutil.copytree(DATASET, folder)
    with (folder / "dev.jsonl").open("a") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="checksum"):
        load_dataset(folder, SNAPSHOT)


@pytest.mark.parametrize(
    "problem", ["unknown_chunk", "wrong_quote", "duplicate_id", "cross_split_group"]
)
def test_semantic_dataset_errors_rejected_even_with_new_checksum(tmp_path, problem):
    folder = tmp_path / "dataset"
    shutil.copytree(DATASET, folder)

    def mutate(cases):
        if problem == "unknown_chunk":
            cases[0]["evidence"][0]["chunk_id"] = "invented"
        elif problem == "wrong_quote":
            cases[0]["evidence"][0]["quote"] = "A sentence not in this chunk."
        elif problem == "duplicate_id":
            cases[1]["id"] = cases[0]["id"]
        else:
            cases[0]["group_id"] = "enum-response"

    rewrite_dev(folder, mutate)
    with pytest.raises(ValueError):
        load_dataset(folder, SNAPSHOT)
