import argparse
from pathlib import Path

from openai import OpenAI

from support_copilot.db import database_url
from support_copilot.evaluation.adversarial import load_adversarial, run_adversarial
from support_copilot.evaluation.artifacts import write_json
from support_copilot.evaluation.dataset import validation_report
from support_copilot.evaluation.judge import load_judge_settings
from support_copilot.evaluation.keyword import keyword_evaluation
from support_copilot.evaluation.review import prepare_review, record_review
from support_copilot.evaluation.runner import compare_runs, run_evaluation
from support_copilot.settings import api_key, load_settings


def add_evaluation_parser(commands: argparse._SubParsersAction) -> None:
    evaluation = commands.add_parser("eval")
    actions = evaluation.add_subparsers(dest="evaluation_command", required=True)
    validate = actions.add_parser("validate")
    validate.add_argument("--report", type=Path)
    run = actions.add_parser("run")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--split", choices=("dev", "test"), default="dev")
    run.add_argument("--limit", type=int)
    keyword = actions.add_parser("keyword")
    keyword.add_argument("--report", type=Path, required=True)
    for parser in (validate, run, keyword):
        parser.add_argument(
            "--dataset", type=Path, default=Path("data/evaluation/fastapi-support-v1")
        )
        parser.add_argument(
            "--snapshot", type=Path, default=Path("data/snapshots/fastapi-d4f83a093dd1b2ab")
        )
    adversarial_validate = actions.add_parser("adversarial-validate")
    adversarial_run = actions.add_parser("adversarial-run")
    adversarial_run.add_argument("--output", type=Path, required=True)
    for parser in (adversarial_validate, adversarial_run):
        parser.add_argument(
            "--dataset", type=Path, default=Path("data/evaluation/fastapi-adversarial-v1")
        )
        parser.add_argument(
            "--snapshot", type=Path, default=Path("data/snapshots/fastapi-d4f83a093dd1b2ab")
        )
    compare = actions.add_parser("compare")
    compare.add_argument("left", type=Path)
    compare.add_argument("right", type=Path)
    sample = actions.add_parser("review-sample")
    sample.add_argument("--run", type=Path, required=True)
    sample.add_argument("--output", type=Path, required=True)
    sample.add_argument("--count", type=int, default=5)
    sample.add_argument("--seed", type=int, default=42)
    record = actions.add_parser("review-record")
    record.add_argument("--run", type=Path, required=True)
    record.add_argument("--packet", type=Path, required=True)


def evaluate_command(args: argparse.Namespace) -> dict:
    if args.evaluation_command == "adversarial-validate":
        cases, _, identity = load_adversarial(args.dataset, args.snapshot)
        return {**identity, "cases": len(cases), "model_calls": 0, "checks": "passed"}
    if args.evaluation_command == "validate":
        report = validation_report(args.dataset, args.snapshot)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            write_json(args.report, report)
        return report
    if args.evaluation_command == "compare":
        return compare_runs(args.left, args.right)
    if args.evaluation_command == "review-sample":
        return prepare_review(args.run, args.output, args.count, args.seed)
    if args.evaluation_command == "review-record":
        return record_review(args.run, args.packet)
    settings = load_settings()
    if args.evaluation_command == "keyword":
        return keyword_evaluation(
            args.dataset, args.snapshot, args.report, database_url(), settings
        )
    if args.evaluation_command == "adversarial-run":
        with OpenAI(api_key=api_key(), timeout=settings.timeout_seconds, max_retries=0) as client:
            return run_adversarial(args.dataset, args.snapshot, args.output, settings, client)
    judge = load_judge_settings()
    key = api_key()
    with (
        OpenAI(api_key=key, timeout=settings.timeout_seconds, max_retries=0) as client,
        OpenAI(
            api_key=key,
            timeout=judge.timeout_seconds,
            max_retries=0,
        ) as judge_client,
    ):
        return run_evaluation(
            args.dataset,
            args.snapshot,
            args.output,
            args.split,
            args.limit,
            settings,
            judge,
            database_url(),
            client,
            judge_client,
        )
