import json
import logging
import sys
from contextvars import ContextVar

trace_id: ContextVar[str] = ContextVar("trace_id", default="-")
run_id: ContextVar[str] = ContextVar("run_id", default="-")


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    redacted = {}
    for key, value in headers.items():
        if key.lower() in {"authorization", "cookie", "x-api-key"}:
            redacted[key] = "[REDACTED]"
        else:
            redacted[key] = value
    return redacted


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": trace_id.get(),
            "run_id": run_id.get(),
        }
        return json.dumps(payload, separators=(",", ":"))


def configure_logging(service: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.LoggerAdapter(logging.getLogger(service), {})
