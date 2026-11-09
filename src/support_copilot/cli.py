import argparse
import json
import sys
from pathlib import Path

import httpx
import psycopg
from openai import OpenAI, OpenAIError

from support_copilot.db import database_url, ingest, initialize
from support_copilot.errors import CopilotError
from support_copilot.events import configure_logging, emit
from support_copilot.provider import provider_error
from support_copilot.retrieval import corpus_status, embed_corpus
from support_copilot.settings import api_key, load_settings
from support_copilot.snapshot import fetch_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(prog="copilot")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")
    commands.add_parser("index-status")
    commands.add_parser("embed")
    fetch = commands.add_parser("fetch-docs")
    fetch.add_argument("--output", type=Path, default=Path("data/snapshots"))
    ingest_parser = commands.add_parser("ingest")
    ingest_parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    configure_logging()
    try:
        if args.command == "fetch-docs":
            print(fetch_snapshot(args.output))
        elif args.command == "init-db":
            initialize(database_url())
        elif args.command == "index-status":
            print(json.dumps(corpus_status(database_url(), load_settings()), sort_keys=True))
        elif args.command == "embed":
            settings = load_settings()
            with OpenAI(
                api_key=api_key(), timeout=settings.timeout_seconds, max_retries=0
            ) as client:
                print(json.dumps(embed_corpus(database_url(), settings, client), sort_keys=True))
        else:
            print(json.dumps(ingest(database_url(), args.snapshot), sort_keys=True))
    except (
        CopilotError,
        OpenAIError,
        httpx.HTTPError,
        psycopg.Error,
        OSError,
        ValueError,
    ) as error:
        emit("command_failed", command=args.command, error_type=type(error).__name__)
        if isinstance(error, CopilotError):
            message = error.message
        elif isinstance(error, OpenAIError):
            message = provider_error(error).message
        elif isinstance(error, psycopg.Error):
            message = "Database operation failed; check DATABASE_URL, Docker, and init-db."
        elif isinstance(error, httpx.HTTPError):
            message = "Official documentation download failed; check network access and retry."
        elif isinstance(error, OSError):
            message = "File operation failed; check the snapshot path and file permissions."
        else:
            message = "Input validation failed; check the snapshot, model configuration, and .env."
        print(message, file=sys.stderr)
        raise SystemExit(1) from None
