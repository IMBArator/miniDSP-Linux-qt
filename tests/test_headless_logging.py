"""configure_logging — behaviour with and without a console.

Why these tests exist
---------------------
The packaged Windows build starts from a GUI-subsystem executable, where
Python has no console and ``sys.stderr`` is ``None``. ``logging`` copes with
that silently: every record is dropped, and an uncaught exception ends the
process without a trace. ``configure_logging`` must therefore switch to a log
file in that situation, and must keep the classic stderr handler whenever a
console is attached. The decision is made on the stream, never on the
platform, so the tests drive both paths on Linux by swapping ``sys.stderr``.
"""

from __future__ import annotations

import logging
import sys

import pytest

from minidspqt.app import LOG_FILE_NAME, configure_logging


@pytest.fixture
def attached_handlers():
    """Collect handlers a test attaches so they never leak into other tests."""
    handlers: list[logging.Handler] = []
    yield handlers
    root = logging.getLogger()
    for handler in handlers:
        root.removeHandler(handler)
        handler.close()


def test_with_console_logs_to_stderr(attached_handlers):
    handler = configure_logging(logging.INFO)
    attached_handlers.append(handler)

    assert isinstance(handler, logging.StreamHandler)
    assert not isinstance(handler, logging.FileHandler)
    assert handler.stream is sys.stderr
    assert handler in logging.getLogger().handlers
    assert logging.getLogger().level == logging.INFO


def test_without_console_logs_to_file(monkeypatch, tmp_path, attached_handlers):
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # restored on teardown

    handler = configure_logging(logging.WARNING, log_dir=tmp_path)
    attached_handlers.append(handler)

    assert isinstance(handler, logging.FileHandler)
    logging.getLogger("minidspqt.test").warning("hello from the test")
    handler.flush()
    text = (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8")
    assert "hello from the test" in text
    assert "WARN" in text


def test_without_console_uncaught_exceptions_reach_the_file(
    monkeypatch, tmp_path, attached_handlers
):
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)

    handler = configure_logging(logging.WARNING, log_dir=tmp_path)
    attached_handlers.append(handler)
    assert sys.excepthook is not sys.__excepthook__

    try:
        raise RuntimeError("boom in the event loop")
    except RuntimeError as exc:
        sys.excepthook(type(exc), exc, exc.__traceback__)
    handler.flush()

    text = (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8")
    assert "boom in the event loop" in text
    assert "Traceback" in text


def test_without_console_creates_the_log_directory(
    monkeypatch, tmp_path, attached_handlers
):
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    nested = tmp_path / "miniDSP" / "minidspqt"

    handler = configure_logging(logging.WARNING, log_dir=nested)
    attached_handlers.append(handler)

    assert (nested / LOG_FILE_NAME).exists()


def test_with_console_leaves_excepthook_alone(monkeypatch, attached_handlers):
    monkeypatch.setattr(sys, "excepthook", sys.__excepthook__)
    handler = configure_logging(logging.WARNING)
    attached_handlers.append(handler)
    assert sys.excepthook is sys.__excepthook__
