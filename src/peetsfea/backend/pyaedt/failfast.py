from __future__ import annotations

from collections.abc import Mapping
from typing import TypeVar

T = TypeVar("T")
_EMPTY_CONTEXT: Mapping[str, object] = {}


def _format_context(context: Mapping[str, object]) -> str:
    if not context:
        return ""
    parts: list[str] = []
    for key, value in context.items():
        parts.append(f"{key}={value!r}")
    return f" ({', '.join(parts)})"


def raise_on_false(
    result: T,
    *,
    operation: str,
    context: Mapping[str, object] = _EMPTY_CONTEXT,
) -> T:
    """Raise when a PyAEDT boundary reports failure with the boolean value ``False``."""
    if result is False:
        raise RuntimeError(f"PyAEDT operation returned False: {operation}{_format_context(context)}")
    return result
