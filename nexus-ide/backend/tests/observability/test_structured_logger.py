"""Tests for StructuredLogger."""
import json
import logging

from backend.observability.structured_logger import (
    StructuredLogFormatter,
    StructuredLogger,
    configure_structured_logging,
    set_correlation_context,
    clear_correlation_context,
)


class TestStructuredLogFormatter:
    def test_format_basic(self) -> None:
        formatter = StructuredLogFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="hello", args=(), exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["message"] == "hello"
        assert data["level"] == "INFO"
        assert "timestamp" in data

    def test_format_with_trace_id(self) -> None:
        formatter = StructuredLogFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="hello", args=(), exc_info=None,
        )
        record.trace_id = "abc-123"
        output = formatter.format(record)
        data = json.loads(output)
        assert data["trace_id"] == "abc-123"


class TestStructuredLogger:
    def test_log_levels(self, caplog) -> None:
        logger = StructuredLogger("test")
        with caplog.at_level(logging.DEBUG):
            logger.debug("debug msg", extra_field="x")
            logger.info("info msg")
            logger.warning("warn msg")
            logger.error("error msg")

        assert len(caplog.records) == 4
        assert caplog.records[0].message == "debug msg"

    def test_correlation_context(self, caplog) -> None:
        logger = StructuredLogger("test")
        set_correlation_context(trace_id="trace-1", span_id="span-1")

        with caplog.at_level(logging.INFO):
            logger.info("with context")

        record = caplog.records[0]
        assert record.trace_id == "trace-1"
        assert record.span_id == "span-1"

        clear_correlation_context()
