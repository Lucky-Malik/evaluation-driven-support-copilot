from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from support_copilot.dashboard_data import (
    DashboardError,
    ask_api,
    discover_runs,
    load_dashboard_run,
    run_path,
)

APP = Path(__file__).resolve().parents[2] / "src/support_copilot/dashboard.py"


@pytest.fixture
def ui(monkeypatch, tmp_path):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("COPILOT_RUNS_DIR", str(tmp_path))
    # Allow cold pandas/Arrow imports on slower CI machines.
    return AppTest.from_file(str(APP), default_timeout=30)


def test_api_posts_validated_question_and_parses_answer(monkeypatch, dataset_bundle, make_answer):
    expected = make_answer(dataset_bundle[1][0])
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json=expected.model_dump())

    monkeypatch.setattr("support_copilot.dashboard_data.httpx.post", post)
    assert ask_api("http://api:8000/", "  How?  ") == expected
    assert calls[0][0] == "http://api:8000/ask"
    assert calls[0][1]["json"] == {"question": "How?"}
    with pytest.raises(DashboardError, match="Enter a question"):
        ask_api("http://api:8000", "   ")
    assert len(calls) == 1


@pytest.mark.parametrize("status", [422, 429, 500, 503, 504])
def test_api_errors_never_display_raw_response(monkeypatch, status):
    monkeypatch.setattr(
        "support_copilot.dashboard_data.httpx.post",
        lambda *a, **kw: httpx.Response(status, text="secret-database-password"),
    )
    with pytest.raises(DashboardError) as caught:
        ask_api("http://api:8000", "How?")
    assert "secret" not in str(caught.value)


def test_timeout_is_not_retried(monkeypatch):
    calls = []

    def timeout(*args, **kwargs):
        calls.append(args)
        raise httpx.ReadTimeout("private detail")

    monkeypatch.setattr("support_copilot.dashboard_data.httpx.post", timeout)
    with pytest.raises(DashboardError, match="may have completed"):
        ask_api("http://api:8000", "How?")
    assert len(calls) == 1


def test_invalid_api_response(monkeypatch):
    monkeypatch.setattr(
        "support_copilot.dashboard_data.httpx.post",
        lambda *a, **kw: httpx.Response(200, json={"private": "bad response"}),
    )
    with pytest.raises(DashboardError, match="invalid response"):
        ask_api("http://api:8000", "How?")


def test_invalid_api_url_has_a_safe_error():
    with pytest.raises(DashboardError, match="Cannot reach"):
        ask_api("http://[", "How?")


def test_dashboard_recomputes_summary_and_rejects_tampering(make_run, tmp_path):
    folder, result = make_run("baseline")
    (folder / "summary.json").write_text('{"overall": {"cases": 999}}')
    assert discover_runs(tmp_path) == ["baseline"]
    _, _, summary = load_dashboard_run(tmp_path, "baseline")
    assert summary["overall"] == result["overall"]
    (folder / "cases.jsonl").write_text("{}")
    with pytest.raises(DashboardError, match="intact artifacts"):
        load_dashboard_run(tmp_path, "baseline")


def test_dashboard_rejects_traversal_and_symlinks(tmp_path):
    root = tmp_path / "runs"
    root.mkdir()
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "run.json").write_text("{}")
    (root / "link").symlink_to(outside, target_is_directory=True)
    assert discover_runs(root) == []
    for name in ("../private", "link", str(outside), ""):
        with pytest.raises(DashboardError):
            run_path(root, name)
    inside = root / "inside"
    inside.mkdir()
    (inside / "run.json").symlink_to(outside / "run.json")
    with pytest.raises(DashboardError):
        run_path(root, "inside")


@pytest.mark.parametrize("outcome", ["answered", "needs_clarification", "insufficient_evidence"])
def test_ui_submits_once_and_preserves_result(
    ui, monkeypatch, dataset_bundle, make_answer, outcome
):
    case = next(c for c in dataset_bundle[1] if c.expected_status == outcome)
    answer = make_answer(case)
    calls = []

    def ask(url, question):
        calls.append(question)
        return answer

    # Streamlit runs the entrypoint as __main__; patch the imported data function.
    monkeypatch.setattr("support_copilot.dashboard_data.ask_api", ask)
    ui.run()
    assert not ui.exception
    assert calls == []
    ui.text_area[0].input(case.question)
    ui.button[0].click().run()
    assert not ui.exception
    assert len(calls) == 1
    assert ui.session_state["last_answer"].status == outcome
    ui.run()
    assert len(calls) == 1
    if outcome == "answered":
        assert ui.success[0].value == "Answered with citations"
    elif outcome == "needs_clarification":
        assert ui.info[0].value == answer.clarification_question
    else:
        assert "enough evidence" in ui.warning[0].value


def test_failed_submission_clears_previous_answer(ui, monkeypatch, dataset_bundle, make_answer):
    ui.session_state["last_answer"] = make_answer(dataset_bundle[1][0])
    ui.session_state["last_question"] = "old question"
    ui.run()
    ui.text_area[0].input("   ")
    ui.button[0].click().run()
    assert not ui.exception
    assert ui.error and "Enter a question" in ui.error[0].value
    assert "last_answer" not in ui.session_state


def test_ui_browses_and_compares_runs_without_api(ui, monkeypatch, make_run):
    make_run("baseline")
    make_run("candidate")
    monkeypatch.setattr(
        "support_copilot.dashboard_data.ask_api",
        lambda *a: pytest.fail("Browsing must not call the API"),
    )
    ui.run()
    ui.sidebar.radio[0].set_value("Evaluation").run()
    assert not ui.exception
    assert ui.metric[0].value == "3"
    ui.selectbox[3].select("candidate").run()
    assert not ui.exception
    assert len(ui.dataframe) == 2
    ui.checkbox[0].check().run()
    assert "No cases match" in ui.info[0].value


def test_ui_empty_and_corrupt_runs(ui, make_run):
    ui.run()
    ui.sidebar.radio[0].set_value("Evaluation").run()
    assert "No evaluation runs" in ui.info[0].value
    folder, _ = make_run("broken")
    (folder / "run.json").write_text("not json")
    ui.run()
    assert not ui.exception
    assert "Cannot load" in ui.error[0].value
