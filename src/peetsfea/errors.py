"""Structured peetsfea errors for runner integration.

Every failure the runner needs to record is raised as a :class:`PeetsfeaStageError`
carrying a ``stage``, an ``error_type``, and a human-readable ``message``. The runner
maps these onto ``terminal_state="failed"`` and persists the structured triple.
"""

from __future__ import annotations

from typing import Literal, TypedDict

PeetsfeaStage = Literal[
    "validate",
    "sample",
    "attach",
    "setup",
    "solve",
    "report",
    "result",
]


class PeetsfeaErrorPayload(TypedDict):
    stage: PeetsfeaStage
    error_type: str
    message: str


class PeetsfeaStageError(RuntimeError):
    """Structured error carrying the failing stage, an error type, and a message.

    Subclasses :class:`RuntimeError` so existing ``except RuntimeError`` paths keep working while
    the runner can catch :class:`PeetsfeaStageError` to read the structured ``stage``/``error_type``.
    """

    def __init__(self, *, stage: PeetsfeaStage, error_type: str, message: str) -> None:
        if error_type == "":
            raise ValueError("PeetsfeaStageError error_type must be non-empty")
        if message == "":
            raise ValueError("PeetsfeaStageError message must be non-empty")
        super().__init__(f"[{stage}:{error_type}] {message}")
        self.stage: PeetsfeaStage = stage
        self.error_type = error_type
        self.message = message

    def as_payload(self) -> PeetsfeaErrorPayload:
        return {"stage": self.stage, "error_type": self.error_type, "message": self.message}


__all__ = [
    "PeetsfeaErrorPayload",
    "PeetsfeaStage",
    "PeetsfeaStageError",
]
