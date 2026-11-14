"""Read-only artifact access and the dashboard's API boundary."""

from pathlib import Path

import httpx

from support_copilot.contracts import Answer, Question
from support_copilot.evaluation.artifacts import read_run
from support_copilot.evaluation.metrics import summarize


class DashboardError(ValueError):
    """A safe, user-facing dashboard failure."""


def ask_api(base_url: str, question: str) -> Answer:
    try:
        payload = Question(question=question)
    except ValueError:
        raise DashboardError("Enter a question between 1 and 4,000 characters.") from None
    try:
        # No automatic retries: a lost response may already have incurred model usage.
        response = httpx.post(
            base_url.rstrip("/") + "/ask",
            json=payload.model_dump(),
            timeout=httpx.Timeout(120, connect=5),
        )
    except httpx.TimeoutException:
        raise DashboardError(
            "The API timed out. The request may have completed; check API logs before retrying."
        ) from None
    except (httpx.HTTPError, httpx.InvalidURL, ValueError):
        raise DashboardError(
            "Cannot reach the API. Check COPILOT_API_URL and start the API."
        ) from None
    if response.is_error:
        messages = {
            413: "The question exceeds the API request limit.",
            422: "The API rejected the question. Use between 1 and 4,000 characters.",
            429: "The provider is rate limited. Try again later.",
            503: "The API is not ready. Check its key, database, and corpus configuration.",
            504: "The provider timed out. Check API logs before retrying.",
        }
        raise DashboardError(messages.get(response.status_code, "The API could not answer."))
    try:
        return Answer.model_validate(response.json())
    except ValueError:
        raise DashboardError("The API returned an invalid response.") from None


def discover_runs(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    resolved = root.resolve()
    return sorted(
        item.name
        for item in root.iterdir()
        if item.is_dir()
        and item.resolve().is_relative_to(resolved)
        and (item / "run.json").is_file()
    )


def run_path(root: Path, name: str) -> Path:
    folder = (root / name).resolve()
    if not name or Path(name).name != name or not folder.is_relative_to(root.resolve()):
        raise DashboardError("Select a run inside the configured runs directory.")
    for filename in ("run.json", "cases.jsonl"):
        if not (folder / filename).resolve().is_relative_to(root.resolve()):
            raise DashboardError("Run files must remain inside the configured runs directory.")
    return folder


def load_dashboard_run(root: Path, name: str) -> tuple[dict, list[dict], dict]:
    try:
        manifest, records = read_run(run_path(root, name))
        if not records:
            raise ValueError("Empty run")
        # Recompute from checksum-verified records; summary.json is not authoritative.
        summary = summarize(records)
        return manifest, records, summary
    except (OSError, ValueError, KeyError, TypeError):
        raise DashboardError(
            "Cannot load this run. It must be a completed quality evaluation with intact artifacts."
        ) from None
