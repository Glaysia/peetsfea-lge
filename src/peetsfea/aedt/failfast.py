from __future__ import annotations

from collections.abc import Mapping
from typing import TypeVar

T = TypeVar("T")

MAX_AEDT_NAME_LENGTH = 55
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


def validate_aedt_name(
    value: str,
    *,
    field: str = "name",
    max_length: int = MAX_AEDT_NAME_LENGTH,
) -> str:
    if len(value) > max_length:
        raise ValueError(f"AEDT {field} must be <= {max_length} characters (field={field}, length={len(value)})")
    return value
