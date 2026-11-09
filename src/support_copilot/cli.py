import argparse
import json
import sys
from pathlib import Path

import httpx
import psycopg

from support_copilot.db import database_url, ingest, initialize
from support_copilot.events import configure_logging, emit
from support_copilot.snapshot import fetch_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(prog="copilot")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")
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
        else:
            print(json.dumps(ingest(database_url(), args.snapshot), sort_keys=True))
    except (httpx.HTTPError, psycopg.Error, OSError, ValueError) as error:
        emit("command_failed", command=args.command, error_type=type(error).__name__)
        if isinstance(error, psycopg.Error):
            message = "Database operation failed; check DATABASE_URL, Docker, and init-db."
        elif isinstance(error, httpx.HTTPError):
            message = "Official documentation download failed; check network access and retry."
        elif isinstance(error, OSError):
            message = "File operation failed; check the snapshot path and file permissions."
        else:
            message = "Input validation failed; check the snapshot manifest, checksums, and .env."
        print(message, file=sys.stderr)
        raise SystemExit(1) from None
