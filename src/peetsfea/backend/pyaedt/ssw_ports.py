from __future__ import annotations

from datetime import datetime
import json
import multiprocessing
from pathlib import Path
from collections.abc import Sequence
import shutil
import socket
import subprocess
import threading
import time
from typing import Callable, Literal, NotRequired, Protocol, TypeAlias, TypedDict, cast

import psutil
from ansys.aedt.core.generic.settings import settings as pyaedt_settings

from peetsfea.aedt import Hfss
from peetsfea.aedt.failfast import raise_on_false
from peetsfea.errors import PeetsfeaStageError
from peetsfea.aedt.protocols import (
    AnalysisSetupModuleSession,
    DesignSession,
    HfssSession,
    MaterialsSession,
    MeshModuleSession,
    ModelerSession,
    ReportSetupModuleSession,
    SolutionsModuleSession,
)
from peetsfea.aedt.proxies import assign_lumped_port, edit_sources, set_object_color, set_object_transparency

DEFAULT_LEDGER_PATH = Path(__file__).resolve().parents[4] / "run" / "ssw_0_3_0_fixed" / "ssw_aedt_port_ledger.json"
COPPER_COLOR = (184, 115, 51)
COPPER_TRANSPARENCY = 0.0
NON_MODEL_COLOR = (128, 128, 128)
NON_MODEL_TRANSPARENCY = 0.85
FR4_MATERIAL = "fr4"
FR4_PERMITTIVITY = "4.4"
FR4_CONDUCTIVITY = "0"
FR4_DIELECTRIC_LOSS_TANGENT = "0.02"
MULL_FERRITE_ALIAS = "mull_ferrite"
MULL_FERRITE_MATERIAL = "MULL12060ferrite"
MULL_FERRITE_APPEARANCE_RGB = (89, 94, 107)
NOTEBOOK_DATASET_IMPORT_PATH = Path(__file__).resolve().parents[2] / "data" / "mu_p.tab"
MU_R_REAL_DATASET_NAME = "$mu_r_real"
MU_TAND_M_DATASET_NAME = "$mu_tand_m"
MU_R_REAL_DATASET_POINTS = (
    (0.001, 133.0),
    (0.003, 134.0),
    (0.005, 135.0),
    (0.008, 136.0),
    (0.01, 137.0),
    (0.012, 142.0),
    (0.015, 152.0),
    (0.018, 160.0),
    (0.02, 166.0),
    (0.025, 150.0),
    (0.03, 130.0),
    (0.04, 100.0),
    (0.05, 82.0),
    (0.07, 65.0),
    (0.1, 50.0),
    (0.15, 35.0),
    (0.2, 25.0),
    (0.3, 15.0),
    (0.5, 10.0),
    (0.7, 11.0),
    (1.0, 18.0),
)
MU_TAND_M_DATASET_POINTS = (
    (0.001, 0.0),
    (0.003, 0.0),
    (0.005, 0.0),
    (0.008, 0.00367647),
    (0.01, 0.00729927),
    (0.012, 0.0140845),
    (0.015, 0.0328947),
    (0.018, 0.075),
    (0.02, 0.150602),
    (0.025, 0.4),
    (0.03, 0.553846),
    (0.04, 0.76),
    (0.05, 0.890244),
    (0.07, 1.01538),
    (0.1, 1.16),
    (0.15, 1.42857),
    (0.2, 1.8),
    (0.3, 2.46667),
    (0.5, 2.8),
    (0.7, 2.0),
    (1.0, 1.0),
)
MESH_MODULE_NAME = "MeshSetup"
ANALYSIS_MODULE_NAME = "AnalysisSetup"
MESH_OPERATION_NAME = "Length1"
MESH_RX_COPPER_CANDIDATES = ("rx_ssw_coil_coil_copper", "rx_ssw_coil_ssw_copper")
MESH_TX_COPPER_NAME = "tx_ssw_coil_ssw_copper"
MESH_MAX_LENGTH_FALLBACK_MM = 3.0
MESH_MAX_ELEMENTS = "20000"
SETUP_NAME = "Setup1"
SWEEP_NAME = "Sweep"
SETUP_FREQUENCY = "6.78MHz"
SETUP_MAX_DELTA_S = 0.003
SWEEP_RANGE_START = "0.1MHz"
SWEEP_RANGE_END = "100MHz"
SWEEP_RANGE_COUNT = 81
RADIATION_MARGIN_MM = 2000.0
RESULTS1_PASS_REPORT_NAME = "Results1_Pass"
RESULTS2_LAST_REPORT_NAME = "Results2_Last"
RESULTS3_FREQ_REPORT_NAME = "Results3_Freq"
SSW_REPORT_NAMES = (RESULTS1_PASS_REPORT_NAME, RESULTS2_LAST_REPORT_NAME, RESULTS3_FREQ_REPORT_NAME)
TX_SOURCE_MAGNITUDE = "100V"
TX_SOURCE_PHASE = "0deg"
RX_SOURCE_MAGNITUDE = "100V"
RX_SOURCE_PHASE = "90deg"
SETUP_MAXIMUM_PASSES = 16
SETUP_MINIMUM_PASSES = 16
SETUP_MINIMUM_CONVERGED_PASSES = 16
SETUP_PERCENT_REFINEMENT = 20
SOLVE_TELEMETRY_SAMPLE_INTERVAL_SECONDS = 2.0
SOLVE_TELEMETRY_SAMPLES_JSONL_NAME = "ssw_solve_telemetry_samples.jsonl"
SOLVE_TELEMETRY_STOP_NAME = "ssw_solve_telemetry.stop"
SOLVE_HARD_ABORT_SECONDS = 3600.0
SOLVE_ABORT_GRACE_SECONDS = 120.0
SOLVE_CORES = 6
GPU_DETECT_TIMEOUT_SECONDS = 20.0
SOLVE_FALLBACK_MIN_SECONDS = 60.0

_TXRX_OUTPUT_VARIABLE_EXPRESSIONS: tuple[tuple[str, str], ...] = (
    ("Ltx_uH", "im(Zt(TX_TML,TX_TML))/2/pi/freq*1e6"),
    ("Lrx_uH", "im(Zt(RX_TML,RX_TML))/2/pi/freq*1e6"),
    ("M_uH", "abs(im(Zt(TX_TML,RX_TML))/2/pi/freq*1e6)"),
    ("k_ratio", "M_uH/sqrt(Ltx_uH*Lrx_uH)"),
    ("Qtx_ratio", "im(Zt(TX_TML,TX_TML))/re(Zt(TX_TML,TX_TML))"),
    ("Qrx_ratio", "im(Zt(RX_TML,RX_TML))/re(Zt(RX_TML,RX_TML))"),
    ("FOM_ratio", "k_ratio*sqrt(Qtx_ratio*Qrx_ratio)"),
    ("re_Z11_ohm", "re(Zt(TX_TML,TX_TML))"),
    ("im_Z11_ohm", "im(Zt(TX_TML,TX_TML))"),
    ("re_Z22_ohm", "re(Zt(RX_TML,RX_TML))"),
    ("im_Z22_ohm", "im(Zt(RX_TML,RX_TML))"),
    ("re_Z12_ohm", "re(Zt(TX_TML,RX_TML))"),
    ("im_Z12_ohm", "im(Zt(TX_TML,RX_TML))"),
    ("M_over_Ltx_ratio", "M_uH/Ltx_uH"),
    ("M_over_Lrx_ratio", "M_uH/Lrx_uH"),
    (
        "eta_fom_max_ratio",
        "(FOM_ratio*FOM_ratio)/((1+sqrt(1+FOM_ratio*FOM_ratio))*(1+sqrt(1+FOM_ratio*FOM_ratio)))",
    ),
)

Point3 = tuple[float, float, float]
HfssFactory = Callable[[str], HfssSession]
PortRole = Literal["tx", "rx"]
BoundaryPayloadName = Literal["NAME:1", "NAME:2"]
ExpectedTerminalName = Literal["1_T1", "2_T1"]


class FieldsReporterSession(Protocol):
    def CalcStack(self, command: str) -> object: ...

    def CopyNamedExprToStack(self, expression_name: str) -> object: ...

    def EnterVol(self, assignment: str) -> object: ...

    def CalcOp(self, operation: str) -> object: ...

    def AddNamedExpression(self, expression_name: str, field_type: str) -> object: ...


class CanonicalCoordinates(TypedDict):
    outer_bounds_min_xyz: list[float]
    outer_bounds_max_xyz: list[float]
    outer_bounds_size_xyz: list[float]


class SswAedtBodyLedgerEntry(TypedDict):
    object_id: str
    role: str
    material: str
    model_state: bool
    canonical_coordinates: CanonicalCoordinates


class SswSemanticPortEdgeLedgerEntry(TypedDict):
    role: PortRole
    copper_body_name: str
    selection: Literal["semantic_edge_vertices"]
    edge_vertices_xyz: list[list[list[float]]]


SswAedtPortEdgeLedgerEntry: TypeAlias = SswSemanticPortEdgeLedgerEntry


class SswAedtPortStepLedger(TypedDict):
    design_id: str
    aedt_filename: str
    dimension_count: int
    design_space_hash: str
    source_step_ledger_path: str
    scene_step_path: str
    seed: int
    units: Literal["mm"]
    body_names: list[str]
    copper_body_names: list[str]
    fr4_body_names: list[str]
    non_model_body_names: list[str]
    ferrite_body_names: list[str]
    bodies: list[SswAedtBodyLedgerEntry]
    port_edges: list[SswAedtPortEdgeLedgerEntry]
    mesh_max_length: NotRequired[str]


class VisualAssignment(TypedDict):
    color: list[int]
    transparency: float


class SswAedtMeshSummary(TypedDict):
    module_name: str
    operation: str
    operation_name: str
    objects: list[str]
    refine_inside: bool
    enabled: bool
    restrict_elem: bool
    num_max_elem: str
    restrict_length: bool
    max_length: str


class SswAedtAnalysisSetupSummary(TypedDict):
    module_name: str
    operation: str
    setup_type: str
    setup_name: str
    frequency: str
    max_delta_s: float
    maximum_passes: int
    minimum_passes: int
    minimum_converged_passes: int
    percent_refinement: int
    basis_order: int
    port_accuracy: int
    driven_solver_type: str


class SswAedtFrequencySweepSummary(TypedDict):
    module_name: str
    operation: str
    setup_name: str
    sweep_name: str
    range_type: str
    range_start: str
    range_end: str
    range_count: int
    sweep_type: str


class SswAedtSourcesSummary(TypedDict):
    tx_source_name: str
    tx_magnitude: str
    tx_phase_deg: str
    rx_source_name: str
    rx_magnitude: str
    rx_phase_deg: str


class SswAedtBoundarySummary(TypedDict):
    type: Literal["radiation"]
    offset_type: str
    offset_value: str
    region_name: str
    face_count: str
    boundary_names: list[str]


class SswAedtReportsSummary(TypedDict):
    report_names: list[str]
    output_variable_names: list[str]
    solid_loss_expression_names: list[str]
    output_solution_name: str
    solid_loss_solution_name: str
    diagnostic_report_names: list[str]


class SswAedtImportedLedgerBase(TypedDict):
    design_id: str
    aedt_filename: str
    dimension_count: int
    design_space_hash: str
    source_port_ledger_path: str
    source_step_ledger_path: str
    scene_step_path: str
    aedt_path: str
    imported_object_names: list[str]
    copper_body_names: list[str]
    fr4_body_names: list[str]
    material_assignments: dict[str, str]
    visual_assignments: dict[str, VisualAssignment]
    non_model_body_names: list[str]
    ferrite_body_names: list[str]
    mesh: SswAedtMeshSummary


class SswAedtImportedLedger(SswAedtImportedLedgerBase):
    boundary: SswAedtBoundarySummary
    analysis_setup: SswAedtAnalysisSetupSummary
    frequency_sweep: SswAedtFrequencySweepSummary
    sources: SswAedtSourcesSummary
    reports: SswAedtReportsSummary


class SswAedtPorts(TypedDict):
    tx: list[str]
    rx: list[str]


class SswAedtPortSetupResult(TypedDict):
    design_id: str
    aedt_filename: str
    dimension_count: int
    design_space_hash: str
    source_port_ledger_path: str
    source_step_ledger_path: str
    scene_step_path: str
    aedt_path: str
    imported_ledger_path: str
    ports: SswAedtPorts
    imported_object_names: list[str]
    mesh: SswAedtMeshSummary
    boundary: SswAedtBoundarySummary
    analysis_setup: SswAedtAnalysisSetupSummary
    frequency_sweep: SswAedtFrequencySweepSummary
    sources: SswAedtSourcesSummary
    reports: SswAedtReportsSummary


class SswProcessResourceSample(TypedDict):
    pid: int
    name: str
    cpu_percent: float
    rss_bytes: int
    vms_bytes: int


class SswSolveTelemetrySample(TypedDict):
    timestamp: str
    elapsed_ms: float
    aedt_process_id: int
    reported_aedt_process_id: int
    process_count: int
    pids: list[int]
    cpu_percent_total: float
    rss_bytes_total: int
    vms_bytes_total: int
    processes: list[SswProcessResourceSample]


class SswSolveTelemetry(TypedDict):
    started_at: str
    finished_at: str
    elapsed_ms: float
    aedt_process_id: int
    reported_aedt_process_id: int
    sample_interval_seconds: float
    samples_jsonl_path: str
    sample_count: int
    peak_cpu_percent_total: float
    peak_rss_bytes_total: int
    peak_vms_bytes_total: int
    gpu_used: bool
    gpu_device_name: str
    solver_cores: int
    samples: list[SswSolveTelemetrySample]


class SswSolverResources(TypedDict):
    gpu_count: int
    gpu_device_name: str
    cores: int


def _detect_gpus() -> tuple[int, str]:
    """Best-effort GPU detection via ``nvidia-smi``. Returns (count, first_device_name)."""
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is None:
        return (0, "")
    try:
        completed = subprocess.run(
            [nvidia_smi, "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=GPU_DETECT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return (0, "")
    if completed.returncode != 0:
        return (0, "")
    names = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if len(names) == 0:
        return (0, "")
    return (len(names), names[0])


def detect_solver_resources() -> SswSolverResources:
    """Resolve solver resources at solve time: fixed ``cores`` plus auto-detected GPUs."""
    gpu_count, gpu_device_name = _detect_gpus()
    return {"gpu_count": gpu_count, "gpu_device_name": gpu_device_name, "cores": SOLVE_CORES}


class SswSolveOutcome(TypedDict):
    completed: bool
    hard_aborted: bool
    hard_abort_seconds: float
    analyze_elapsed_ms: float


class SswAedtReportCsvResult(TypedDict):
    setup: SswAedtPortSetupResult
    csv_paths: dict[str, str]
    solve_telemetry: SswSolveTelemetry
    solve_outcome: SswSolveOutcome


def create_headless_hfss(design_name: str) -> HfssSession:
    # 0.3.9.5: wait for an Ansys license instead of failing immediately when none
    # is free (adds -waitforlicense at Desktop launch); pairs with the 6-core cap.
    pyaedt_settings.wait_for_license = True
    return cast(HfssSession, Hfss(design=design_name, non_graphical=True, new_desktop=True, close_on_exit=False))


def create_graphical_hfss(design_name: str) -> HfssSession:
    pyaedt_settings.wait_for_license = True
    return cast(HfssSession, Hfss(design=design_name, non_graphical=False, new_desktop=True, close_on_exit=False))


DEFAULT_ATTACH_HOST = "127.0.0.1"
ATTACH_PROBE_TIMEOUT_SECONDS = 5.0


def _grpc_port_is_listening(host: str, port: int, timeout_seconds: float = ATTACH_PROBE_TIMEOUT_SECONDS) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def _attach_hfss_via_port(*, design_name: str, host: str, grpc_port: int) -> HfssSession:
    return cast(
        HfssSession,
        Hfss(
            design=design_name,
            non_graphical=True,
            new_desktop=False,
            close_on_exit=False,
            machine=host,
            port=grpc_port,
        ),
    )


def _attach_hfss_via_pid(*, design_name: str, aedt_pid: int) -> HfssSession:
    return cast(
        HfssSession,
        Hfss(
            design=design_name,
            non_graphical=True,
            new_desktop=False,
            close_on_exit=False,
            aedt_process_id=aedt_pid,
        ),
    )


def make_attached_hfss_factory(
    *,
    grpc_port: int | None,
    aedt_pid: int | None = None,
    host: str = DEFAULT_ATTACH_HOST,
) -> HfssFactory:
    """Build an :data:`HfssFactory` that attaches to an already-running ansysedt.

    The runner keeps a warm, license-holding ansysedt and lends it via ``grpc_port`` (and
    optionally ``aedt_pid``). The factory never starts or stops AEDT: it attaches with
    ``new_desktop=False`` and ``close_on_exit=False``, trying the gRPC ``port`` first and the
    ``pid`` second. When neither attaches it raises :class:`PeetsfeaStageError` (stage
    ``"attach"``) so the runner can mark that ansysedt unusable, recycle it, and retry.
    """
    if grpc_port is None and aedt_pid is None:
        raise PeetsfeaStageError(
            stage="attach",
            error_type="missing_attach_target",
            message="attaching to an existing ansysedt requires a grpc_port or an aedt_pid",
        )
    if grpc_port is not None and (isinstance(grpc_port, bool) or not isinstance(grpc_port, int) or grpc_port <= 0):
        raise PeetsfeaStageError(
            stage="attach",
            error_type="invalid_grpc_port",
            message=f"grpc_port must be a positive int (actual={grpc_port!r})",
        )
    if aedt_pid is not None and (isinstance(aedt_pid, bool) or not isinstance(aedt_pid, int) or aedt_pid <= 0):
        raise PeetsfeaStageError(
            stage="attach",
            error_type="invalid_aedt_pid",
            message=f"aedt_pid must be a positive int (actual={aedt_pid!r})",
        )

    def factory(design_name: str) -> HfssSession:
        failures: list[str] = []
        if grpc_port is not None:
            if _grpc_port_is_listening(host, grpc_port):
                try:
                    return _attach_hfss_via_port(design_name=design_name, host=host, grpc_port=grpc_port)
                except Exception as exc:  # noqa: BLE001 — attach failure must surface structured
                    failures.append(f"grpc_port {grpc_port}: {type(exc).__name__}: {exc}")
            else:
                failures.append(f"grpc_port {grpc_port}: no listener on {host}:{grpc_port}")
        if aedt_pid is not None:
            if psutil.pid_exists(aedt_pid):
                try:
                    return _attach_hfss_via_pid(design_name=design_name, aedt_pid=aedt_pid)
                except Exception as exc:  # noqa: BLE001 — attach failure must surface structured
                    failures.append(f"aedt_pid {aedt_pid}: {type(exc).__name__}: {exc}")
            else:
                failures.append(f"aedt_pid {aedt_pid}: process not found")
        raise PeetsfeaStageError(
            stage="attach",
            error_type="aedt_unreachable",
            message="could not attach to a running ansysedt (" + "; ".join(failures) + ")",
        )

    return factory


def _release_keeping_desktop_alive(hfss: HfssSession) -> None:
    """Close only the active project and detach, leaving the borrowed ansysedt running."""
    project_name = hfss.project_name
    hfss.close_project(project_name, save=False)
    raise_on_false(
        hfss.desktop_class.release_desktop(close_projects=False, close_on_exit=False),
        operation="release_desktop",
        context={"close_projects": False, "close_on_exit": False},
    )


class _AnalyzeAttempt(TypedDict):
    status: Literal["completed", "aborted", "failed"]
    error: str


def _run_analyze_attempt(
    *,
    hfss: HfssSession,
    setup_name: str,
    cores: int,
    gpus: int,
    deadline_seconds: float,
    abort_grace_seconds: float,
) -> _AnalyzeAttempt:
    """Run one ``analyze_setup`` attempt under the hard-abort watchdog.

    ``analyze_setup`` blocks AEDT until convergence, so it runs on a worker thread while the caller
    enforces ``deadline_seconds``. On timeout the watchdog issues ``stop_simulations(clean_stop=True)``
    so the last completed pass stays solved and exportable.
    """
    worker_error: dict[str, str] = {}

    def _worker() -> None:
        try:
            raise_on_false(
                hfss.analyze_setup(setup_name, blocking=True, cores=cores, gpus=gpus),
                operation="analyze_setup",
                context={"setup_name": setup_name, "cores": cores, "gpus": gpus},
            )
        except BaseException as exc:  # noqa: BLE001 — propagate to the caller thread via the dict
            worker_error["message"] = f"{type(exc).__name__}: {exc}"

    worker = threading.Thread(target=_worker, name="ssw-analyze-setup", daemon=True)
    worker.start()
    worker.join(timeout=deadline_seconds)
    if worker.is_alive():
        hfss.stop_simulations(clean_stop=True)
        worker.join(timeout=abort_grace_seconds)
        return {"status": "aborted", "error": ""}
    if "message" in worker_error:
        return {"status": "failed", "error": worker_error["message"]}
    return {"status": "completed", "error": ""}


def _analyze_with_hard_abort(
    *,
    hfss: HfssSession,
    setup_name: str,
    hard_abort_seconds: float,
    cores: int,
    gpus: int,
    abort_grace_seconds: float = SOLVE_ABORT_GRACE_SECONDS,
) -> tuple[SswSolveOutcome, bool]:
    """Analyze with the hard-abort watchdog, auto-enabling GPU and falling back to CPU.

    When ``gpus > 0`` the first attempt enables GPU acceleration. If that attempt *fails* (e.g. no
    HPC Pack license or driver issue — distinct from a timeout abort), it silently retries on CPU
    (``gpus=0``) with the remaining time budget so the job still completes. Returns the outcome and
    whether GPU acceleration was actually used.
    """
    started = time.monotonic()
    attempt = _run_analyze_attempt(
        hfss=hfss,
        setup_name=setup_name,
        cores=cores,
        gpus=gpus,
        deadline_seconds=hard_abort_seconds,
        abort_grace_seconds=abort_grace_seconds,
    )
    gpu_used = gpus > 0 and attempt["status"] != "failed"
    if attempt["status"] == "failed" and gpus > 0:
        remaining = max(SOLVE_FALLBACK_MIN_SECONDS, hard_abort_seconds - (time.monotonic() - started))
        attempt = _run_analyze_attempt(
            hfss=hfss,
            setup_name=setup_name,
            cores=cores,
            gpus=0,
            deadline_seconds=remaining,
            abort_grace_seconds=abort_grace_seconds,
        )
        gpu_used = False
    elapsed_ms = (time.monotonic() - started) * 1000.0
    if attempt["status"] == "failed":
        raise PeetsfeaStageError(stage="solve", error_type="analyze_failed", message=attempt["error"])
    outcome: SswSolveOutcome = {
        "completed": attempt["status"] == "completed",
        "hard_aborted": attempt["status"] == "aborted",
        "hard_abort_seconds": hard_abort_seconds,
        "analyze_elapsed_ms": elapsed_ms,
    }
    return outcome, gpu_used


def write_ssw_aedt_port_ledger(*, ledger_path: Path, ledger: SswAedtPortStepLedger) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_ssw_aedt_port_ledger(ledger_path: Path) -> SswAedtPortStepLedger:
    raw_ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if not isinstance(raw_ledger, dict):
        raise TypeError(f"SSW AEDT port ledger must be a JSON object: {ledger_path}")
    for key in (
        "design_id",
        "aedt_filename",
        "dimension_count",
        "design_space_hash",
        "source_step_ledger_path",
        "scene_step_path",
        "seed",
        "units",
        "body_names",
        "copper_body_names",
        "non_model_body_names",
        "ferrite_body_names",
        "bodies",
        "port_edges",
    ):
        if key not in raw_ledger:
            raise ValueError(f"SSW AEDT port ledger is missing required key {key!r}: {ledger_path}")
    return cast(SswAedtPortStepLedger, raw_ledger)


def _required_str_list(ledger: SswAedtPortStepLedger, *, key: str) -> list[str]:
    raw_value = ledger[key]
    if isinstance(raw_value, (str, bytes)) or not isinstance(raw_value, list):
        raise TypeError(f"SSW AEDT port ledger {key} must be a list of strings")
    names: list[str] = []
    for index, raw_name in enumerate(raw_value):
        if not isinstance(raw_name, str):
            raise TypeError(f"SSW AEDT port ledger {key}[{index}] must be str")
        if raw_name == "":
            raise ValueError(f"SSW AEDT port ledger {key}[{index}] must be non-empty")
        names.append(raw_name)
    return names


def _body_materials_by_object_id(ledger: SswAedtPortStepLedger) -> dict[str, str]:
    raw_bodies = ledger["bodies"]
    if isinstance(raw_bodies, (str, bytes)) or not isinstance(raw_bodies, list):
        raise TypeError("SSW AEDT port ledger bodies must be a list")
    body_materials: dict[str, str] = {}
    for index, raw_body in enumerate(raw_bodies):
        if not isinstance(raw_body, dict):
            raise TypeError(f"SSW AEDT port ledger bodies[{index}] must be object")
        if "object_id" not in raw_body:
            raise ValueError(f"SSW AEDT port ledger bodies[{index}] is missing object_id")
        if "material" not in raw_body:
            raise ValueError(f"SSW AEDT port ledger bodies[{index}] is missing material")
        raw_object_id = raw_body["object_id"]
        raw_material = raw_body["material"]
        if not isinstance(raw_object_id, str) or raw_object_id == "":
            raise TypeError(f"SSW AEDT port ledger bodies[{index}].object_id must be non-empty str")
        if not isinstance(raw_material, str) or raw_material == "":
            raise TypeError(f"SSW AEDT port ledger bodies[{index}].material must be non-empty str")
        if raw_object_id in body_materials:
            raise ValueError(f"SSW AEDT port ledger contains duplicate body object_id {raw_object_id!r}")
        body_materials[raw_object_id] = raw_material
    return body_materials


def _assign_object_material(*, hfss: HfssSession, modeler: ModelerSession, object_name: str, material: str) -> str:
    raw_materials = hfss.materials
    assert hasattr(raw_materials, "exists_material"), "Hfss.materials must expose exists_material"
    materials = cast(MaterialsSession, raw_materials)
    raise_on_false(
        materials.exists_material(material),
        operation="Materials.exists_material",
        context={"object_name": object_name, "material": material},
    )
    raise_on_false(
        hfss.assign_material(object_name, material),
        operation="assign_material",
        context={"object_name": object_name, "material": material},
    )
    imported_object = raise_on_false(
        modeler.get_object_from_name(object_name),
        operation="get_object_from_name",
        context={"object_name": object_name},
    )
    assert hasattr(imported_object, "material_name"), (
        f"Imported AEDT object must expose material_name before material assignment (object_name={object_name})"
    )
    assigned_material = getattr(imported_object, "material_name")
    assert isinstance(assigned_material, str), (
        f"Imported AEDT object material_name must read back as str (object_name={object_name})"
    )
    if assigned_material.lower() != material.lower():
        raise RuntimeError(
            "AEDT object material assignment did not stick "
            f"(object_name={object_name}, expected={material!r}, actual={assigned_material!r})"
        )
    return assigned_material


def _set_imported_object_solve_inside(*, modeler: ModelerSession, object_name: str, solve_inside: bool) -> None:
    imported_object = raise_on_false(
        modeler.get_object_from_name(object_name),
        operation="get_object_from_name",
        context={"object_name": object_name},
    )
    assert hasattr(imported_object, "solve_inside"), (
        f"Imported AEDT object must expose solve_inside before solve-inside assignment (object_name={object_name})"
    )
    raw_imported_object = _unwrap_raw(imported_object, context=f"modeler.get_object_from_name({object_name})")
    setattr(raw_imported_object, "solve_inside", solve_inside)
    assigned_solve_inside = object.__getattribute__(raw_imported_object, "solve_inside")
    assert isinstance(assigned_solve_inside, bool), (
        f"Imported AEDT object solve_inside must read back as bool (object_name={object_name})"
    )
    if assigned_solve_inside is not solve_inside:
        raise RuntimeError(
            "AEDT object solve_inside assignment did not stick "
            f"(object_name={object_name}, expected={solve_inside!r}, actual={assigned_solve_inside!r})"
        )


def _set_material_property(material: object, *, material_name: str, attr_name: str, attr_value: str) -> None:
    try:
        setattr(material, attr_name, attr_value)
    except Exception as exc:
        raise RuntimeError(
            "Failed to configure AEDT material property "
            f"(material={material_name}, property={attr_name}, value={attr_value!r})"
        ) from exc


def _unwrap_raw(value: object, *, context: str) -> object:
    if hasattr(value, "_raw"):
        raw_value = object.__getattribute__(value, "_raw")
        assert raw_value is not None, f"{context}._raw must not be null"
        return raw_value
    return value


def _dataset_payload(dataset_name: str, *, points: tuple[tuple[float, float], ...]) -> list[object]:
    payload: list[object] = [
        f"NAME:{dataset_name}",
        [
            "NAME:Coordinates",
            ["NAME:DimUnits", "GHz", "fraction"],
        ],
    ]
    coordinates = payload[1]
    assert isinstance(coordinates, list), "dataset payload coordinates container must be a list"
    for frequency_ghz, value in points:
        coordinates.append(["NAME:Point", frequency_ghz, value])
    return payload


def _raw_project(hfss: HfssSession) -> object:
    raw_hfss = _unwrap_raw(hfss, context="hfss")
    assert hasattr(raw_hfss, "oproject"), "HFSS session must expose raw oproject for dataset-backed ferrite setup"
    raw_project = getattr(raw_hfss, "oproject")
    assert raw_project is not None, "HFSS raw oproject must not be null"
    return raw_project


def _raw_design(hfss: HfssSession) -> object:
    return _unwrap_raw(hfss.odesign, context="hfss.odesign")


def _raw_materials(hfss: HfssSession) -> object:
    return _unwrap_raw(hfss.materials, context="hfss.materials")


def _materials_session(hfss: HfssSession) -> MaterialsSession:
    return cast(MaterialsSession, _unwrap_raw(hfss.materials, context="hfss.materials"))


def _material_ref_from_material_keys(hfss: HfssSession, *, material_name: str) -> object | None:
    material_keys = _materials_session(hfss).material_keys
    normalized_name = material_name.casefold()
    if normalized_name not in material_keys:
        return None
    return material_keys[normalized_name]


def _definition_manager(raw_project: object) -> object:
    assert hasattr(raw_project, "GetDefinitionManager"), (
        f"Raw project must expose GetDefinitionManager (project_type={type(raw_project).__name__})"
    )
    get_definition_manager = getattr(raw_project, "GetDefinitionManager")
    assert callable(get_definition_manager), "Raw project GetDefinitionManager must be callable"
    definition_manager = get_definition_manager()
    assert definition_manager is not None, "Raw project definition manager must not be null"
    return definition_manager


def _project_material_names(definition_manager: object) -> list[str]:
    assert hasattr(definition_manager, "GetProjectMaterialNames"), (
        "Definition manager must expose GetProjectMaterialNames "
        f"(definition_manager_type={type(definition_manager).__name__})"
    )
    get_project_material_names = getattr(definition_manager, "GetProjectMaterialNames")
    assert callable(get_project_material_names), "Definition manager GetProjectMaterialNames must be callable"
    raw_names = get_project_material_names()
    assert isinstance(raw_names, Sequence), (
        "Definition manager GetProjectMaterialNames result must be a sequence "
        f"(actual={type(raw_names).__name__})"
    )
    assert not isinstance(raw_names, (str, bytes)), "Definition manager GetProjectMaterialNames must not be str/bytes"
    names: list[str] = []
    for index, raw_name in enumerate(raw_names):
        assert isinstance(raw_name, str), (
            "Definition manager GetProjectMaterialNames items must be str "
            f"(index={index}, actual={type(raw_name).__name__})"
        )
        if raw_name == "":
            raise ValueError(f"Definition manager GetProjectMaterialNames returned empty name at index {index}")
        names.append(raw_name)
    return names


def _dataset_ferrite_material_payload() -> list[object]:
    red, green, blue = MULL_FERRITE_APPEARANCE_RGB
    return [
        f"NAME:{MULL_FERRITE_MATERIAL}",
        "CoordinateSystemType:=",
        "Cartesian",
        "BulkOrSurfaceType:=",
        1,
        [
            "NAME:PhysicsTypes",
            "set:=",
            ["Electromagnetic", "Thermal", "Structural"],
        ],
        [
            "NAME:AttachedData",
            [
                "NAME:MatAppearanceData",
                "property_data:=",
                "appearance_data",
                "Red:=",
                red,
                "Green:=",
                green,
                "Blue:=",
                blue,
            ],
        ],
        "permittivity:=",
        "6",
        "permeability:=",
        f"pwlx({MU_R_REAL_DATASET_NAME}, Freq)",
        "conductivity:=",
        "0.01",
        "magnetic_loss_tangent:=",
        f"pwlx({MU_TAND_M_DATASET_NAME}, Freq)",
        "thermal_conductivity:=",
        "4",
        "mass_density:=",
        "4600",
        "specific_heat:=",
        "750",
        "youngs_modulus:=",
        "119000000000",
        "thermal_expansion_coefficient:=",
        "1e-05",
    ]


def _ensure_project_dataset_ferrite_material_definition(hfss: HfssSession) -> None:
    definition_manager = _definition_manager(_raw_project(hfss))
    payload = _dataset_ferrite_material_payload()
    material_names = _project_material_names(definition_manager)
    existing_case_name = next(
        (name for name in material_names if name.casefold() == MULL_FERRITE_MATERIAL.casefold()),
        None,
    )
    if existing_case_name is None:
        assert hasattr(definition_manager, "AddMaterial"), (
            "Definition manager must expose AddMaterial "
            f"(definition_manager_type={type(definition_manager).__name__})"
        )
        add_material = getattr(definition_manager, "AddMaterial")
        assert callable(add_material), "Definition manager AddMaterial must be callable"
        add_material(payload)
    else:
        assert hasattr(definition_manager, "EditMaterial"), (
            "Definition manager must expose EditMaterial "
            f"(definition_manager_type={type(definition_manager).__name__})"
        )
        edit_material = getattr(definition_manager, "EditMaterial")
        assert callable(edit_material), "Definition manager EditMaterial must be callable"
        edit_material(existing_case_name, payload)
    persisted_names = _project_material_names(definition_manager)
    if not any(name.casefold() == MULL_FERRITE_MATERIAL.casefold() for name in persisted_names):
        raise RuntimeError(
            "Project ferrite material definition was not persisted after AddMaterial/EditMaterial "
            f"(material_name={MULL_FERRITE_MATERIAL})"
        )


def _sync_pyaedt_material_lookup(hfss: HfssSession, *, material_name: str) -> None:
    if _material_ref_from_material_keys(hfss, material_name=material_name) is not None:
        return
    raw_materials = _raw_materials(hfss)
    assert hasattr(raw_materials, "_aedmattolibrary"), (
        "Raw materials must expose _aedmattolibrary for post-definition material sync "
        f"(materials_type={type(raw_materials).__name__})"
    )
    sync_material = getattr(raw_materials, "_aedmattolibrary")
    assert callable(sync_material), "Raw materials _aedmattolibrary must be callable"
    sync_material(material_name)
    if _material_ref_from_material_keys(hfss, material_name=material_name) is None:
        raise RuntimeError(
            "PyAEDT materials lookup did not resolve ferrite material after project definition sync "
            f"(material_name={material_name})"
        )


def _ensure_notebook_dataset_ferrite_material(hfss: HfssSession) -> str:
    if not NOTEBOOK_DATASET_IMPORT_PATH.is_file():
        raise FileNotFoundError(f"Notebook ferrite dataset tab file is missing: {NOTEBOOK_DATASET_IMPORT_PATH}")

    raw_design = _raw_design(hfss)
    assert hasattr(raw_design, "ImportDataset"), (
        f"Raw design must expose ImportDataset for ferrite dataset import (design_type={type(raw_design).__name__})"
    )
    import_dataset = getattr(raw_design, "ImportDataset")
    assert callable(import_dataset), "Raw design ImportDataset must be callable"
    raise_on_false(
        import_dataset(str(NOTEBOOK_DATASET_IMPORT_PATH)),
        operation="ImportDataset",
        context={"path": str(NOTEBOOK_DATASET_IMPORT_PATH)},
    )

    raw_project = _raw_project(hfss)
    assert hasattr(raw_project, "AddDataset"), (
        f"Raw project must expose AddDataset for ferrite material datasets (project_type={type(raw_project).__name__})"
    )
    add_dataset = getattr(raw_project, "AddDataset")
    assert callable(add_dataset), "Raw project AddDataset must be callable"
    raise_on_false(
        add_dataset(_dataset_payload(MU_R_REAL_DATASET_NAME, points=MU_R_REAL_DATASET_POINTS)),
        operation="AddDataset",
        context={"dataset_name": MU_R_REAL_DATASET_NAME},
    )
    raise_on_false(
        add_dataset(_dataset_payload(MU_TAND_M_DATASET_NAME, points=MU_TAND_M_DATASET_POINTS)),
        operation="AddDataset",
        context={"dataset_name": MU_TAND_M_DATASET_NAME},
    )
    _ensure_project_dataset_ferrite_material_definition(hfss)
    _sync_pyaedt_material_lookup(hfss, material_name=MULL_FERRITE_MATERIAL)
    return MULL_FERRITE_MATERIAL


def _ensure_fr4_material(hfss: HfssSession) -> str:
    raw_materials = hfss.materials
    assert hasattr(raw_materials, "exists_material"), "Hfss.materials must expose exists_material"
    assert hasattr(raw_materials, "add_material"), "Hfss.materials must expose add_material"
    assert hasattr(raw_materials, "material_keys"), "Hfss.materials must expose material_keys"
    materials = cast(MaterialsSession, raw_materials)
    exists = bool(materials.exists_material(FR4_MATERIAL))
    if exists:
        material_keys = materials.material_keys
        assert FR4_MATERIAL in material_keys, (
            f"AEDT material_keys must contain {FR4_MATERIAL} after exists_material(name)=True"
        )
        material = material_keys[FR4_MATERIAL]
    else:
        material = raise_on_false(
            materials.add_material(FR4_MATERIAL),
            operation="add_material",
            context={"name": FR4_MATERIAL},
        )
    for attr_name, attr_value in (
        ("permeability", "1.0"),
        ("permittivity", FR4_PERMITTIVITY),
        ("conductivity", FR4_CONDUCTIVITY),
        ("dielectric_loss_tangent", FR4_DIELECTRIC_LOSS_TANGENT),
        ("magnetic_loss_tangent", "0"),
    ):
        _set_material_property(
            material,
            material_name=FR4_MATERIAL,
            attr_name=attr_name,
            attr_value=attr_value,
        )
    return FR4_MATERIAL


def _ensure_repo_owned_material(*, hfss: HfssSession, material: str) -> str:
    if material == FR4_MATERIAL:
        return _ensure_fr4_material(hfss)
    if material in (MULL_FERRITE_ALIAS, MULL_FERRITE_MATERIAL):
        return _ensure_notebook_dataset_ferrite_material(hfss)
    return material


def _imported_object_ref(*, modeler: ModelerSession, object_name: str) -> object:
    return raise_on_false(
        modeler.get_object_from_name(object_name),
        operation="get_object_from_name",
        context={"object_name": object_name},
    )


def _apply_visual_state(
    *,
    modeler: ModelerSession,
    object_name: str,
    color: tuple[int, int, int],
    transparency: float,
) -> VisualAssignment:
    object_ref = _imported_object_ref(modeler=modeler, object_name=object_name)
    set_object_color(object_ref, color=color)
    set_object_transparency(object_ref, transparency=transparency)
    return {"color": [color[0], color[1], color[2]], "transparency": transparency}


def _assign_body_materials(
    *,
    hfss: HfssSession,
    modeler: ModelerSession,
    ledger: SswAedtPortStepLedger,
    body_names: list[str],
) -> dict[str, str]:
    body_materials = _body_materials_by_object_id(ledger)
    material_assignments: dict[str, str] = {}
    for object_name in body_names:
        if object_name not in body_materials:
            raise ValueError(f"SSW body has no material entry (object_name={object_name})")
        material = body_materials[object_name]
        assignment_material = _ensure_repo_owned_material(hfss=hfss, material=material)
        material_assignments[object_name] = _assign_object_material(
            hfss=hfss,
            modeler=modeler,
            object_name=object_name,
            material=assignment_material,
        )
        if material == "copper":
            _set_imported_object_solve_inside(modeler=modeler, object_name=object_name, solve_inside=True)
    return material_assignments


def _design(hfss: HfssSession) -> DesignSession:
    raw_design = hfss.odesign
    assert isinstance(raw_design, DesignSession)
    return raw_design


def _region_object_name(region: object) -> str:
    assert hasattr(region, "name"), "create_region did not return a region object with a name"
    name = getattr(region, "name")
    assert isinstance(name, str) and name, "create_region returned a region object without a valid name"
    return name


def _build_boundary(*, hfss: HfssSession, modeler: ModelerSession) -> SswAedtBoundarySummary:
    pad_value_mm = int(round(RADIATION_MARGIN_MM))
    region = raise_on_false(
        modeler.create_region(
            pad_value=pad_value_mm,
            pad_type="Absolute Offset",
            name=f"Region_Abs_{pad_value_mm}mm",
        ),
        operation="create_region",
        context={"pad_value_mm": pad_value_mm},
    )
    region_name = _region_object_name(region)
    region_faces = raise_on_false(
        modeler.get_object_faces(region_name),
        operation="get_object_faces",
        context={"region": region_name},
    )
    if len(region_faces) != 6:
        raise ValueError(
            "Created SSW region does not expose 6 faces required for radiation assignment "
            f"(region={region_name}, face_count={len(region_faces)})"
        )
    boundary_names: list[str] = []
    for index, face_id in enumerate(region_faces):
        radiation_name = f"Rad_RegionAbs_{index}"
        raise_on_false(
            hfss.assign_radiation_boundary_to_faces([face_id], name=radiation_name),
            operation="assign_radiation_boundary_to_faces",
            context={"region": region_name, "face_id": face_id, "boundary": radiation_name},
        )
        boundary_names.append(radiation_name)
    return {
        "type": "radiation",
        "offset_type": "Absolute Offset",
        "offset_value": str(RADIATION_MARGIN_MM),
        "region_name": region_name,
        "face_count": str(len(region_faces)),
        "boundary_names": boundary_names,
    }


def _mesh_setup_module(hfss: HfssSession) -> MeshModuleSession:
    raw_module = raise_on_false(
        _design(hfss).GetModule(MESH_MODULE_NAME),
        operation="GetModule",
        context={"module_name": MESH_MODULE_NAME},
    )
    assert hasattr(raw_module, "AssignLengthOp"), "MeshSetup module must expose AssignLengthOp"
    return cast(MeshModuleSession, raw_module)


def _analysis_setup_module(hfss: HfssSession) -> AnalysisSetupModuleSession:
    raw_module = raise_on_false(
        _design(hfss).GetModule(ANALYSIS_MODULE_NAME),
        operation="GetModule",
        context={"module_name": ANALYSIS_MODULE_NAME},
    )
    assert hasattr(raw_module, "InsertSetup"), "AnalysisSetup module must expose InsertSetup"
    assert hasattr(raw_module, "InsertFrequencySweep"), "AnalysisSetup module must expose InsertFrequencySweep"
    return cast(AnalysisSetupModuleSession, raw_module)


def _required_mesh_object_names(*, copper_body_names: list[str], fr4_body_names: list[str]) -> list[str]:
    rx_matches = [name for name in copper_body_names if name in MESH_RX_COPPER_CANDIDATES]
    tx_matches = [name for name in copper_body_names if name == MESH_TX_COPPER_NAME]
    if len(rx_matches) != 1:
        raise ValueError(
            "SSW mesh requires exactly one recorded RX copper target "
            f"(candidates={MESH_RX_COPPER_CANDIDATES}, actual={rx_matches}, copper_body_names={copper_body_names})"
        )
    if len(tx_matches) != 1:
        raise ValueError(
            "SSW mesh requires exactly one recorded TX copper target "
            f"(required={MESH_TX_COPPER_NAME!r}, actual={tx_matches}, copper_body_names={copper_body_names})"
        )
    if len(fr4_body_names) == 0:
        raise ValueError("SSW mesh requires at least one recorded FR4 PCB target")
    return [rx_matches[0], tx_matches[0], *fr4_body_names]


def _format_length_mm(value_mm: float) -> str:
    return f"{value_mm:.6g}mm"


def adaptive_mesh_max_length_mm(*, tx_trace_width_mm: float, rx_trace_width_mm: float) -> str:
    """0.3.9.3 mesh Length op MaxLength = min(tx/2, rx/2) as an Xmm string (no floor).

    The 3 mm floor was removed in 0.3.9.3: on small coils it forced a mesh
    coarser than the trace itself and broke the solve.
    """
    return _format_length_mm(min(tx_trace_width_mm / 2.0, rx_trace_width_mm / 2.0))


def _mesh_assignment_payload(mesh_object_names: list[str], *, max_length: str) -> list[object]:
    return [
        f"NAME:{MESH_OPERATION_NAME}",
        "RefineInside:=",
        False,
        "Enabled:=",
        True,
        "Objects:=",
        mesh_object_names,
        "RestrictElem:=",
        True,
        "NumMaxElem:=",
        MESH_MAX_ELEMENTS,
        "RestrictLength:=",
        True,
        "MaxLength:=",
        max_length,
    ]


def _require_positive_int(value: int, *, context: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{context} must be an int")
    if value <= 0:
        raise ValueError(f"{context} must be positive")


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _process_tree(*, root_pid: int) -> list[psutil.Process]:
    try:
        root = psutil.Process(root_pid)
    except psutil.Error as exc:
        raise RuntimeError(f"AEDT process is not available for telemetry (pid={root_pid})") from exc
    processes = [root]
    try:
        processes.extend(root.children(recursive=True))
    except psutil.Error:
        pass
    return processes


def _process_name_and_cmdline(process: psutil.Process) -> str:
    name = ""
    cmdline = ""
    try:
        name = process.name()
    except psutil.Error:
        name = ""
    try:
        cmdline = " ".join(process.cmdline())
    except psutil.Error:
        cmdline = ""
    return f"{name} {cmdline}"


def _resolve_host_aedt_process_id(*, reported_pid: int) -> int:
    if psutil.pid_exists(reported_pid):
        try:
            reported_process = psutil.Process(reported_pid)
            reported_label = _process_name_and_cmdline(reported_process).lower()
        except psutil.Error:
            reported_label = ""
        if "ansysedt" in reported_label and "-grpcsrv" in reported_label:
            return reported_pid
    candidates: list[tuple[float, int]] = []
    for process in psutil.process_iter():
        label = _process_name_and_cmdline(process).lower()
        if "ansysedt" not in label:
            continue
        if "-grpcsrv" not in label:
            continue
        try:
            create_time = float(process.create_time())
        except psutil.Error:
            continue
        candidates.append((create_time, int(process.pid)))
    if len(candidates) == 0:
        raise RuntimeError(f"AEDT host process is not available for telemetry (reported_pid={reported_pid})")
    candidates.sort()
    return candidates[-1][1]


def _sample_process_resources(
    *,
    root_pid: int,
    reported_pid: int,
    started_at_monotonic: float,
    previous_cpu_seconds_by_pid: dict[int, float],
    previous_sample_monotonic: float,
) -> tuple[SswSolveTelemetrySample, dict[int, float], float]:
    process_samples: list[SswProcessResourceSample] = []
    current_cpu_seconds_by_pid: dict[int, float] = {}
    current_sample_monotonic = time.monotonic()
    cpu_elapsed_seconds = current_sample_monotonic - previous_sample_monotonic
    if cpu_elapsed_seconds <= 0.0:
        cpu_elapsed_seconds = 1e-9
    for process in _process_tree(root_pid=root_pid):
        try:
            memory = process.memory_info()
            name = process.name()
            cpu_times = process.cpu_times()
        except psutil.Error:
            continue
        cpu_seconds = float(cpu_times.user) + float(cpu_times.system)
        current_cpu_seconds_by_pid[int(process.pid)] = cpu_seconds
        if int(process.pid) in previous_cpu_seconds_by_pid:
            cpu_delta_seconds = cpu_seconds - previous_cpu_seconds_by_pid[int(process.pid)]
            cpu_percent = max(cpu_delta_seconds / cpu_elapsed_seconds * 100.0, 0.0)
        else:
            cpu_percent = 0.0
        process_samples.append(
            {
                "pid": int(process.pid),
                "name": name,
                "cpu_percent": cpu_percent,
                "rss_bytes": int(memory.rss),
                "vms_bytes": int(memory.vms),
            }
        )
    if len(process_samples) == 0:
        raise RuntimeError(f"AEDT telemetry could not sample any live process (pid={root_pid})")
    return (
        {
            "timestamp": _timestamp(),
            "elapsed_ms": (current_sample_monotonic - started_at_monotonic) * 1000.0,
            "aedt_process_id": root_pid,
            "reported_aedt_process_id": reported_pid,
            "process_count": len(process_samples),
            "pids": [sample["pid"] for sample in process_samples],
            "cpu_percent_total": sum(sample["cpu_percent"] for sample in process_samples),
            "rss_bytes_total": sum(sample["rss_bytes"] for sample in process_samples),
            "vms_bytes_total": sum(sample["vms_bytes"] for sample in process_samples),
            "processes": process_samples,
        },
        current_cpu_seconds_by_pid,
        current_sample_monotonic,
    )


def _append_sample_jsonl(*, samples_path: Path, sample: SswSolveTelemetrySample) -> None:
    with samples_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(sample, sort_keys=True) + "\n")


def _telemetry_worker(
    *,
    root_pid: int,
    reported_pid: int,
    sample_interval_seconds: float,
    started_at_monotonic: float,
    samples_path: Path,
    stop_path: Path,
) -> None:
    previous_cpu_seconds_by_pid: dict[int, float] = {}
    previous_sample_monotonic = time.monotonic()
    while True:
        sample, previous_cpu_seconds_by_pid, previous_sample_monotonic = _sample_process_resources(
            root_pid=root_pid,
            reported_pid=reported_pid,
            started_at_monotonic=started_at_monotonic,
            previous_cpu_seconds_by_pid=previous_cpu_seconds_by_pid,
            previous_sample_monotonic=previous_sample_monotonic,
        )
        _append_sample_jsonl(samples_path=samples_path, sample=sample)
        if stop_path.exists():
            return
        next_sample_at = time.monotonic() + sample_interval_seconds
        while time.monotonic() < next_sample_at:
            if stop_path.exists():
                break
            time.sleep(0.1)


def _load_telemetry_samples(*, samples_path: Path) -> list[SswSolveTelemetrySample]:
    if not samples_path.is_file():
        raise FileNotFoundError(f"SSW solve telemetry sample file was not created: {samples_path}")
    samples: list[SswSolveTelemetrySample] = []
    for line_number, line in enumerate(samples_path.read_text(encoding="utf-8").splitlines(), start=1):
        if line == "":
            continue
        raw_sample = json.loads(line)
        if not isinstance(raw_sample, dict):
            raise TypeError(f"SSW solve telemetry sample line must be an object (line={line_number})")
        samples.append(cast(SswSolveTelemetrySample, raw_sample))
    if len(samples) == 0:
        raise ValueError(f"SSW solve telemetry did not record any samples: {samples_path}")
    return samples


class _SolveTelemetryMonitor:
    def __init__(self, *, reported_pid: int, sample_interval_seconds: float, output_dir: Path) -> None:
        if sample_interval_seconds <= 0.0:
            raise ValueError(f"sample_interval_seconds must be positive (actual={sample_interval_seconds})")
        self._reported_pid = reported_pid
        self._root_pid = _resolve_host_aedt_process_id(reported_pid=reported_pid)
        self._sample_interval_seconds = sample_interval_seconds
        self._started_at = _timestamp()
        self._started_at_monotonic = time.monotonic()
        self._samples_path = output_dir / SOLVE_TELEMETRY_SAMPLES_JSONL_NAME
        self._stop_path = output_dir / SOLVE_TELEMETRY_STOP_NAME
        context = multiprocessing.get_context("fork")
        self._process = context.Process(
            target=_telemetry_worker,
            kwargs={
                "root_pid": self._root_pid,
                "reported_pid": self._reported_pid,
                "sample_interval_seconds": self._sample_interval_seconds,
                "started_at_monotonic": self._started_at_monotonic,
                "samples_path": self._samples_path,
                "stop_path": self._stop_path,
            },
            name="ssw-solve-telemetry",
            daemon=True,
        )

    def start(self) -> None:
        self._samples_path.parent.mkdir(parents=True, exist_ok=True)
        self._samples_path.unlink(missing_ok=True)
        self._stop_path.unlink(missing_ok=True)
        self._process.start()

    def stop(self) -> SswSolveTelemetry:
        self._stop_path.write_text("stop\n", encoding="utf-8")
        self._process.join(timeout=self._sample_interval_seconds + 5.0)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=5.0)
            raise RuntimeError("SSW solve telemetry process did not stop")
        finished_at = _timestamp()
        elapsed_ms = (time.monotonic() - self._started_at_monotonic) * 1000.0
        samples = _load_telemetry_samples(samples_path=self._samples_path)
        return {
            "started_at": self._started_at,
            "finished_at": finished_at,
            "elapsed_ms": elapsed_ms,
            "aedt_process_id": self._root_pid,
            "reported_aedt_process_id": self._reported_pid,
            "sample_interval_seconds": self._sample_interval_seconds,
            "samples_jsonl_path": str(self._samples_path),
            "sample_count": len(samples),
            "peak_cpu_percent_total": max(sample["cpu_percent_total"] for sample in samples),
            "peak_rss_bytes_total": max(sample["rss_bytes_total"] for sample in samples),
            "peak_vms_bytes_total": max(sample["vms_bytes_total"] for sample in samples),
            "gpu_used": False,
            "gpu_device_name": "",
            "solver_cores": 0,
            "samples": samples,
        }


def _setup_payload(
    *,
    maximum_passes: int = SETUP_MAXIMUM_PASSES,
    minimum_passes: int = SETUP_MINIMUM_PASSES,
    minimum_converged_passes: int = SETUP_MINIMUM_CONVERGED_PASSES,
) -> list[object]:
    _require_positive_int(maximum_passes, context="maximum_passes")
    _require_positive_int(minimum_passes, context="minimum_passes")
    _require_positive_int(minimum_converged_passes, context="minimum_converged_passes")
    return [
        f"NAME:{SETUP_NAME}",
        "SolveType:=",
        "Single",
        "Frequency:=",
        SETUP_FREQUENCY,
        "MaxDeltaS:=",
        SETUP_MAX_DELTA_S,
        "UseMatrixConv:=",
        False,
        "MaximumPasses:=",
        maximum_passes,
        "MinimumPasses:=",
        minimum_passes,
        "MinimumConvergedPasses:=",
        minimum_converged_passes,
        "PercentRefinement:=",
        SETUP_PERCENT_REFINEMENT,
        "IsEnabled:=",
        True,
        [
            "NAME:MeshLink",
            "ImportMesh:=",
            False,
        ],
        "BasisOrder:=",
        0,
        "DoLambdaRefine:=",
        False,
        "DoMaterialLambda:=",
        True,
        "SetLambdaTarget:=",
        False,
        "Target:=",
        0.1,
        "UseMaxTetIncrease:=",
        False,
        "PortAccuracy:=",
        2,
        "UseABCOnPort:=",
        False,
        "SetPortMinMaxTri:=",
        False,
        "DrivenSolverType:=",
        "Direct Solver",
        "EnhancedLowFreqAccuracy:=",
        False,
        "EnhancedFEBIPreconditioner:=",
        False,
        "SaveRadFieldsOnly:=",
        False,
        "SaveAnyFields:=",
        True,
        "IESolverType:=",
        "Auto",
        "LambdaTargetForIESolver:=",
        0.15,
        "UseDefaultLambdaTgtForIESolver:=",
        True,
        "IE Solver Accuracy:=",
        "Balanced",
        "InfiniteSphereSetup:=",
        "",
        "MaxPass:=",
        maximum_passes,
        "MinPass:=",
        minimum_passes,
        "MinConvPass:=",
        minimum_converged_passes,
        "PerError:=",
        1,
        "PerRefine:=",
        30,
    ]


def _sweep_payload() -> list[object]:
    return [
        f"NAME:{SWEEP_NAME}",
        "IsEnabled:=",
        True,
        "RangeType:=",
        "LinearCount",
        "RangeStart:=",
        SWEEP_RANGE_START,
        "RangeEnd:=",
        SWEEP_RANGE_END,
        "RangeCount:=",
        SWEEP_RANGE_COUNT,
        "Type:=",
        "Interpolating",
        "SaveFields:=",
        False,
        "SaveRadFields:=",
        False,
        "InterpTolerance:=",
        0.5,
        "InterpMaxSolns:=",
        250,
        "InterpMinSolns:=",
        0,
        "InterpMinSubranges:=",
        1,
        "InterpUseS:=",
        True,
        "InterpUsePortImped:=",
        True,
        "InterpUsePropConst:=",
        True,
        "UseDerivativeConvergence:=",
        False,
        "InterpDerivTolerance:=",
        0.2,
        "UseFullBasis:=",
        True,
        "EnforcePassivity:=",
        True,
        "PassivityErrorTolerance:=",
        0.0001,
        "EnforceCausality:=",
        False,
        "SMatrixOnlySolveMode:=",
        "Auto",
    ]


def _assign_recorded_mesh(
    *,
    hfss: HfssSession,
    copper_body_names: list[str],
    fr4_body_names: list[str],
    max_length: str,
) -> SswAedtMeshSummary:
    mesh_object_names = _required_mesh_object_names(copper_body_names=copper_body_names, fr4_body_names=fr4_body_names)
    mesh_module = _mesh_setup_module(hfss)
    raise_on_false(
        mesh_module.AssignLengthOp(_mesh_assignment_payload(mesh_object_names, max_length=max_length)),
        operation="AssignLengthOp",
        context={
            "module_name": MESH_MODULE_NAME,
            "operation_name": MESH_OPERATION_NAME,
            "objects": mesh_object_names,
            "max_length": max_length,
            "num_max_elem": MESH_MAX_ELEMENTS,
        },
    )
    return {
        "module_name": MESH_MODULE_NAME,
        "operation": "AssignLengthOp",
        "operation_name": MESH_OPERATION_NAME,
        "objects": mesh_object_names,
        "refine_inside": False,
        "enabled": True,
        "restrict_elem": True,
        "num_max_elem": MESH_MAX_ELEMENTS,
        "restrict_length": True,
        "max_length": max_length,
    }


def _insert_recorded_setup_and_sweep(
    *,
    hfss: HfssSession,
    maximum_passes: int = SETUP_MAXIMUM_PASSES,
    minimum_passes: int = SETUP_MINIMUM_PASSES,
    minimum_converged_passes: int = SETUP_MINIMUM_CONVERGED_PASSES,
) -> tuple[SswAedtAnalysisSetupSummary, SswAedtFrequencySweepSummary]:
    module = _analysis_setup_module(hfss)
    raise_on_false(
        module.InsertSetup(
            "HfssDriven",
            _setup_payload(
                maximum_passes=maximum_passes,
                minimum_passes=minimum_passes,
                minimum_converged_passes=minimum_converged_passes,
            ),
        ),
        operation="InsertSetup",
        context={"setup_type": "HfssDriven", "setup_name": SETUP_NAME},
    )
    raise_on_false(
        module.InsertFrequencySweep(SETUP_NAME, _sweep_payload()),
        operation="InsertFrequencySweep",
        context={"setup_name": SETUP_NAME, "sweep_name": SWEEP_NAME},
    )
    return (
        {
            "module_name": ANALYSIS_MODULE_NAME,
            "operation": "InsertSetup",
            "setup_type": "HfssDriven",
            "setup_name": SETUP_NAME,
            "frequency": SETUP_FREQUENCY,
            "max_delta_s": SETUP_MAX_DELTA_S,
            "maximum_passes": maximum_passes,
            "minimum_passes": minimum_passes,
            "minimum_converged_passes": minimum_converged_passes,
            "percent_refinement": SETUP_PERCENT_REFINEMENT,
            "basis_order": 0,
            "port_accuracy": 2,
            "driven_solver_type": "Direct Solver",
        },
        {
            "module_name": ANALYSIS_MODULE_NAME,
            "operation": "InsertFrequencySweep",
            "setup_name": SETUP_NAME,
            "sweep_name": SWEEP_NAME,
            "range_type": "LinearCount",
            "range_start": SWEEP_RANGE_START,
            "range_end": SWEEP_RANGE_END,
            "range_count": SWEEP_RANGE_COUNT,
            "sweep_type": "Interpolating",
        },
    )


def _report_setup_module(hfss: HfssSession) -> ReportSetupModuleSession:
    raw_module = _design(hfss).GetModule("ReportSetup")
    assert hasattr(raw_module, "CreateReport"), "ReportSetup module must expose CreateReport"
    assert hasattr(raw_module, "GetAllReportNames"), "ReportSetup module must expose GetAllReportNames"
    return cast(ReportSetupModuleSession, raw_module)


def _txrx_output_variables(*, tx_port: str, rx_port: str) -> list[tuple[str, str]]:
    variables: list[tuple[str, str]] = []
    for name, raw_expression in _TXRX_OUTPUT_VARIABLE_EXPRESSIONS:
        expression = raw_expression.replace("TX_TML", tx_port).replace("RX_TML", rx_port)
        variables.append((name, expression))
    return variables


def _ssw_geometry_diagnostic_traces(
    *,
    imported_ledger: SswAedtImportedLedgerBase,
    boundary: SswAedtBoundarySummary,
) -> list[str]:
    traces: list[str] = []
    for name in imported_ledger["non_model_body_names"]:
        traces.append(f"Volume({name})")
    for name in imported_ledger["ferrite_body_names"]:
        traces.append(f"Volume({name})")
    for name in imported_ledger["copper_body_names"]:
        traces.append(f"Volume({name})")
    traces.append(f"Volume({boundary['region_name']})")
    return traces


def _solid_loss_expression_name(object_name: str) -> str:
    return f"loss_W_{object_name}"


def _solid_loss_target_names(
    *,
    imported_ledger: SswAedtImportedLedgerBase,
    boundary: SswAedtBoundarySummary,
) -> list[str]:
    material_assigned_names = set(imported_ledger["material_assignments"])
    non_model_names = set(imported_ledger["non_model_body_names"])
    targets: list[str] = []
    for object_name in imported_ledger["imported_object_names"]:
        if object_name in material_assigned_names and object_name not in non_model_names:
            targets.append(object_name)
    targets.append(boundary["region_name"])
    return targets


def _fields_reporter(hfss: HfssSession) -> FieldsReporterSession:
    raw_module = _design(hfss).GetModule("FieldsReporter")
    assert hasattr(raw_module, "CalcStack"), "FieldsReporter module must expose CalcStack"
    assert hasattr(raw_module, "CopyNamedExprToStack"), "FieldsReporter module must expose CopyNamedExprToStack"
    assert hasattr(raw_module, "EnterVol"), "FieldsReporter module must expose EnterVol"
    assert hasattr(raw_module, "CalcOp"), "FieldsReporter module must expose CalcOp"
    assert hasattr(raw_module, "AddNamedExpression"), "FieldsReporter module must expose AddNamedExpression"
    return cast(FieldsReporterSession, raw_module)


def _create_one_solid_loss_expression(
    *,
    fields_reporter: FieldsReporterSession,
    object_name: str,
    expression_name: str,
) -> None:
    raise_on_false(fields_reporter.CalcStack("clear"), operation="CalcStack", context={"command": "clear"})
    raise_on_false(
        fields_reporter.CopyNamedExprToStack("Volume_Loss_Density"),
        operation="CopyNamedExprToStack",
        context={"expression_name": "Volume_Loss_Density"},
    )
    raise_on_false(fields_reporter.EnterVol(object_name), operation="EnterVol", context={"object_name": object_name})
    raise_on_false(fields_reporter.CalcOp("Integrate"), operation="CalcOp", context={"operation": "Integrate"})
    raise_on_false(
        fields_reporter.AddNamedExpression(expression_name, "Fields"),
        operation="AddNamedExpression",
        context={"expression_name": expression_name, "field_type": "Fields"},
    )


def _create_solid_loss_expressions(
    *,
    hfss: HfssSession,
    imported_ledger: SswAedtImportedLedgerBase,
    boundary: SswAedtBoundarySummary,
) -> list[str]:
    fields_reporter = _fields_reporter(hfss)
    expression_names: list[str] = []
    for object_name in _solid_loss_target_names(imported_ledger=imported_ledger, boundary=boundary):
        expression_name = _solid_loss_expression_name(object_name)
        _create_one_solid_loss_expression(
            fields_reporter=fields_reporter,
            object_name=object_name,
            expression_name=expression_name,
        )
        expression_names.append(expression_name)
    return expression_names


def _create_one_report(
    *,
    report_setup: ReportSetupModuleSession,
    report_name: str,
    report_category: str,
    solution_name: str,
    context: list[object],
    variations: list[object],
    traces: list[str],
    primary_sweep: str,
) -> None:
    raise_on_false(
        report_setup.CreateReport(
            report_name,
            report_category,
            "Data Table",
            solution_name,
            context,
            variations,
            ["X Component:=", primary_sweep, "Y Component:=", traces],
            [],
        ),
        operation="CreateReport",
        context={"report_name": report_name, "report_category": report_category, "solution_name": solution_name},
    )


def _create_reports(
    *,
    hfss: HfssSession,
    ports: SswAedtPorts,
    imported_ledger: SswAedtImportedLedgerBase,
    boundary: SswAedtBoundarySummary,
) -> SswAedtReportsSummary:
    tx_ports = ports["tx"]
    rx_ports = ports["rx"]
    if len(tx_ports) != 1 or len(rx_ports) != 1:
        raise ValueError(f"SSW reports require exactly one TX and one RX port (ports={ports})")
    tx_port = tx_ports[0]
    rx_port = rx_ports[0]
    variables = _txrx_output_variables(tx_port=tx_port, rx_port=rx_port)
    output_variable_names = [name for name, _expression in variables]
    solution_name = f"{SETUP_NAME} : {SWEEP_NAME}"
    solid_loss_solution_name = f"{SETUP_NAME} : LastAdaptive"
    for name, expression in variables:
        raise_on_false(
            hfss.create_output_variable(variable=name, expression=expression, solution=solution_name),
            operation="create_output_variable",
            context={"name": name, "expression": expression, "solution": solution_name},
        )
    solid_loss_expression_names = _create_solid_loss_expressions(
        hfss=hfss,
        imported_ledger=imported_ledger,
        boundary=boundary,
    )
    report_setup = _report_setup_module(hfss)
    _create_one_report(
        report_setup=report_setup,
        report_name=RESULTS1_PASS_REPORT_NAME,
        report_category="Terminal Solution Data",
        solution_name=f"{SETUP_NAME} : AdaptivePass",
        context=[],
        variations=["Pass:=", ["All"], "Freq:=", ["All"]],
        traces=[*output_variable_names, "SolvedElements", "MaxMagDeltaS"],
        primary_sweep="Pass",
    )
    _create_one_report(
        report_setup=report_setup,
        report_name=RESULTS2_LAST_REPORT_NAME,
        report_category="Fields",
        solution_name=solid_loss_solution_name,
        context=[],
        variations=["Freq:=", ["All"]],
        traces=solid_loss_expression_names,
        primary_sweep="Freq",
    )
    _create_one_report(
        report_setup=report_setup,
        report_name=RESULTS3_FREQ_REPORT_NAME,
        report_category="Terminal Solution Data",
        solution_name=solution_name,
        context=[],
        variations=["Freq:=", ["All"]],
        traces=[
            *output_variable_names,
            *_ssw_geometry_diagnostic_traces(imported_ledger=imported_ledger, boundary=boundary),
        ],
        primary_sweep="Freq",
    )
    report_names = set(report_setup.GetAllReportNames())
    expected_report_names = set(SSW_REPORT_NAMES)
    if not expected_report_names.issubset(report_names):
        raise ValueError(
            "SSW report creation did not register required reports "
            f"(missing={sorted(expected_report_names.difference(report_names))}, available={sorted(report_names)})"
        )
    return {
        "report_names": list(SSW_REPORT_NAMES),
        "output_variable_names": output_variable_names,
        "solid_loss_expression_names": solid_loss_expression_names,
        "output_solution_name": solution_name,
        "solid_loss_solution_name": solid_loss_solution_name,
        "diagnostic_report_names": list(SSW_REPORT_NAMES),
    }


def _import_ssw_aedt_port_step(
    *,
    hfss: HfssSession,
    ledger_path: Path,
    output_aedt_path: Path,
    ledger: SswAedtPortStepLedger,
) -> SswAedtImportedLedgerBase:
    scene_step_path = Path(ledger["scene_step_path"])
    before_names = set(hfss.modeler.object_names)
    raise_on_false(
        hfss.modeler.import_3d_cad(
            scene_step_path,
            create_group=False,
            import_free_surfaces=False,
            import_materials=False,
        ),
        operation="import_3d_cad",
        context={"scene_step_path": str(scene_step_path)},
    )
    after_names = set(hfss.modeler.object_names)
    expected_names = set(_required_str_list(ledger, key="body_names"))
    missing_names = sorted(expected_names.difference(after_names))
    if missing_names:
        raise ValueError(f"SSW AEDT port STEP import did not create required bodies (missing={missing_names})")
    imported_names = sorted(name for name in after_names if name in expected_names or name not in before_names)
    body_names = _required_str_list(ledger, key="body_names")
    copper_body_names = _required_str_list(ledger, key="copper_body_names")
    fr4_body_names = _required_str_list(ledger, key="fr4_body_names")
    material_assignments = _assign_body_materials(
        hfss=hfss,
        modeler=hfss.modeler,
        ledger=ledger,
        body_names=body_names,
    )
    non_model_names = _required_str_list(ledger, key="non_model_body_names")
    ferrite_names = _required_str_list(ledger, key="ferrite_body_names")
    for non_model_name in non_model_names:
        raise_on_false(
            hfss.modeler.set_object_model_state(non_model_name, False),
            operation="set_object_model_state",
            context={"name": non_model_name, "model": False},
        )
    visual_assignments: dict[str, VisualAssignment] = {}
    ferrite_set = set(ferrite_names)
    non_model_set = set(non_model_names)
    overlap = sorted(ferrite_set.intersection(non_model_set))
    if overlap:
        raise ValueError(f"SSW ferrite bodies must remain model objects, not non-model objects (overlap={overlap})")
    for object_name in non_model_names:
        visual_assignments[object_name] = _apply_visual_state(
            modeler=hfss.modeler,
            object_name=object_name,
            color=NON_MODEL_COLOR,
            transparency=NON_MODEL_TRANSPARENCY,
        )
    for object_name in copper_body_names:
        visual_assignments[object_name] = _apply_visual_state(
            modeler=hfss.modeler,
            object_name=object_name,
            color=COPPER_COLOR,
            transparency=COPPER_TRANSPARENCY,
        )
    mesh_max_length = ledger.get("mesh_max_length") or _format_length_mm(MESH_MAX_LENGTH_FALLBACK_MM)
    mesh = _assign_recorded_mesh(
        hfss=hfss,
        copper_body_names=copper_body_names,
        fr4_body_names=fr4_body_names,
        max_length=mesh_max_length,
    )
    return {
        "design_id": ledger["design_id"],
        "aedt_filename": ledger["aedt_filename"],
        "dimension_count": ledger["dimension_count"],
        "design_space_hash": ledger["design_space_hash"],
        "source_port_ledger_path": str(ledger_path),
        "source_step_ledger_path": ledger["source_step_ledger_path"],
        "scene_step_path": str(scene_step_path),
        "aedt_path": str(output_aedt_path),
        "imported_object_names": imported_names,
        "copper_body_names": copper_body_names,
        "fr4_body_names": fr4_body_names,
        "material_assignments": material_assignments,
        "visual_assignments": visual_assignments,
        "non_model_body_names": non_model_names,
        "ferrite_body_names": ferrite_names,
        "mesh": mesh,
    }


def _edge_vertices_xyz(modeler: ModelerSession, *, edge_id: int) -> tuple[Point3, Point3]:
    vertex_ids = modeler.get_edge_vertices(edge_id)
    if len(vertex_ids) != 2:
        raise ValueError(f"edge {edge_id} must expose exactly two vertices")
    first = modeler.get_vertex_position(int(vertex_ids[0]))
    second = modeler.get_vertex_position(int(vertex_ids[1]))
    if len(first) != 3 or len(second) != 3:
        raise ValueError(f"edge {edge_id} vertices must expose 3D positions")
    return (
        (float(first[0]), float(first[1]), float(first[2])),
        (float(second[0]), float(second[1]), float(second[2])),
    )


class EdgeSnapshot(TypedDict):
    edge_id: int
    vertices_xyz: tuple[Point3, Point3]


EDGE_TOLERANCE_MM = 1e-5


def _object_edge_snapshots(*, modeler: ModelerSession, object_name: str) -> list[EdgeSnapshot]:
    snapshots: list[EdgeSnapshot] = []
    for raw_edge_id in modeler.get_object_edges(object_name):
        edge_id = int(raw_edge_id)
        vertices = _edge_vertices_xyz(modeler, edge_id=edge_id)
        snapshots.append(
            {
                "edge_id": edge_id,
                "vertices_xyz": vertices,
            }
        )
    if len(snapshots) == 0:
        raise ValueError(f"imported copper object has no edges (object_name={object_name})")
    return snapshots


def _point_from_rows(raw_point: list[float], *, context: str) -> Point3:
    if len(raw_point) != 3:
        raise ValueError(f"{context} must contain exactly three coordinates")
    return (float(raw_point[0]), float(raw_point[1]), float(raw_point[2]))


def _same_point(first: Point3, second: Point3) -> bool:
    return (
        abs(first[0] - second[0]) <= EDGE_TOLERANCE_MM
        and abs(first[1] - second[1]) <= EDGE_TOLERANCE_MM
        and abs(first[2] - second[2]) <= EDGE_TOLERANCE_MM
    )


def _same_edge(first: tuple[Point3, Point3], second: tuple[Point3, Point3]) -> bool:
    return (_same_point(first[0], second[0]) and _same_point(first[1], second[1])) or (
        _same_point(first[0], second[1]) and _same_point(first[1], second[0])
    )


def _resolve_semantic_edge_ids(
    *,
    modeler: ModelerSession,
    spec: SswSemanticPortEdgeLedgerEntry,
    context: str,
) -> list[int]:
    edges = _object_edge_snapshots(modeler=modeler, object_name=spec["copper_body_name"])
    edge_ids: list[int] = []
    for expected_index, expected_edge_rows in enumerate(spec["edge_vertices_xyz"]):
        expected_context = f"{context}.edge_vertices_xyz[{expected_index}]"
        expected_edge = _edge_from_rows(expected_edge_rows, context=expected_context)
        matches = [
            edge["edge_id"]
            for edge in edges
            if _same_edge(edge["vertices_xyz"], expected_edge)
        ]
        if len(matches) != 1:
            raise ValueError(
                f"{expected_context} must match exactly one imported edge "
                f"(object_name={spec['copper_body_name']}, matches={matches})"
            )
        edge_ids.append(matches[0])
    if len(set(edge_ids)) != len(edge_ids):
        raise ValueError(f"{context}.edge_vertices_xyz resolves duplicate edge ids (edge_ids={edge_ids})")
    return sorted(edge_ids)


def _capture_expected_excitation(*, hfss: HfssSession, expected_name: str, context: str) -> str:
    names = list(hfss.excitation_names)
    if expected_name not in names:
        raise ValueError(f"{context} did not create expected excitation (expected={expected_name!r}, available={names})")
    return expected_name


def _required_raw_key(raw_entry: dict[str, object], *, key: str, context: str) -> object:
    if key not in raw_entry:
        raise ValueError(f"{context} is missing required key {key!r}")
    return raw_entry[key]


def _required_raw_str(raw_entry: dict[str, object], *, key: str, context: str) -> str:
    raw_value = _required_raw_key(raw_entry, key=key, context=context)
    if not isinstance(raw_value, str) or raw_value == "":
        raise TypeError(f"{context}.{key} must be a non-empty str")
    return raw_value


def _required_port_role(raw_entry: dict[str, object], *, context: str) -> PortRole:
    role = _required_raw_str(raw_entry, key="role", context=context)
    if role == "tx" or role == "rx":
        return role
    raise ValueError(f"{context}.role must be tx or rx (actual={role!r})")


def _raw_point_from_object(raw_point: object, *, context: str) -> list[float]:
    if isinstance(raw_point, (str, bytes)) or not isinstance(raw_point, list):
        raise TypeError(f"{context} must be a list of three numbers")
    if len(raw_point) != 3:
        raise ValueError(f"{context} must contain exactly three entries")
    point: list[float] = []
    for index, component in enumerate(raw_point):
        if isinstance(component, bool) or not isinstance(component, (int, float)):
            raise TypeError(f"{context}[{index}] must be numeric")
        point.append(float(component))
    return point


def _edge_from_rows(raw_edge: list[list[float]], *, context: str) -> tuple[Point3, Point3]:
    if len(raw_edge) != 2:
        raise ValueError(f"{context} must contain exactly two endpoint rows")
    return (
        _point_from_rows(raw_edge[0], context=f"{context}[0]"),
        _point_from_rows(raw_edge[1], context=f"{context}[1]"),
    )


def _raw_edge_vertices(raw_entry: dict[str, object], *, context: str) -> list[list[list[float]]]:
    raw_edges = _required_raw_key(raw_entry, key="edge_vertices_xyz", context=context)
    if isinstance(raw_edges, (str, bytes)) or not isinstance(raw_edges, list):
        raise TypeError(f"{context}.edge_vertices_xyz must be a list of two edge endpoint pairs")
    if len(raw_edges) != 2:
        raise ValueError(f"{context}.edge_vertices_xyz must contain exactly two edges")
    edges: list[list[list[float]]] = []
    for edge_index, raw_edge in enumerate(raw_edges):
        edge_context = f"{context}.edge_vertices_xyz[{edge_index}]"
        if isinstance(raw_edge, (str, bytes)) or not isinstance(raw_edge, list):
            raise TypeError(f"{edge_context} must be a list of two endpoint rows")
        if len(raw_edge) != 2:
            raise ValueError(f"{edge_context} must contain exactly two endpoint rows")
        edges.append(
            [
                _raw_point_from_object(raw_edge[0], context=f"{edge_context}[0]"),
                _raw_point_from_object(raw_edge[1], context=f"{edge_context}[1]"),
            ]
        )
    return edges


def _semantic_port_edge_entry(raw_entry: dict[str, object], *, context: str) -> SswSemanticPortEdgeLedgerEntry:
    return {
        "role": _required_port_role(raw_entry, context=context),
        "copper_body_name": _required_raw_str(raw_entry, key="copper_body_name", context=context),
        "selection": "semantic_edge_vertices",
        "edge_vertices_xyz": _raw_edge_vertices(raw_entry, context=context),
    }


def _port_edges_by_role(ledger: SswAedtPortStepLedger) -> dict[PortRole, SswAedtPortEdgeLedgerEntry]:
    raw_edges = ledger["port_edges"]
    if isinstance(raw_edges, (str, bytes)) or not isinstance(raw_edges, list):
        raise TypeError("SSW AEDT port ledger port_edges must be a list")
    edges_by_role: dict[PortRole, SswAedtPortEdgeLedgerEntry] = {}
    for index, raw_edge in enumerate(raw_edges):
        context = f"SSW AEDT port ledger port_edges[{index}]"
        if not isinstance(raw_edge, dict):
            raise TypeError(f"{context} must be object")
        raw_entry = cast(dict[str, object], raw_edge)
        selection = _required_raw_str(raw_entry, key="selection", context=context)
        if selection != "semantic_edge_vertices":
            raise ValueError(f"{context}.selection is unsupported (actual={selection!r})")
        entry = _semantic_port_edge_entry(raw_entry, context=context)
        role = entry["role"]
        if role in edges_by_role:
            raise ValueError(f"SSW AEDT port ledger contains duplicate port edge role {role!r}")
        edges_by_role[role] = entry
    if set(edges_by_role) != {"tx", "rx"}:
        raise ValueError(f"SSW AEDT port ledger requires tx and rx port edges (actual={sorted(edges_by_role)})")
    return edges_by_role


def _assign_one_port(
    *,
    hfss: HfssSession,
    modeler: ModelerSession,
    edge_spec: SswAedtPortEdgeLedgerEntry,
    boundary_name: BoundaryPayloadName,
    expected_terminal_name: ExpectedTerminalName,
    context: str,
) -> str:
    selection = edge_spec["selection"]
    if selection != "semantic_edge_vertices":
        raise ValueError(f"{context} has unsupported port edge selection {selection!r}")
    edge_ids = _resolve_semantic_edge_ids(
        modeler=modeler,
        spec=edge_spec,
        context=context,
    )
    assign_lumped_port(
        hfss.oboundary,
        [
            boundary_name,
            "Edges:=",
            edge_ids,
            "LumpedPortType:=",
            "Terminal",
            "DoDeembed:=",
            False,
            "RenormalizeAllTerminals:=",
            True,
            "ShowReporterFilter:=",
            False,
            "Impedance:=",
            "50ohm",
        ],
        context=context,
    )
    return _capture_expected_excitation(hfss=hfss, expected_name=expected_terminal_name, context=context)


def _assign_ports(*, hfss: HfssSession, ledger: SswAedtPortStepLedger) -> SswAedtPorts:
    edges_by_role = _port_edges_by_role(ledger)
    return {
        "tx": [
            _assign_one_port(
                hfss=hfss,
                modeler=hfss.modeler,
                edge_spec=edges_by_role["tx"],
                boundary_name="NAME:1",
                expected_terminal_name="1_T1",
                context="ssw.tx_port",
            )
        ],
        "rx": [
            _assign_one_port(
                hfss=hfss,
                modeler=hfss.modeler,
                edge_spec=edges_by_role["rx"],
                boundary_name="NAME:2",
                expected_terminal_name="2_T1",
                context="ssw.rx_port",
            )
        ],
    }


def _apply_sources(*, hfss: HfssSession, ports: SswAedtPorts) -> SswAedtSourcesSummary:
    tx_source_name = ports["tx"][0]
    rx_source_name = ports["rx"][0]
    raw_solutions = _design(hfss).GetModule("Solutions")
    assert hasattr(raw_solutions, "EditSources"), "Solutions module must expose EditSources"
    solutions = cast(SolutionsModuleSession, raw_solutions)
    edit_sources(
        solutions,
        payload=[
            [
                "UseIncidentVoltage:=",
                True,
                "IncludePortPostProcessing:=",
                False,
                "UseElementPatternMode:=",
                False,
                "SpecifySystemPower:=",
                False,
            ],
            ["Name:=", tx_source_name, "Magnitude:=", TX_SOURCE_MAGNITUDE, "Phase:=", TX_SOURCE_PHASE],
            ["Name:=", rx_source_name, "Magnitude:=", RX_SOURCE_MAGNITUDE, "Phase:=", RX_SOURCE_PHASE],
        ],
    )
    return {
        "tx_source_name": tx_source_name,
        "tx_magnitude": TX_SOURCE_MAGNITUDE,
        "tx_phase_deg": TX_SOURCE_PHASE,
        "rx_source_name": rx_source_name,
        "rx_magnitude": RX_SOURCE_MAGNITUDE,
        "rx_phase_deg": RX_SOURCE_PHASE,
    }


def _write_imported_ledger(*, imported_ledger_path: Path, imported_ledger: SswAedtImportedLedger) -> None:
    imported_ledger_path.parent.mkdir(parents=True, exist_ok=True)
    imported_ledger_path.write_text(json.dumps(imported_ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def setup_ssw_aedt_ports_into_hfss(
    *,
    hfss: HfssSession,
    output_aedt_path: Path,
    imported_ledger_path: Path,
    port_ledger_path: Path = DEFAULT_LEDGER_PATH,
    setup_maximum_passes: int = SETUP_MAXIMUM_PASSES,
    setup_minimum_passes: int = SETUP_MINIMUM_PASSES,
    setup_minimum_converged_passes: int = SETUP_MINIMUM_CONVERGED_PASSES,
) -> SswAedtPortSetupResult:
    ledger = load_ssw_aedt_port_ledger(port_ledger_path)
    output_aedt_path.parent.mkdir(parents=True, exist_ok=True)
    imported_base_ledger = _import_ssw_aedt_port_step(
        hfss=hfss,
        ledger_path=port_ledger_path,
        output_aedt_path=output_aedt_path,
        ledger=ledger,
    )
    boundary = _build_boundary(hfss=hfss, modeler=hfss.modeler)
    ports = _assign_ports(hfss=hfss, ledger=ledger)
    sources = _apply_sources(hfss=hfss, ports=ports)
    analysis_setup, frequency_sweep = _insert_recorded_setup_and_sweep(
        hfss=hfss,
        maximum_passes=setup_maximum_passes,
        minimum_passes=setup_minimum_passes,
        minimum_converged_passes=setup_minimum_converged_passes,
    )
    reports = _create_reports(hfss=hfss, ports=ports, imported_ledger=imported_base_ledger, boundary=boundary)
    imported_ledger: SswAedtImportedLedger = {
        "design_id": imported_base_ledger["design_id"],
        "aedt_filename": imported_base_ledger["aedt_filename"],
        "dimension_count": imported_base_ledger["dimension_count"],
        "design_space_hash": imported_base_ledger["design_space_hash"],
        "source_port_ledger_path": imported_base_ledger["source_port_ledger_path"],
        "source_step_ledger_path": imported_base_ledger["source_step_ledger_path"],
        "scene_step_path": imported_base_ledger["scene_step_path"],
        "aedt_path": imported_base_ledger["aedt_path"],
        "imported_object_names": imported_base_ledger["imported_object_names"],
        "copper_body_names": imported_base_ledger["copper_body_names"],
        "fr4_body_names": imported_base_ledger["fr4_body_names"],
        "material_assignments": imported_base_ledger["material_assignments"],
        "visual_assignments": imported_base_ledger["visual_assignments"],
        "non_model_body_names": imported_base_ledger["non_model_body_names"],
        "ferrite_body_names": imported_base_ledger["ferrite_body_names"],
        "mesh": imported_base_ledger["mesh"],
        "boundary": boundary,
        "analysis_setup": analysis_setup,
        "frequency_sweep": frequency_sweep,
        "sources": sources,
        "reports": reports,
    }
    raise_on_false(hfss.save_project(str(output_aedt_path)), operation="save_project", context={"path": str(output_aedt_path)})
    _write_imported_ledger(imported_ledger_path=imported_ledger_path, imported_ledger=imported_ledger)
    return {
        "design_id": imported_ledger["design_id"],
        "aedt_filename": imported_ledger["aedt_filename"],
        "dimension_count": imported_ledger["dimension_count"],
        "design_space_hash": imported_ledger["design_space_hash"],
        "source_port_ledger_path": str(port_ledger_path),
        "source_step_ledger_path": imported_ledger["source_step_ledger_path"],
        "scene_step_path": imported_ledger["scene_step_path"],
        "aedt_path": str(output_aedt_path),
        "imported_ledger_path": str(imported_ledger_path),
        "ports": ports,
        "imported_object_names": imported_ledger["imported_object_names"],
        "mesh": imported_ledger["mesh"],
        "boundary": imported_ledger["boundary"],
        "analysis_setup": imported_ledger["analysis_setup"],
        "frequency_sweep": imported_ledger["frequency_sweep"],
        "sources": imported_ledger["sources"],
        "reports": imported_ledger["reports"],
    }


def setup_ssw_aedt_ports(
    *,
    output_aedt_path: Path,
    imported_ledger_path: Path,
    design_name: str,
    port_ledger_path: Path = DEFAULT_LEDGER_PATH,
    hfss_factory: HfssFactory = create_headless_hfss,
    release_desktop_on_exit: bool = True,
    close_projects_on_release: bool = True,
    setup_maximum_passes: int = SETUP_MAXIMUM_PASSES,
    setup_minimum_passes: int = SETUP_MINIMUM_PASSES,
    setup_minimum_converged_passes: int = SETUP_MINIMUM_CONVERGED_PASSES,
) -> SswAedtPortSetupResult:
    hfss = hfss_factory(design_name)
    try:
        return setup_ssw_aedt_ports_into_hfss(
            hfss=hfss,
            port_ledger_path=port_ledger_path,
            output_aedt_path=output_aedt_path,
            imported_ledger_path=imported_ledger_path,
            setup_maximum_passes=setup_maximum_passes,
            setup_minimum_passes=setup_minimum_passes,
            setup_minimum_converged_passes=setup_minimum_converged_passes,
        )
    finally:
        if release_desktop_on_exit:
            raise_on_false(
                hfss.desktop_class.release_desktop(close_projects=close_projects_on_release, close_on_exit=True),
                operation="release_desktop",
                context={"close_projects": close_projects_on_release, "close_on_exit": True},
            )


def _report_csv_path(*, output_dir: Path, report_name: str) -> Path:
    return output_dir / f"{report_name}.csv"


def _export_ssw_report_csvs(*, hfss: HfssSession, output_dir: Path) -> dict[str, str]:
    report_setup = _report_setup_module(hfss)
    report_names = list(report_setup.GetAllReportNames())
    missing_report_names = sorted(set(SSW_REPORT_NAMES).difference(report_names))
    if len(missing_report_names) != 0:
        raise ValueError(f"SSW solve cannot export missing reports (missing={missing_report_names}, available={report_names})")
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_paths: dict[str, str] = {}
    for report_name in SSW_REPORT_NAMES:
        csv_path = _report_csv_path(output_dir=output_dir, report_name=report_name)
        raise_on_false(
            report_setup.ExportToFile(report_name, str(csv_path)),
            operation="ReportSetup.ExportToFile",
            context={"report_name": report_name, "path": str(csv_path)},
        )
        if not csv_path.is_file():
            raise FileNotFoundError(f"SSW report export did not create CSV: {csv_path}")
        csv_paths[report_name] = str(csv_path)
    return csv_paths


def solve_ssw_aedt_ports(
    *,
    output_aedt_path: Path,
    imported_ledger_path: Path,
    design_name: str,
    port_ledger_path: Path = DEFAULT_LEDGER_PATH,
    csv_output_dir: Path,
    hfss_factory: HfssFactory = create_headless_hfss,
    setup_maximum_passes: int = SETUP_MAXIMUM_PASSES,
    setup_minimum_passes: int = SETUP_MINIMUM_PASSES,
    setup_minimum_converged_passes: int = SETUP_MINIMUM_CONVERGED_PASSES,
    telemetry_sample_interval_seconds: float = SOLVE_TELEMETRY_SAMPLE_INTERVAL_SECONDS,
    keep_desktop_alive: bool = False,
    solve_hard_abort_seconds: float = SOLVE_HARD_ABORT_SECONDS,
) -> SswAedtReportCsvResult:
    hfss = hfss_factory(design_name)
    try:
        setup = setup_ssw_aedt_ports_into_hfss(
            hfss=hfss,
            port_ledger_path=port_ledger_path,
            output_aedt_path=output_aedt_path,
            imported_ledger_path=imported_ledger_path,
            setup_maximum_passes=setup_maximum_passes,
            setup_minimum_passes=setup_minimum_passes,
            setup_minimum_converged_passes=setup_minimum_converged_passes,
        )
        monitor = _SolveTelemetryMonitor(
            reported_pid=hfss.desktop_class.aedt_process_id,
            sample_interval_seconds=telemetry_sample_interval_seconds,
            output_dir=csv_output_dir,
        )
        resources = detect_solver_resources()
        monitor.start()
        try:
            solve_outcome, gpu_used = _analyze_with_hard_abort(
                hfss=hfss,
                setup_name=SETUP_NAME,
                hard_abort_seconds=solve_hard_abort_seconds,
                cores=resources["cores"],
                gpus=resources["gpu_count"],
            )
        finally:
            solve_telemetry = monitor.stop()
        solve_telemetry["gpu_used"] = gpu_used
        solve_telemetry["gpu_device_name"] = resources["gpu_device_name"] if gpu_used else ""
        solve_telemetry["solver_cores"] = resources["cores"]
        csv_paths = _export_ssw_report_csvs(hfss=hfss, output_dir=csv_output_dir)
        raise_on_false(hfss.save_project(str(output_aedt_path)), operation="save_project", context={"path": str(output_aedt_path)})
        return {
            "setup": setup,
            "csv_paths": csv_paths,
            "solve_telemetry": solve_telemetry,
            "solve_outcome": solve_outcome,
        }
    finally:
        if keep_desktop_alive:
            _release_keeping_desktop_alive(hfss)
        else:
            raise_on_false(
                hfss.desktop_class.release_desktop(close_projects=True, close_on_exit=True),
                operation="release_desktop",
                context={"close_projects": True, "close_on_exit": True},
            )


__all__ = [
    "DEFAULT_LEDGER_PATH",
    "HfssFactory",
    "CanonicalCoordinates",
    "SswAedtAnalysisSetupSummary",
    "SswAedtBoundarySummary",
    "SswAedtBodyLedgerEntry",
    "SswAedtFrequencySweepSummary",
    "SswAedtImportedLedger",
    "SswAedtMeshSummary",
    "SswAedtPortEdgeLedgerEntry",
    "SswAedtPorts",
    "SswAedtPortSetupResult",
    "SswAedtReportCsvResult",
    "SETUP_MAXIMUM_PASSES",
    "SETUP_MINIMUM_CONVERGED_PASSES",
    "SETUP_MINIMUM_PASSES",
    "MESH_MAX_LENGTH_FALLBACK_MM",
    "adaptive_mesh_max_length_mm",
    "SOLVE_ABORT_GRACE_SECONDS",
    "SOLVE_CORES",
    "SOLVE_HARD_ABORT_SECONDS",
    "SswSolveOutcome",
    "SswSolverResources",
    "detect_solver_resources",
    "SOLVE_TELEMETRY_SAMPLE_INTERVAL_SECONDS",
    "SOLVE_TELEMETRY_SAMPLES_JSONL_NAME",
    "SOLVE_TELEMETRY_STOP_NAME",
    "SSW_REPORT_NAMES",
    "SswProcessResourceSample",
    "SswAedtPortStepLedger",
    "SswAedtReportsSummary",
    "SswSolveTelemetry",
    "SswSolveTelemetrySample",
    "DEFAULT_ATTACH_HOST",
    "create_graphical_hfss",
    "create_headless_hfss",
    "make_attached_hfss_factory",
    "load_ssw_aedt_port_ledger",
    "setup_ssw_aedt_ports",
    "setup_ssw_aedt_ports_into_hfss",
    "solve_ssw_aedt_ports",
    "write_ssw_aedt_port_ledger",
]
