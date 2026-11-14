"""Streamlit entry point. Browsing artifacts never calls a model or the database."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import streamlit as st
from dotenv import load_dotenv

from support_copilot.dashboard_data import (
    DashboardError,
    ask_api,
    discover_runs,
    load_dashboard_run,
    run_path,
)
from support_copilot.evaluation.runner import compare_runs


def metric_table(metrics: dict) -> None:
    st.dataframe(
        [
            {"Metric": name, "Score": score["value"], "Scored cases": score["n"]}
            for name, score in metrics.items()
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption("Scores range from 0 to 1. Missing scores are unavailable, not zero.")


def ask_page() -> None:
    st.header("Ask a FastAPI question")
    st.write("Get an answer grounded in the saved documentation, with sources you can inspect.")
    st.caption("Each submission can make paid model calls. Questions are independent.")
    with st.form("question_form"):
        question = st.text_area(
            "Your question",
            placeholder="How do I require item_id to be an integer path parameter?",
            max_chars=4000,
        )
        submitted = st.form_submit_button("Ask", type="primary")
    if submitted:
        st.session_state.pop("last_answer", None)
        st.session_state.pop("last_question", None)
        try:
            with st.spinner("Retrieving evidence and preparing an answer…"):
                answer = ask_api(os.getenv("COPILOT_API_URL", "http://127.0.0.1:8000"), question)
            st.session_state.last_answer = answer
            st.session_state.last_question = question.strip()
        except DashboardError as error:
            st.error(str(error))
    answer = st.session_state.get("last_answer")
    if answer is None:
        return
    st.subheader("Result")
    st.caption(st.session_state.last_question)
    if answer.status == "answered":
        st.success("Answered with citations")
        st.markdown(answer.answer)
    elif answer.status == "needs_clarification":
        st.info(answer.clarification_question)
        st.caption("Submit a new question including the missing detail.")
    else:
        st.warning("The saved documentation does not provide enough evidence.")
    st.write(answer.reason)
    if answer.citations:
        st.subheader("Sources")
        for citation in answer.citations:
            st.write(f"{citation.title} · {citation.section}")
            if urlsplit(citation.source_url).scheme in {"http", "https"}:
                st.link_button("Open source", citation.source_url)
            st.caption(citation.chunk_id)
    with st.expander("Retrieved passages"):
        for passage in answer.retrieved_passages:
            st.write(f"{passage.title} · {passage.section}")
            st.code(passage.content, language=None, wrap_lines=True)
            st.caption(passage.chunk_id)
    with st.expander("Request timing and usage"):
        st.write("Estimated cost: unavailable")
        st.json(answer.trace.model_dump())


def evaluation_page(root: Path) -> None:
    st.header("Evaluation dashboard")
    st.write("Inspect saved quality runs and compare matched experiments without model calls.")
    st.caption("Inspect score coverage and label provenance before interpreting quality.")
    try:
        names = discover_runs(root)
    except OSError:
        st.error("Cannot read the runs directory. Check COPILOT_RUNS_DIR and file permissions.")
        return
    if not names:
        st.info("No evaluation runs found. Create one with copilot eval run --output runs/my-run.")
        return
    selected = st.selectbox("Run", names)
    try:
        manifest, records, summary = load_dashboard_run(root, selected)
    except DashboardError as error:
        st.error(str(error))
        return
    overall = summary["overall"]
    cols = st.columns(3)
    cols[0].metric("Cases", overall["cases"])
    cols[1].metric("Application errors", overall["application_errors"])
    cols[2].metric("Judge failures", overall["judge_failures"])
    metric_table(overall["metrics"])
    with st.expander("Latency, usage, and run identity"):
        st.write(
            "Estimated cost: unavailable. Application and judge usage are reported separately."
        )
        st.json({k: v for k, v in overall.items() if "latency" in k or "usage" in k})
        st.json(manifest)
    with st.expander("Category breakdown and failures"):
        st.json(summary["by_category"])
        st.json(summary["failure_counts"])
    st.subheader("Inspect a case")
    category = st.selectbox("Category", ["All", *sorted(summary["by_category"])])
    failures_only = st.checkbox("Failures only")
    filtered = [
        r
        for r in records
        if (category == "All" or r["case"]["category"] == category)
        and (not failures_only or r["failure_tags"])
    ]
    if filtered:
        case_id = st.selectbox("Case", [r["case"]["id"] for r in filtered])
        record = next(r for r in filtered if r["case"]["id"] == case_id)
        st.write(record["case"]["question"])
        st.caption(f"Expected outcome: {record['case']['expected_status']}")
        result_tab, evidence_tab, judge_tab = st.tabs(["Response", "Evidence", "Judgment"])
        with result_tab:
            answer = record["application"]["answer"]
            if answer:
                st.write(f"Observed outcome: {answer['status']}")
                st.markdown(
                    answer["answer"] or answer["clarification_question"] or answer["reason"]
                )
            else:
                st.error("The application failed for this case.")
                st.json(record["application"]["error"])
            st.write("Answer criteria")
            st.write(record["case"]["answer_criteria"])
            st.write("Failure tags", record["failure_tags"])
        with evidence_tab:
            for passage in record["application"]["retrieved_passages"]:
                st.write(f"{passage['title']} · {passage['section']}")
                st.caption(passage["chunk_id"])
                st.code(passage["content"], language=None, wrap_lines=True)
            with st.expander("Labelled evidence and provenance"):
                st.json(record["gold_passages"])
                st.json(record["case"]["provenance"])
        with judge_tab:
            st.json(record["scores"])
            st.json(record["judge"])
        with st.expander("Full case record"):
            st.json(record)
    else:
        st.info("No cases match these filters.")
    st.subheader("Compare runs")
    other = st.selectbox("Candidate run", ["—", *[name for name in names if name != selected]])
    if other != "—":
        try:
            load_dashboard_run(root, other)
            comparison = compare_runs(run_path(root, selected), run_path(root, other))
            st.dataframe(
                [{"Metric": name, **value} for name, value in comparison["paired_metrics"].items()],
                hide_index=True,
                width="stretch",
            )
            st.caption(comparison["note"])
        except (OSError, ValueError, KeyError, TypeError):
            st.error(
                "These runs cannot be compared. Check artifact integrity and matched identities."
            )
    st.download_button(
        "Download summary",
        json.dumps(summary, indent=2),
        file_name=f"{selected}-summary.json",
        mime="application/json",
    )


def main() -> None:
    load_dotenv()
    st.set_page_config(page_title="Support Copilot", page_icon="📚", layout="wide")
    st.title("Support Copilot")
    page = st.sidebar.radio("Workspace", ["Ask", "Evaluation"])
    st.sidebar.caption("FastAPI documentation · six-page snapshot")
    if page == "Ask":
        ask_page()
    else:
        evaluation_page(Path(os.getenv("COPILOT_RUNS_DIR", "runs")))


if __name__ == "__main__":
    main()
