# Runner Integration (peetsfea 0.3.8.0)

What `peetsfea-runner` depends on in the `peetsfea` package, and the status of each item.

> Principle: **peetsfea never starts/stops `ansysedt` or manages licenses.** The runner keeps a
> warm, license-holding `ansysedt` and lends it to peetsfea per simulation.

## Public API

```python
peetsfea.__version__                       # "0.3.8.0"; package ships py.typed

# Reject sweeps outside the reference design space (raises PeetsfeaStageError).
peetsfea.validate_sweep_toml_text(sweep_text: str) -> None

# Deterministic for a given (sweep_text, count, seed). Honors TMPDIR.
peetsfea.sample_fixed_candidates_from_toml_text(sweep_text: str, count: int, seed: int) -> list[str]

# Attach to a runner-owned ansysedt, build+solve one candidate, return structured results.
peetsfea.run_ssw_random_sample_reports_from_toml_text(
    candidate_toml_text: str, *, output_dir, seed,
    grpc_port: int | None = None, aedt_pid: int | None = None,
) -> SswRandomSampleReportResult

peetsfea.PeetsfeaStageError   # structured failure (stage / error_type / message), subclass of RuntimeError
```

## Contract

| # | Requirement | Where |
|---|-------------|-------|
| 1 | `__version__ == "0.3.8.0"` + `py.typed` for strict typing of the public API | `version.py`, `py.typed` |
| 2 | Attach to an already-running `ansysedt` via `grpc_port` (then `pid`); never self-launch; `close_on_exit=False`; fail-fast (`stage="attach"`) when unreachable | `make_attached_hfss_factory` (`backend/pyaedt/ssw_ports.py`) |
| 3 | On finish, close only the project and leave AEDT alive for reuse | `keep_desktop_alive` → `_release_keeping_desktop_alive` |
| 4 | 60-min hard-abort watchdog (`SOLVE_HARD_ABORT_SECONDS=3600`) that still exports the last completed pass; `solve_outcome` reports `completed`/`hard_aborted` | `_analyze_with_hard_abort` |
| 5 | `validate_sweep_toml_text(text)` — every swept range within the reference sweep design space (bounds + int flag + positive count), else raise | `ssw_design_space.py` |
| 6 | `sample_fixed_candidates_from_toml_text(text, count, seed)` — deterministic fan-out of one sweep into N fixed candidates | `ssw_design_space.py` |
| 7 | Structured result `SswRandomSampleReportResult` (TypedDict): output vars + input params via report CSVs, per-setup pass counts, solve telemetry, `output_dir`/`aedt_path`; only the full solve mode is accepted | `ssw_random_sample_reports.py` |
| 8 | Respect the runner's working dir / `TMPDIR`; no hardcoded `/tmp` or `/dev/shm` | sampling scratch uses `tempfile` (env-honoring) |
| 9 | Structured failures via `PeetsfeaStageError(stage, error_type, message)` (subclass of `RuntimeError`) | `errors.py` |
| 10 | 18 free design inputs; RX SSW mode is fixed enabled, RX no-SSW quarter-turn fields are fixed, and TX MULL ferrite sheet count ranges from 1 to 5 | `peetsfea/data/0.3.x_sweep.toml` |

`SOLVE_HARD_ABORT_SECONDS=3600` (60 min) is below the runner's 3900s (65 min) backstop, so peetsfea
always self-reports before the external kill.

## Automatic GPU acceleration (0.3.5)

No API/signature change — the runner just exposes the GPU to the container (e.g.
`NVIDIA_VISIBLE_DEVICES=all`); peetsfea decides solver resources itself at solve time
(`detect_solver_resources` in `backend/pyaedt/ssw_ports.py`):

- **Auto-detect**: GPUs are detected via `nvidia-smi`. When present, the solve enables GPU
  acceleration on the AEDT analyze (`analyze_setup(..., gpus=N)` with manual HPC settings).
- **CPU fallback**: if the GPU-enabled analyze *fails* (no HPC Pack license, driver issue, …), it
  silently retries on CPU within the remaining time budget so the job still completes.
- **Cores**: the solver runs with a fixed `cores=SOLVE_CORES` (4) using manual HPC settings.
- **Telemetry**: `solve_telemetry` records `gpu_used`, `gpu_device_name`, and `solver_cores` (plus
  existing solve timing) so the runner can compare CPU vs GPU partitions from result data alone.

> HFSS frequency-domain (driven terminal/modal) GPU acceleration is limited; "enable if possible,
> measure via telemetry" rather than assuming a speedup.

## Reference sweep SSOT (packaging)

The reference sweep design space is bundled **inside the package** as `peetsfea/data/0.3.x_sweep.toml`
and resolved relative to the package directory, so it works in both source and pip-installed layouts
(`DEFAULT_REFERENCE_TOML_PATH` in `ssw_design_space.py`). The canonical fixed authoring point is
`peetsfea/data/0.3.x_fixed.toml` (`DEFAULT_SOURCE_TOML_PATH`).

> 0.3.2 shipped this reference under `examples/`, which is not part of the wheel — installed runs
> failed with `FileNotFound`. 0.3.5 fixes this by moving the SSOT into package data.

## Resolved design decisions

- **Attach**: take both `grpc_port` and `aedt_pid`; try the port first, the pid second; raise on failure.
- **Range validation strictness**: full (bounds + integer/float flag + positive count).
- **Result keys**: `SswRandomSampleReportResult` is a `TypedDict`; keys map 1:1 to the runner store.
- **Reference SSOT**: `peetsfea/data/0.3.x_sweep.toml`, resolved install-safe.
