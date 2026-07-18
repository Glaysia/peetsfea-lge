from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, TypedDict

from peetsfea.errors import PeetsfeaStageError
from peetsfea.backend.pyaedt.ssw_ports import (
    HfssFactory,
    SETUP_MAXIMUM_PASSES,
    SETUP_MINIMUM_CONVERGED_PASSES,
    SETUP_MINIMUM_PASSES,
    SOLVE_HARD_ABORT_SECONDS,
    SSW_REPORT_NAMES,
    SswAedtPortStepLedger,
    SswSolveOutcome,
    SswSolveTelemetry,
    create_headless_hfss,
    make_attached_hfss_factory,
    solve_ssw_aedt_ports,
)
from peetsfea.ssw_design_space import (
    DEFAULT_REFERENCE_TOML_PATH,
    RangeValue,
    build_ssw_aedt_identity,
    sample_ssw_fixed_tomls,
)

SAMPLE_POINT_LEDGER_NAME = "sample_point_ledger.json"
SERIALIZED_INPUT_TOML_NAME = "input.toml"
AEDT_PORT_LEDGER_NAME = "ssw_aedt_port_ledger.json"
AEDT_IMPORTED_LEDGER_NAME = "ssw_aedt_imported_ledger.json"
SswRandomSampleReportMode = Literal["full"]


class SswRandomSampleReportResult(TypedDict):
    mode: SswRandomSampleReportMode
    seed: int
    dimension_count: int
    free_owner_paths: list[str]
    point_values: dict[str, RangeValue]
    design_id: str
    point_hash: str
    output_dir: str
    sampled_toml_path: str
    sample_point_ledger_path: str
    aedt_path: str
    setup_pass_counts: _SetupPassCounts
    solve_telemetry: SswSolveTelemetry
    solve_outcome: SswSolveOutcome
    csv_paths: dict[str, str]
    csv_text_by_report: dict[str, str]


class _SetupPassCounts(TypedDict):
    maximum_passes: int
    minimum_passes: int
    minimum_converged_passes: int


def _require_mode(mode: SswRandomSampleReportMode) -> None:
    if mode != "full":
        raise ValueError(f"SSW random sample report mode must be 'full' (actual={mode!r})")


def _setup_pass_counts_for_mode(mode: SswRandomSampleReportMode) -> _SetupPassCounts:
    _require_mode(mode)
    return {
        "maximum_passes": SETUP_MAXIMUM_PASSES,
        "minimum_passes": SETUP_MINIMUM_PASSES,
        "minimum_converged_passes": SETUP_MINIMUM_CONVERGED_PASSES,
    }


def _export_ssw_aedt_port_artifacts(*, source_toml_path: Path, output_dir: Path, seed: int) -> SswAedtPortStepLedger:
    from peetsfea.ssw_aedt_artifacts import export_ssw_aedt_port_artifacts

    return export_ssw_aedt_port_artifacts(source_toml_path=source_toml_path, output_dir=output_dir, seed=seed)


def _single_sample_from_batch(
    *,
    candidate_toml_path: Path,
    output_dir: Path,
    seed: int,
    reference_toml_path: Path,
) -> tuple[Path, str, str, int, tuple[str, ...], dict[str, RangeValue]]:
    batch = sample_ssw_fixed_tomls(
        sample_count=1,
        seed=seed,
        sweep_toml_path=candidate_toml_path,
        output_dir=output_dir,
        reference_toml_path=reference_toml_path,
    )
    if len(batch.samples) != 1:
        raise RuntimeError(f"SSW random sample API expected exactly one sample (actual={len(batch.samples)})")
    sample = batch.samples[0]
    identity = build_ssw_aedt_identity(sample.toml_path, reference_toml_path)
    if identity.point_hash != sample.point_hash:
        raise RuntimeError(
            "SSW sampled point hash changed after identity rebuild "
            f"(sample={sample.point_hash!r}, rebuilt={identity.point_hash!r})"
        )
    missing_paths = sorted(set(batch.free_owner_paths).difference(sample.point_values))
    if len(missing_paths) != 0:
        raise ValueError(f"SSW sampled point is missing point_values for free paths: {missing_paths}")
    return (
        sample.toml_path,
        sample.design_id,
        sample.point_hash,
        batch.dimension_count,
        batch.free_owner_paths,
        dict(sample.point_values),
    )


def _read_csv_text_by_report(csv_paths: dict[str, str]) -> dict[str, str]:
    csv_text_by_report: dict[str, str] = {}
    for report_name in SSW_REPORT_NAMES:
        if report_name not in csv_paths:
            raise ValueError(f"SSW CSV export result is missing report {report_name!r}")
        csv_path = Path(csv_paths[report_name])
        if not csv_path.is_file():
            raise FileNotFoundError(f"SSW CSV path does not exist: {csv_path}")
        csv_text_by_report[report_name] = csv_path.read_text(encoding="utf-8")
    return csv_text_by_report


def _write_sample_point_ledger(
    *,
    ledger_path: Path,
    mode: SswRandomSampleReportMode,
    seed: int,
    reference_toml_path: Path,
    candidate_toml_path: Path,
    sampled_toml_path: Path,
    dimension_count: int,
    free_owner_paths: tuple[str, ...],
    point_values: dict[str, RangeValue],
    design_id: str,
    point_hash: str,
    aedt_path: Path,
    setup_pass_counts: _SetupPassCounts,
    solve_telemetry: SswSolveTelemetry,
    solve_outcome: SswSolveOutcome,
    csv_paths: dict[str, str],
) -> None:
    ledger = {
        "mode": mode,
        "seed": seed,
        "reference_toml_path": str(reference_toml_path),
        "candidate_toml_path": str(candidate_toml_path),
        "sampled_toml_path": str(sampled_toml_path),
        "dimension_count": dimension_count,
        "free_owner_paths": list(free_owner_paths),
        "point_values": point_values,
        "design_id": design_id,
        "point_hash": point_hash,
        "aedt_path": str(aedt_path),
        "setup_pass_counts": setup_pass_counts,
        "solve_telemetry": solve_telemetry,
        "solve_outcome": solve_outcome,
        "csv_paths": csv_paths,
    }
    ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_ssw_random_sample_reports(
    candidate_toml_path: Path,
    *,
    output_dir: Path,
    seed: int,
    mode: SswRandomSampleReportMode = "full",
    reference_toml_path: Path = DEFAULT_REFERENCE_TOML_PATH,
    hfss_factory: HfssFactory = create_headless_hfss,
    keep_desktop_alive: bool = False,
    solve_hard_abort_seconds: float = SOLVE_HARD_ABORT_SECONDS,
) -> SswRandomSampleReportResult:
    _require_mode(mode)
    output_dir.mkdir(parents=True, exist_ok=True)
    (
        sampled_toml_path,
        design_id,
        point_hash,
        dimension_count,
        free_owner_paths,
        point_values,
    ) = _single_sample_from_batch(
        candidate_toml_path=candidate_toml_path,
        output_dir=output_dir,
        seed=seed,
        reference_toml_path=reference_toml_path,
    )
    port_ledger = _export_ssw_aedt_port_artifacts(source_toml_path=sampled_toml_path, output_dir=output_dir, seed=seed)
    aedt_path = output_dir / port_ledger["aedt_filename"]
    pass_counts = _setup_pass_counts_for_mode(mode)
    solve_result = solve_ssw_aedt_ports(
        port_ledger_path=output_dir / AEDT_PORT_LEDGER_NAME,
        output_aedt_path=aedt_path,
        imported_ledger_path=output_dir / AEDT_IMPORTED_LEDGER_NAME,
        design_name=design_id,
        csv_output_dir=output_dir,
        hfss_factory=hfss_factory,
        setup_maximum_passes=pass_counts["maximum_passes"],
        setup_minimum_passes=pass_counts["minimum_passes"],
        setup_minimum_converged_passes=pass_counts["minimum_converged_passes"],
        keep_desktop_alive=keep_desktop_alive,
        solve_hard_abort_seconds=solve_hard_abort_seconds,
    )
    csv_paths = solve_result["csv_paths"]
    solve_telemetry = solve_result["solve_telemetry"]
    solve_outcome = solve_result["solve_outcome"]
    csv_text_by_report = _read_csv_text_by_report(csv_paths)
    sample_point_ledger_path = output_dir / SAMPLE_POINT_LEDGER_NAME
    _write_sample_point_ledger(
        ledger_path=sample_point_ledger_path,
        mode=mode,
        seed=seed,
        reference_toml_path=reference_toml_path,
        candidate_toml_path=candidate_toml_path,
        sampled_toml_path=sampled_toml_path,
        dimension_count=dimension_count,
        free_owner_paths=free_owner_paths,
        point_values=point_values,
        design_id=design_id,
        point_hash=point_hash,
        aedt_path=aedt_path,
        setup_pass_counts=pass_counts,
        solve_telemetry=solve_telemetry,
        solve_outcome=solve_outcome,
        csv_paths=csv_paths,
    )
    return {
        "mode": mode,
        "seed": seed,
        "dimension_count": dimension_count,
        "free_owner_paths": list(free_owner_paths),
        "point_values": point_values,
        "design_id": design_id,
        "point_hash": point_hash,
        "output_dir": str(output_dir),
        "sampled_toml_path": str(sampled_toml_path),
        "sample_point_ledger_path": str(sample_point_ledger_path),
        "aedt_path": str(aedt_path),
        "setup_pass_counts": pass_counts,
        "solve_telemetry": solve_telemetry,
        "solve_outcome": solve_outcome,
        "csv_paths": csv_paths,
        "csv_text_by_report": csv_text_by_report,
    }


def run_ssw_random_sample_reports_from_toml_text(
    candidate_toml_text: str,
    *,
    output_dir: Path,
    seed: int,
    mode: SswRandomSampleReportMode = "full",
    grpc_port: int | None = None,
    aedt_pid: int | None = None,
    reference_toml_path: Path = DEFAULT_REFERENCE_TOML_PATH,
    hfss_factory: HfssFactory | None = None,
    solve_hard_abort_seconds: float = SOLVE_HARD_ABORT_SECONDS,
) -> SswRandomSampleReportResult:
    """Sample, build, solve, and report one candidate against a runner-owned ansysedt.

    When ``grpc_port`` (and optionally ``aedt_pid``) is given, the run attaches to that warm
    ansysedt, solves, and on completion closes only the project — leaving AEDT alive for the
    runner to reuse. Supply an explicit ``hfss_factory`` only for standalone/self-launching runs;
    it is mutually exclusive with ``grpc_port``/``aedt_pid``.
    """
    attach_requested = grpc_port is not None or aedt_pid is not None
    if attach_requested and hfss_factory is not None:
        raise PeetsfeaStageError(
            stage="attach",
            error_type="conflicting_hfss_source",
            message="provide either grpc_port/aedt_pid (attach) or an explicit hfss_factory, not both",
        )
    if attach_requested:
        resolved_factory = make_attached_hfss_factory(grpc_port=grpc_port, aedt_pid=aedt_pid)
        keep_desktop_alive = True
    else:
        resolved_factory = hfss_factory if hfss_factory is not None else create_headless_hfss
        keep_desktop_alive = False
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_toml_path = output_dir / SERIALIZED_INPUT_TOML_NAME
    candidate_toml_path.write_text(candidate_toml_text, encoding="utf-8")
    return run_ssw_random_sample_reports(
        candidate_toml_path,
        output_dir=output_dir,
        seed=seed,
        mode=mode,
        reference_toml_path=reference_toml_path,
        hfss_factory=resolved_factory,
        keep_desktop_alive=keep_desktop_alive,
        solve_hard_abort_seconds=solve_hard_abort_seconds,
    )


__all__ = [
    "SAMPLE_POINT_LEDGER_NAME",
    "SERIALIZED_INPUT_TOML_NAME",
    "SswRandomSampleReportMode",
    "SswRandomSampleReportResult",
    "run_ssw_random_sample_reports",
    "run_ssw_random_sample_reports_from_toml_text",
]
