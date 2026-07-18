from __future__ import annotations

import pytest

from peetsfea.backend.pyaedt.failfast import raise_on_false


def test_raise_on_false_returns_non_false_result_unchanged() -> None:
    payload = {"name": "coil_a"}
    assert raise_on_false(payload, operation="create_box") is payload


def test_raise_on_false_does_not_treat_none_as_false() -> None:
    assert raise_on_false(None, operation="optional_probe") is None


def test_raise_on_false_raises_with_operation_and_context() -> None:
    with pytest.raises(RuntimeError, match=r"PyAEDT operation returned False: save_project") as exc_info:
        raise_on_false(
            False,
            operation="save_project",
            context={"design_id": "demo_001", "path": "/tmp/demo.aedt"},
        )

    message = str(exc_info.value)
    assert "design_id='demo_001'" in message
    assert "path='/tmp/demo.aedt'" in message
