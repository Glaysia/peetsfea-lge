---
title: AGENTS
created: 2026-04-17 @ 09:09
updated: 2026-06-16 @ 00:00
tags:
  - governance
---

> Global code commandments live in [CODE_COMMANDMENTS.md](CODE_COMMANDMENTS.md) and are mandatory for the entire repository.
> Commandment 1: every real failure must raise and stop execution by default.
> Commandment 2: if a PyAEDT call returns `False`, raise immediately with context; never log-and-continue.
> Commandment 3 (all `src/`): repository runtime state must not be nullable.
> Commandment 4 (`src/`): bind values only after asserted validation.
> Commandment 5 (`src/`): attribute and mapping fallbacks are forbidden.
> Fallbacks are forbidden: do not add fallback code paths, degraded substitutes, silent retries, or "try alternative behavior and continue" logic unless the user explicitly requests it for the current task.
> After any AEDT/PyAEDT-affecting code change, run a real headless AEDT validation from `run/` before calling the work complete. If the local AEDT/license/runtime cannot run, report the blocker and leave the work explicitly incomplete; never hand unvalidated AEDT code to the user as done.

# AGENTS

Project rules for coding agents working in this repository.

## Project goals
- **Spec-first design**: the TOML spec is the single source of truth (SSOT).
- **Determinism**: same spec + same version + same seed => same results.
- **PyAEDT backend**: delegate modeling/simulation to PyAEDT.
- **Dataset generation**: produce datasets via parameter sweeps/sampling.

## Active surface (0.3.4)
- The active product path is the SSW design-space + headless HFSS setup/solve/report pipeline:
  `ssw_design_space`, `ssw_step`, `ssw_aedt_artifacts`, `backend/pyaedt/ssw_ports`, and
  `ssw_random_sample_reports` (the runner-facing API — see [docs/runner-integration.md](docs/runner-integration.md)).
- Entry scripts: `entry/sample.py` (generate STEP per seed) and `entry/view.py` (OCP viewer / `--fixed`).
- The reference design space SSOT and the canonical fixed point ship as package data under
  `src/peetsfea/data/` and are resolved relative to the package (install-safe).

## Working principles
- Follow the repository-wide commandments in `CODE_COMMANDMENTS.md`; this document supplements them and must not weaken them.
- Multiple agents may work concurrently; before editing, re-read any file that may have changed, keep changes scoped, and do not overwrite, revert, or reformat unrelated in-flight edits from other agents.
- Keep small, tightly coupled edits local. When a change spans multiple subsystems or enough files that parallel work reduces risk, split it across subagents with explicit file/module ownership.
- Do not implement fallback behavior by default. If the intended path fails or is unsupported, raise immediately with actionable context instead of switching to an alternate path.
- In `src/`, do not introduce `Optional[...]`, `| None`, `NotRequired[...]`, `if value is None`, or `if value is not None` for repository runtime state, including parser and boundary code.
- In `src/`, validate dynamic values before binding them: `assert hasattr(...)`, read, then `assert isinstance(...)` or assert an equivalent invariant.
- In `src/`, do not use `getattr(..., default)`, `mapping.get(...)`, or similar fallback-return APIs for required state.
- If state must survive across steps, prefer a canonical module-level registry/dictionary and require `assert key in registry` before reads.
- Any spec change must be reflected in docs (README or spec docs).
- Random/sampling logic must always accept an explicit `seed`.
- Document defaults; do not hide implicit values.
- Keep PyAEDT-dependent code isolated and replaceable.
- Headless AEDT is the required validation target. GUI-visible AEDT is an inspection aid only; it never replaces a successful headless validation.
- Keep execution configuration (machines, runners) in Python code, not in TOML.
- When later logic needs the position/coordinates of an already-created object, store the canonical coordinates at creation time and read from that source; do not reverse-calculate them from downstream geometry.
- Prefer thorough type hints. Do not use `Any` unless there is a hard external boundary that cannot be typed precisely; document the reason. Do not replace `Any` with broad `object` just to satisfy a type checker; use concrete library types (e.g. `Hfss`, `Modeler3D` from `ansys.aedt.core`).
- Use the project-root virtual environment at `.venv` for local installs and commands (`.venv/bin/python`, `.venv/bin/pytest`, `.venv/bin/pyright`).
- Do not use `python -O`; optimized mode disables required assertions and is unsupported.
- Resolve all Pylance/pyright diagnostics before considering work complete.
- In long sessions, restate key assumptions and re-check AGENTS/README for drift before major changes.
- Tracked Python files under `src/` or `entry/` over ~800 lines are strong split candidates; when substantively editing one, first assess whether to split along ownership boundaries.
- Keep the TOML-to-code mapping one-to-one; ensure (TOML + seed) deterministically maps to final parameters and treat this as a testable contract.

## Sampling rules
- Every independent sampled degree of freedom must have exactly one canonical owner.
- Do not implement candidate generation or selection outside the shared sampling API (`ssw_design_space`).
- Values normalized away and not affecting the final design must stay fixed (`count=1` or an equivalent fixed value).
- If a sampled field is added or changed, update docs and the related determinism/coverage tests together.
- Do not hardcode an example spec's dimension count as a permanent contract; derive it from the design-space result.

## Spec rules
- Use standard TOML only (no custom DSL).
- Bump the spec version when adding new parameters; keep spec `path` as stable dot notation.
- Long-term backward compatibility is not guaranteed; document the policy in the README.

## Tests / execution
- Prefer pure-Python tests for parsing/validation/sampling (`-m "not pyaedt_integration"` is the default CI surface).
- Keep AEDT-coupled tests behind the `pyaedt_integration` marker, and run them for every change that affects AEDT/PyAEDT import, ports, setup, solve, reports, materials, validation, or runtime entrypoints.
- Determinism tests are required. PyAEDT integration tests are mandatory for AEDT/PyAEDT-affecting changes.
- Run commands from `run/` so generated artifacts (manifests, AEDT files, logs) land under `run/` (gitignored), not the repo root.
- Default execution and agent validation must stay headless. Do not treat GUI-visible AEDT behavior as completion evidence.
- After editing AEDT/PyAEDT code or an entrypoint that can launch AEDT, run the relevant real headless AEDT test from `run/` using `.venv`. If it fails, fix and rerun. If the machine cannot start AEDT or lacks a license, stop and report the exact blocker.
- Build/run failures must be fail-fast: do not silently continue after a failure; do not rely on best-effort continuation unless the user explicitly requests it.

## File layout
- `src/peetsfea/`: library code (spec/sampling, geometry, PyAEDT backend, public API)
- `src/peetsfea/data/`: packaged SSOT TOMLs (reference sweep + canonical fixed point)
- `entry/`: `sample.py`, `view.py`
- `tests/`: pure-Python contract tests + `tests/backend_em/` headless AEDT integration tests
- `docs/`: design/integration docs
- `run/`: gitignored execution workspace
