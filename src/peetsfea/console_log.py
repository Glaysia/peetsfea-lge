from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime
from functools import wraps
import json
import os
import sys
from time import perf_counter
from typing import TextIO
from collections.abc import Callable
from typing import ParamSpec, TypeVar


_PEETSFEA_INFO_RGB = (46, 111, 172)
_PEETSFEA_TIMING_RGB = (190, 80, 255)
_ANSI_RESET = "\033[0m"
_CALL_DEPTH: ContextVar[int] = ContextVar("peetsfea_log_call_depth", default=0)

P = ParamSpec("P")
R = TypeVar("R")


def _supports_color(stream: TextIO) -> bool:
    if os.environ.get("NO_COLOR", "") != "":
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    return hasattr(stream, "isatty") and stream.isatty()


def _colorize(text: str, *, rgb: tuple[int, int, int], stream: TextIO) -> str:
    if not _supports_color(stream):
        return text
    return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m{text}{_ANSI_RESET}"


def _colorize_timing(text: str, *, rgb: tuple[int, int, int]) -> str:
    if os.environ.get("NO_COLOR", "") != "":
        return text
    if os.environ.get("TERM", "") == "dumb":
        return text
    return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m{text}{_ANSI_RESET}"


def _emit(level: str, message: str, *, stream: TextIO) -> None:
    prefix = _colorize(f"PeetsFEA {level}:", rgb=_PEETSFEA_INFO_RGB, stream=stream)
    stream.write(f"{prefix} {message}\n")
    stream.flush()


def _emit_timing(message: str) -> None:
    line = _colorize_timing(f"PeetsFEA INFO: {message}", rgb=_PEETSFEA_TIMING_RGB)
    sys.stdout.write(f"{line}\n")
    sys.stdout.flush()


def info(message: str) -> None:
    _emit("INFO", message, stream=sys.stdout)


def warn(message: str) -> None:
    _emit("WARN", message, stream=sys.stdout)


def error(message: str) -> None:
    _emit("ERROR", message, stream=sys.stderr)


def info_json(payload: object) -> None:
    info(json.dumps(payload, ensure_ascii=False))


def log_call_duration(func: Callable[P, R]) -> Callable[P, R]:
    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        parent_depth = _CALL_DEPTH.get()
        depth = parent_depth + 1
        token = _CALL_DEPTH.set(depth)
        start = perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            elapsed_ms = (perf_counter() - start) * 1000.0
            ended_at = datetime.now().astimezone().isoformat(timespec="milliseconds")
            _CALL_DEPTH.reset(token)
            _emit_timing(
                f"time={ended_at} stack={depth} func={func.__module__}.{func.__qualname__} elapsed_ms={elapsed_ms:.3f}"
            )

    return wrapper
