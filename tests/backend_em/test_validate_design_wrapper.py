from __future__ import annotations

import pytest

from peetsfea.aedt.wrappers import Design


def test_design_validate_design_returns_non_false_result() -> None:
    class _RawDesign:
        def ValidateDesign(self) -> int:
            return 1

    assert Design(_raw=_RawDesign()).ValidateDesign() == 1


def test_design_validate_design_raises_when_false() -> None:
    class _RawDesign:
        def ValidateDesign(self) -> bool:
            return False

    with pytest.raises(RuntimeError, match=r"PyAEDT operation returned False: ValidateDesign"):
        Design(_raw=_RawDesign()).ValidateDesign()
