from __future__ import annotations

import pytest

from peetsfea.console_log import log_call_duration


def test_log_call_duration_emits_function_name_elapsed_time_and_stack_depth(capsys: pytest.CaptureFixture[str]) -> None:
    @log_call_duration
    def inner() -> str:
        return "done"

    @log_call_duration
    def outer() -> str:
        return inner()

    assert outer() == "done"

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert "PeetsFEA INFO:" in lines[0]
    assert "stack=2" in lines[0]
    assert "func=tests.test_console_log.test_log_call_duration_emits_function_name_elapsed_time_and_stack_depth.<locals>.inner" in lines[0]
    assert "elapsed_ms=" in lines[0]
    assert "stack=1" in lines[1]
    assert "func=tests.test_console_log.test_log_call_duration_emits_function_name_elapsed_time_and_stack_depth.<locals>.outer" in lines[1]
    assert "elapsed_ms=" in lines[1]


def test_log_call_duration_emits_when_wrapped_function_raises(capsys: pytest.CaptureFixture[str]) -> None:
    @log_call_duration
    def broken() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        broken()

    line = capsys.readouterr().out
    assert "stack=1" in line
    assert "func=tests.test_console_log.test_log_call_duration_emits_when_wrapped_function_raises.<locals>.broken" in line
    assert "elapsed_ms=" in line
