"""peetsfea package entry.

The runner depends on the public API surface re-exported here. Heavy backends
(build123d/cadquery, pyaedt) are imported lazily via :pep:`562` ``__getattr__`` so
``import peetsfea`` and ``peetsfea.__version__`` stay cheap.
"""

if not __debug__:
    raise RuntimeError("peetsfea requires assertions; python -O is unsupported")

from typing import TYPE_CHECKING, Any

from .errors import PeetsfeaErrorPayload, PeetsfeaStage, PeetsfeaStageError
from .version import __version__

if TYPE_CHECKING:
    from .ssw_design_space import (
        sample_fixed_candidates_from_toml_text,
        validate_sweep_toml_text,
    )
    from .ssw_random_sample_reports import (
        SswRandomSampleReportResult,
        run_ssw_random_sample_reports_from_toml_text,
    )

_LAZY_EXPORTS: dict[str, str] = {
    "validate_sweep_toml_text": "peetsfea.ssw_design_space",
    "sample_fixed_candidates_from_toml_text": "peetsfea.ssw_design_space",
    "run_ssw_random_sample_reports_from_toml_text": "peetsfea.ssw_random_sample_reports",
    "SswRandomSampleReportResult": "peetsfea.ssw_random_sample_reports",
}


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module_name), name)


def __dir__() -> list[str]:
    return sorted(set(__all__))


__all__ = [
    "PeetsfeaErrorPayload",
    "PeetsfeaStage",
    "PeetsfeaStageError",
    "SswRandomSampleReportResult",
    "__version__",
    "run_ssw_random_sample_reports_from_toml_text",
    "sample_fixed_candidates_from_toml_text",
    "validate_sweep_toml_text",
]
