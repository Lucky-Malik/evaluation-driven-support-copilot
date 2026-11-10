import json
import platform
from importlib.metadata import version
from pathlib import Path

from support_copilot.corpus import sha256


def json_hash(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode())


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    temporary.replace(path)


def environment_identity() -> dict:
    source_root = Path(__file__).resolve().parents[1]
    source = {
        str(path.relative_to(source_root)): sha256(path.read_bytes())
        for path in sorted(source_root.rglob("*"))
        if path.is_file() and path.suffix in {".py", ".sql", ".json", ".txt"}
    }
    packages = {
        name: version(name) for name in ("support-copilot", "openai", "pydantic", "psycopg")
    }
    return {
        "python": platform.python_version(),
        "system": platform.system(),
        "packages": packages,
        "source_sha256": json_hash(source),
        "source_files": source,
    }


def read_run(folder: Path) -> tuple[dict, list[dict]]:
    manifest = json.loads((folder / "run.json").read_text())
    if manifest["status"] != "completed" or manifest["kind"] != "live_evaluation":
        raise ValueError("Only completed live evaluation artifacts can be compared or reviewed")
    raw = (folder / "cases.jsonl").read_bytes()
    if sha256(raw) != manifest["results_sha256"]:
        raise ValueError("Run result checksum mismatch")
    records = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if [record["case"]["id"] for record in records] != manifest["case_ids"]:
        raise ValueError("Run cases do not match the manifest")
    return manifest, records
