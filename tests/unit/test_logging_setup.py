"""Regression: the atexit token report must not spew a logging error when a handler's
stream was already closed (pytest closes its captured stderr at session end; the interpreter
tears streams down at exit). See engine/core/logging_setup.py:_emit_token_report.
"""
import io
import logging
import os
import sys

import pytest

_ENGINE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "engine")
if _ENGINE not in sys.path:
    sys.path.insert(0, _ENGINE)

from core import logging_setup as L  # noqa: E402


def test_emit_token_report_survives_closed_stream(monkeypatch, capsys):
    # Force a non-empty report (as on a run that actually recorded LLM tokens).
    import llm_core.tokens as tok
    monkeypatch.setattr(tok, "format_report", lambda: "LLM token usage: 42 tokens")

    # A handler bound to a stream that is then closed - exactly the shutdown scenario.
    closed = io.StringIO()
    handler = logging.StreamHandler(stream=closed)
    root = logging.getLogger()
    root.addHandler(handler)
    closed.close()
    try:
        L._emit_token_report()  # must neither raise nor trigger handleError()
    finally:
        if handler in root.handlers:
            root.removeHandler(handler)

    # The dead handler is dropped, and no "--- Logging error ---" reaches stderr.
    assert handler not in root.handlers
    assert "Logging error" not in capsys.readouterr().err
