import json
import logging

logger = logging.getLogger("support_copilot")


def emit(event: str, **fields: str | int) -> None:
    logger.info(json.dumps({"event": event, **fields}, sort_keys=True))


def configure_logging() -> None:
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
