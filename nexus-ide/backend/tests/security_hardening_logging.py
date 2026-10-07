"""P1-8 — log secrets unredacted and log growth unbounded.

The audit found no redaction anywhere, a hard-coded ``DEBUG`` level (so
``LOG_LEVEL=INFO`` was ignored), 299 files / 49 MB in ``logs/`` with no
rotation handler, a ``prune_old_logs()`` that nothing called, and one
``asyncio.create_task`` per log line with no reference, no done-callback and no
exception path.

These tests cover the redaction filter (message + args), the log level, the
size/total-size rotation caps, the supervised retention sweep, and the
supervised per-line persist.
"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from backend.core import disk_guard, log_rotation
from backend.observability import log_store as log_store_module
from backend.observability.logging_config import (
    REDACTION,
    RedactingFilter,
    is_secret_key_name,
    redact_text,
    setup_logging,
)


@pytest.fixture(autouse=True)
def _no_disk_guard(monkeypatch):
    monkeypatch.setattr(disk_guard, "require_disk_headroom", lambda *_a, **_k: None)
    yield


# ---------------------------------------------------------------------------
# 1. Redaction
# ---------------------------------------------------------------------------
class TestRedaction:
    @pytest.mark.parametrize(
        "text,secret",
        [
            ("openai_api_key=sk-proj-AAAABBBBCCCCDDDD", "sk-proj-AAAABBBBCCCCDDDD"),
            ("kilo_api_key=abcdef1234567890", "abcdef1234567890"),
            ("admin_password=hunter2hunter2", "hunter2hunter2"),
            ("redis_password=sup3rs3cr3t", "sup3rs3cr3t"),
            ("jwt_secret=abcdefghijklmnop", "abcdefghijklmnop"),
            ("secret_key=abcdefghijklmnop", "abcdefghijklmnop"),
            ("Authorization: Bearer abcdefghijklmnopqrst", "abcdefghijklmnopqrst"),
            ("x-api-key=sk-abcdefghijklmnop", "sk-abcdefghijklmnop"),
            ("Cookie: session=abcdef123456", "session=abcdef123456"),
            ("the key sk-abcdefghijklmnop was used", "sk-abcdefghijklmnop"),
            (
                "token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig12345",
                "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig12345",
            ),
        ],
    )
    def test_secret_is_masked(self, text: str, secret: str) -> None:
        redacted = redact_text(text)
        assert secret not in redacted, f"{secret!r} survived redaction in {redacted!r}"
        assert REDACTION in redacted

    @pytest.mark.parametrize(
        "text",
        [
            "input_tokens=1500 output_tokens=300 total_tokens=1800",
            "max_tokens=2048 anthropic_max_tokens=4096",
            "cost_per_token=0.003 token_budget=4000",
            "chars_per_token=4 key_id=abc123",
            "duration=1.53s level=INFO sha256=deadbeef1234",
            "allow_credentials=True cache_key=zzz",
            "httpx POST /api/chat 200 in 1.2s",
            "NEXUS orchestrator ready (provider=openrouter)",
        ],
    )
    def test_useful_data_survives(self, text: str) -> None:
        assert redact_text(text) == text, "a non-secret was redacted"

    def test_short_values_are_not_masked(self) -> None:
        assert redact_text("password=x") == "password=x"
        assert redact_text("api_key=true") == "api_key=true"

    def test_already_redacted_is_idempotent(self) -> None:
        once = redact_text("openai_api_key=sk-abcdefghijklmnop")
        assert redact_text(once) == once

    def test_provider_token_shapes(self) -> None:
        for token in (
            "sk-ant-api03-AAAABBBBCCCCDDDD",
            "gsk_AAAABBBBCCCCDDDDEEEE",
            "AIzaSyAAAABBBBCCCCDDDDEEEEFFFF",
            "ghp_AAAABBBBCCCCDDDDEEEEFFFFGGGG",
            "AKIAIOSFODNN7EXAMPLE",
        ):
            assert token not in redact_text(f"using {token} now"), token

    def test_secret_key_names(self) -> None:
        assert is_secret_key_name("openai_api_key")
        assert is_secret_key_name("SECRET_KEY")
        assert not is_secret_key_name("input_tokens")
        assert not is_secret_key_name("cost_per_token")

    def test_filter_masks_the_message(self) -> None:
        record = logging.LogRecord(
            "t", logging.INFO, __file__, 1, "key=%s", ("sk-abcdefghijklmnop",), None
        )
        assert RedactingFilter().filter(record) is True
        assert "sk-abcdefghijklmnop" not in record.getMessage()
        assert REDACTION in record.getMessage()

    def test_filter_masks_positional_args(self) -> None:
        record = logging.LogRecord(
            "t", logging.INFO, __file__, 1, "a=%s b=%s", ("openai_api_key=sk-abcdefghij", "1"), None
        )
        RedactingFilter().filter(record)
        assert "sk-abcdefghij" not in record.getMessage()

    def test_filter_masks_mapping_args(self) -> None:
        record = logging.LogRecord(
            "t",
            logging.INFO,
            __file__,
            1,
            "cfg=%(cfg)s",
            ({"cfg": {"openai_api_key": "sk-abcdefghijklmnop", "input_tokens": 5}},),
            None,
        )
        RedactingFilter().filter(record)
        rendered = record.getMessage()
        assert "sk-abcdefghijklmnop" not in rendered
        assert "REDACTED" in rendered

    def test_filter_never_raises(self) -> None:
        class _Exploding:
            def __str__(self) -> str:
                raise RuntimeError("nope")

        record = logging.LogRecord(
            "t", logging.INFO, __file__, 1, "x=%s", (_Exploding(),), None
        )
        assert RedactingFilter().filter(record) is True

    def test_end_to_end_through_setup_logging(self, tmp_path, caplog) -> None:
        log_file = tmp_path / "app.log"
        root = logging.getLogger()
        previous_handlers = list(root.handlers)
        previous_level = root.level
        try:
            setup_logging(level="INFO", json_format=True, log_file=str(log_file))
            logging.getLogger("secretprobe").error(
                "connecting with openai_api_key=%s", "sk-abcdefghijklmnop"
            )
            for handler in root.handlers:
                handler.flush()
            written = log_file.read_text(encoding="utf-8")
            assert "sk-abcdefghijklmnop" not in written
            assert REDACTION in written
            entry = json.loads(written.strip().splitlines()[-1])
            assert "sk-abcdefghijklmnop" not in json.dumps(entry)
        finally:
            for handler in list(root.handlers):
                if getattr(handler, "_nexus_owned", False):
                    root.removeHandler(handler)
                    handler.close()
            for handler in previous_handlers:
                if handler not in root.handlers:
                    root.addHandler(handler)
            root.setLevel(previous_level)

    def test_exception_messages_are_redacted(self, tmp_path) -> None:
        log_file = tmp_path / "app.log"
        root = logging.getLogger()
        previous = list(root.handlers)
        try:
            setup_logging(level="INFO", json_format=True, log_file=str(log_file))
            try:
                raise RuntimeError("failed for openai_api_key=sk-abcdefghijklmnop")
            except RuntimeError:
                logging.getLogger("secretprobe").exception("boom")
            for handler in root.handlers:
                handler.flush()
            written = log_file.read_text(encoding="utf-8")
            assert "sk-abcdefghijklmnop" not in written
        finally:
            for handler in list(root.handlers):
                if getattr(handler, "_nexus_owned", False):
                    root.removeHandler(handler)
                    handler.close()
            for handler in previous:
                if handler not in root.handlers:
                    root.addHandler(handler)


# ---------------------------------------------------------------------------
# 2. Log level honours LOG_LEVEL
# ---------------------------------------------------------------------------
class TestLogLevel:
    def test_setup_logging_applies_the_requested_level(self, tmp_path) -> None:
        root = logging.getLogger()
        previous_level = root.level
        previous = list(root.handlers)
        try:
            setup_logging(level="WARNING", json_format=True, log_file=str(tmp_path / "a.log"))
            assert root.level == logging.WARNING
        finally:
            for handler in list(root.handlers):
                if getattr(handler, "_nexus_owned", False):
                    root.removeHandler(handler)
                    handler.close()
            for handler in previous:
                if handler not in root.handlers:
                    root.addHandler(handler)
            root.setLevel(previous_level)

    def test_main_no_longer_hardcodes_debug(self) -> None:
        import inspect

        from backend.orchestrator import main

        source = inspect.getsource(main)
        assert 'setup_logging(level="DEBUG"' not in source, (
            "main.py still hard-codes DEBUG and ignores LOG_LEVEL"
        )
        assert "log_level" in source

    def test_settings_expose_log_level(self) -> None:
        from backend.config.settings import get_settings

        assert get_settings().log_level


# ---------------------------------------------------------------------------
# 3. Rotation
# ---------------------------------------------------------------------------
class TestRotation:
    def test_parse_size(self) -> None:
        assert log_rotation.parse_size("10MB", 1) == 10 * 1024 * 1024
        assert log_rotation.parse_size("512", 1) == 512
        assert log_rotation.parse_size("", 99) == 99
        assert log_rotation.parse_size(None, 99) == 99
        assert log_rotation.parse_size("not-a-size", 99) == 99

    def test_file_rotates_at_max_bytes(self, tmp_path) -> None:
        log_file = tmp_path / "app.log"
        handler = log_rotation.NexusRotatingFileHandler(
            log_file, max_bytes=1024, backup_count=3, max_total_bytes=10 * 1024
        )
        try:
            for _ in range(40):
                handler.emit(
                    logging.LogRecord("t", logging.INFO, __file__, 1, "x" * 200, None, None)
                )
            assert log_file.exists()
            assert log_file.stat().st_size <= 4 * 1024
            rotated = list(tmp_path.glob("app.log.*"))
            assert rotated, "no rotated file was produced"
        finally:
            handler.close()

    def test_backup_count_is_bounded(self, tmp_path) -> None:
        log_file = tmp_path / "app.log"
        handler = log_rotation.NexusRotatingFileHandler(
            log_file, max_bytes=512, backup_count=2, max_total_bytes=10 * 1024
        )
        try:
            for _ in range(200):
                handler.emit(
                    logging.LogRecord("t", logging.INFO, __file__, 1, "y" * 200, None, None)
                )
            assert len(list(tmp_path.glob("app.log.*"))) <= 2
        finally:
            handler.close()

    def test_total_size_cap_evicts_oldest_first(self, tmp_path) -> None:
        log_file = tmp_path / "app.log"
        for index in range(6):
            path = tmp_path / f"app.log.{index}"
            path.write_bytes(b"z" * 4096)
            import os
            import time

            os.utime(path, (time.time() + index, time.time() + index))
        handler = log_rotation.NexusRotatingFileHandler(
            log_file, max_bytes=10 * 1024 * 1024, backup_count=100, max_total_bytes=8192
        )
        try:
            removed = handler.enforce_total_cap()
            assert removed >= 1
            remaining = sorted(p.name for p in tmp_path.glob("app.log.*"))
            assert "app.log.0" not in remaining, "the oldest file should be evicted first"
            assert remaining[-1] == "app.log.5"
        finally:
            handler.close()

    def test_total_cap_is_read_from_env(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("NEXUS_LOG_MAX_TOTAL_BYTES", "1MB")
        handler = log_rotation.NexusRotatingFileHandler(tmp_path / "a.log")
        try:
            assert handler.max_total_bytes == 1024 * 1024
        finally:
            handler.close()

    def test_setup_logging_installs_a_rotating_handler(self, tmp_path) -> None:
        root = logging.getLogger()
        previous = list(root.handlers)
        try:
            setup_logging(level="INFO", json_format=True, log_file=str(tmp_path / "a.log"))
            handlers = [
                h
                for h in root.handlers
                if isinstance(h, log_rotation.NexusRotatingFileHandler)
            ]
            assert handlers, "no rotating handler installed"
            assert handlers[0].max_bytes > 0
            assert handlers[0].backup_count > 0
            assert handlers[0].max_total_bytes > 0
        finally:
            for handler in list(root.handlers):
                if getattr(handler, "_nexus_owned", False):
                    root.removeHandler(handler)
                    handler.close()
            for handler in previous:
                if handler not in root.handlers:
                    root.addHandler(handler)

    def test_oversized_existing_file_is_rotated_on_first_write(self, tmp_path) -> None:
        """The production scenario: ``logs/backend.log`` is already 40 MB.

        ``RotatingFileHandler`` rotates when the *current* size plus the new
        record would exceed ``max_bytes``, so an already-oversized file must be
        rolled on its very first write instead of growing forever.  Scaled down
        here (40 KB file, 1 KB cap) for speed; the real default is
        ``NEXUS_LOG_MAX_BYTES=10MB``.
        """
        log_file = tmp_path / "backend.log"
        log_file.write_bytes(b"x" * 40_000)
        handler = log_rotation.NexusRotatingFileHandler(
            log_file, max_bytes=1024, backup_count=3, max_total_bytes=200_000
        )
        try:
            handler.emit(
                logging.LogRecord("t", logging.INFO, __file__, 1, "first record", None, None)
            )
            assert list(tmp_path.glob("backend.log.*")), (
                "the pre-existing oversized file was never rolled"
            )
            assert log_file.stat().st_size < 40_000
        finally:
            handler.close()

    def test_rotation_does_not_create_the_file_until_needed(self, tmp_path) -> None:
        log_file = tmp_path / "lazy.log"
        handler = log_rotation.NexusRotatingFileHandler(log_file)
        try:
            assert not log_file.exists()
        finally:
            handler.close()

    def test_rollover_failure_does_not_propagate(self, tmp_path, monkeypatch) -> None:
        handler = log_rotation.NexusRotatingFileHandler(
            tmp_path / "a.log", max_bytes=1024, backup_count=2
        )
        try:
            import logging.handlers

            def boom(self):
                raise OSError("read-only filesystem")

            monkeypatch.setattr(logging.handlers.RotatingFileHandler, "doRollover", boom)
            handler.doRollover()  # must not raise
        finally:
            handler.close()


# ---------------------------------------------------------------------------
# 4. Supervised retention sweep
# ---------------------------------------------------------------------------
class TestPruneSupervision:
    def test_prune_logs_forever_runs_and_stops(self, monkeypatch) -> None:
        calls: list[int] = []

        class _Store:
            async def prune_old_logs(self, days: int = 30) -> int:
                calls.append(days)
                return 0

        monkeypatch.setattr(log_store_module, "get_log_store", lambda: _Store())
        monkeypatch.setenv("NEXUS_LOG_RETENTION_DAYS", "7")
        monkeypatch.setenv("NEXUS_LOG_PRUNE_INTERVAL_SECONDS", "3600")

        async def runner() -> None:
            task = asyncio.create_task(log_store_module.prune_logs_forever())
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(runner())
        assert calls and calls[0] == 7, "the retention sweep never ran"

    def test_prune_survives_a_failing_probe(self, monkeypatch, caplog) -> None:
        class _Store:
            async def prune_old_logs(self, days: int = 30) -> int:
                raise RuntimeError("db locked")

        monkeypatch.setattr(log_store_module, "get_log_store", lambda: _Store())
        monkeypatch.setenv("NEXUS_LOG_PRUNE_INTERVAL_SECONDS", "3600")

        async def runner() -> None:
            task = asyncio.create_task(log_store_module.prune_logs_forever())
            await asyncio.sleep(0.05)
            # The loop must still be alive after the failure.
            assert not task.done(), "the retention sweep died on first error"
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        with caplog.at_level("ERROR"):
            asyncio.run(runner())
        assert any("retention sweep failed" in r.message for r in caplog.records)

    def test_the_sweep_is_actually_started(self) -> None:
        """``prune_old_logs`` used to have no caller at all."""
        import inspect

        from backend.orchestrator import main

        assert "prune_logs_forever" in inspect.getsource(main)

    def test_prune_is_reachable_from_the_module(self) -> None:
        assert callable(log_store_module.prune_logs_forever)
        assert log_store_module.PRUNE_RETENTION_DAYS > 0
        assert log_store_module.PRUNE_INTERVAL_SECONDS > 0


# ---------------------------------------------------------------------------
# 5. Supervised per-line persist
# ---------------------------------------------------------------------------
class TestPersistSupervision:
    def test_insert_schedules_a_supervised_task(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(log_store_module, "DB_PATH", tmp_path / "logs.db")
        store = log_store_module.LogStore()
        original = store._persist

        async def tracked(entry):
            await original(entry)

        monkeypatch.setattr(store, "_persist", tracked)

        async def scenario():
            store._initialized = True
            await store.insert("INFO", "hello")
            assert store.inflight_persists == 1, "no strong reference was retained"
            await store.drain(timeout=5)
            assert store.inflight_persists == 0, "the reference was never dropped"

        asyncio.run(scenario())

    def test_persist_failure_is_logged_not_swallowed(self, monkeypatch, tmp_path, caplog) -> None:
        monkeypatch.setattr(log_store_module, "DB_PATH", tmp_path / "logs.db")
        store = log_store_module.LogStore()

        async def boom(entry):
            raise RuntimeError("disk gone")

        monkeypatch.setattr(store, "_persist", boom)

        async def scenario():
            store._initialized = True
            await store.insert("INFO", "hello")
            await asyncio.sleep(0.05)

        with caplog.at_level("ERROR"):
            asyncio.run(scenario())
        assert any(
            "persistence failed" in r.message for r in caplog.records
        ), "an unobserved persist failure is exactly what the audit flagged"
        assert store.inflight_persists == 0

    def test_inflight_cap_prevents_unbounded_tasks(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(log_store_module, "DB_PATH", tmp_path / "logs.db")
        store = log_store_module.LogStore()
        store.MAX_INFLIGHT_PERSISTS = 4
        gate = asyncio.Event()

        async def blocked(entry):
            await gate.wait()

        async def scenario():
            store._initialized = True
            for index in range(20):
                await store.insert("INFO", f"line {index}")
            assert store.inflight_persists == 4
            assert store.dropped_persists == 16
            gate.set()
            await store.drain(timeout=5)

        asyncio.run(scenario())

    def test_no_running_loop_is_survivable(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(log_store_module, "DB_PATH", tmp_path / "logs.db")
        store = log_store_module.LogStore()
        store._initialized = True
        # Calling the scheduler outside a loop must not raise.
        assert store._schedule_persist({"id": "x"}) is False
