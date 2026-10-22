"""Structured logging, Prometheus metrics, and OpenTelemetry tracing for the orders API."""
import contextvars
import json
import logging
import sys
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import Response
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "path", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency in seconds", ["method", "path"]
)


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = REQUEST_ID.get()
        span_ctx = trace.get_current_span().get_span_context()
        record.trace_id = f"{span_ctx.trace_id:032x}" if span_ctx.is_valid else "-"
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "trace_id": getattr(record, "trace_id", "-"),
        }
        payload.update(getattr(record, "fields", {}))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def _configure_logging() -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    handler.addFilter(_ContextFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    return logging.getLogger("orders_api")


logger = _configure_logging()


def instrument(app: FastAPI) -> None:
    """Wire structured logging, Prometheus metrics, and tracing onto `app`."""
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)

    # Registered before FastAPIInstrumentor.instrument_app() below: Starlette
    # makes the most-recently-added middleware outermost, and we need the
    # OTel span middleware to wrap *this* one (not the other way round) so
    # the span is still active -- and its trace_id readable -- while this
    # middleware logs the completed request.
    @app.middleware("http")
    async def observe_requests(request: Request, call_next):
        REQUEST_ID.set(str(uuid.uuid4()))
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request_failed",
                extra={"fields": {"method": request.method, "path": request.url.path}},
            )
            raise

        duration = time.perf_counter() - start
        REQUEST_COUNT.labels(request.method, request.url.path, response.status_code).inc()
        REQUEST_LATENCY.labels(request.method, request.url.path).observe(duration)
        logger.info(
            "request_handled",
            extra={
                "fields": {
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round(duration * 1000, 2),
                }
            },
        )
        response.headers["X-Request-ID"] = REQUEST_ID.get()
        return response

    FastAPIInstrumentor.instrument_app(app)
    PsycopgInstrumentor().instrument()

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
