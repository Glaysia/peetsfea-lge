---
title: peetsfea
created: 2026-04-17 @ 09:09
updated: 2026-06-16 @ 00:00
tags:
  - governance
---

# peetsfea

peetsfea deterministically generates SSW coil designs from TOML specs and drives a headless
HFSS (AEDT) setup/solve/report pipeline. It exposes the public API that `peetsfea-runner` depends
on (see *Runner integration*).

For Korean documentation, see [README.md](README.md).

## Current contract
- Version: `0.3.7`
- Design-space SSOT: package data `src/peetsfea/data/0.3.x_sweep.toml` (`DEFAULT_REFERENCE_TOML_PATH`).
  The canonical fixed point is `src/peetsfea/data/0.3.x_fixed.toml` (`DEFAULT_SOURCE_TOML_PATH`).
  Both ship in the wheel and resolve in installed environments.
- TOML surface: `[design]` · `[backend]` · `[fixed_dimensions]` · `[[modeled_objects]]` (tx/rx/under
  coil) · `[ferrite]` · `[constraints]`.
- Constraints: an enabled SSW coil must satisfy `gcd(turn_n_int, twist_factor) == 1`; RX `turn_n_int`
  must be `> 1` when RX SSW is enabled; TX/RX `void_profile` is fixed to scaled void profile `1`.
- `tx_under_coil` is the second TX coil (separate from the TX main coil), a YZ-plane normal spiral
  attached outside the global X-min face of `tx_region_max` (see [GOAL.md](GOAL.md)).
- MULL ferrite placement is controlled separately by TX `ferrite.tx_mull_position_ratio` and RX
  `ferrite.rx_mull_position_ratio`.
- EM surface: one Tx port (`1_T1`), one Rx port (`2_T1`), copper pad mesh, radiation boundary,
  `Setup1`, `Sweep`, and report tables.
- Default execution and AEDT/PyAEDT validation are headless; PyAEDT `False` returns raise
  immediately. Any AEDT/PyAEDT code change must pass a real headless AEDT validation.

## Execution
Run from `run/`:

```bash
cd run
../.venv/bin/pytest -q ../tests -m "not pyaedt_integration"   # pure Python
../.venv/bin/pyright ../src ../entry ../tests
```

Generate random in-design-space SSW STEP files over a seed range (`entry/sample.py`) and view one
in the OCP viewer (`entry/view.py`):

```bash
cd run
../.venv/bin/python ../entry/sample.py --seed-start 0 --seed-end 99 --jobs 10
../.venv/bin/python ../entry/view.py --seed-start 0 --seed-end 9 --view-seed 3
../.venv/bin/python ../entry/view.py --view-seed 3 --no-sample
../.venv/bin/python ../entry/view.py --fixed   # build/view data/0.3.x_fixed.toml
```

Output goes under gitignored `run/ssw_step_samples/seed_<NNNNN>/` (`ssw_scene.step`,
`<design_id>.toml`, `ssw_step_ledger.json`, `coil_making_token.toml`). `--jobs N` runs generation
across N processes (each seed in its own directory; results are deterministic). `view.py` shows the
rebuilt `cq.Assembly` so per-role color and transparency are preserved.

## Runner integration (0.3.7)
peetsfea never starts/stops `ansysedt` or manages licenses. Full contract in
[docs/runner-integration.md](docs/runner-integration.md).

- `peetsfea.__version__ == "0.3.7"`, ships `py.typed`.
- `validate_sweep_toml_text(text)` — reject sweeps outside the reference design space.
- `sample_fixed_candidates_from_toml_text(text, count, seed) -> list[str]` — deterministic; honors `TMPDIR`.
- `run_ssw_random_sample_reports_from_toml_text(..., grpc_port, aedt_pid=None)` — attach to a warm
  ansysedt (never self-launch), solve, then close only the project (AEDT stays alive). Solve has a
  60-minute hard-abort watchdog.
- All failures raise `peetsfea.PeetsfeaStageError` (`stage`/`error_type`/`message`, subclass of `RuntimeError`).

## Rules
- `python -O` is unsupported (assertions are part of the runtime contract).
- Runtime state under `src/` must not rely on nullable or fallback paths ([CODE_COMMANDMENTS.md](CODE_COMMANDMENTS.md)).
- GUI AEDT is diagnosis only and never replaces headless validation.

## Documentation
- Goal: [GOAL.md](GOAL.md)
- Runner integration: [docs/runner-integration.md](docs/runner-integration.md)
- Palace second-backend roadmap: [docs/palace-second-backend-roadmap.md](docs/palace-second-backend-roadmap.md)
- Agent rules: [AGENTS.md](AGENTS.md) · Code commandments: [CODE_COMMANDMENTS.md](CODE_COMMANDMENTS.md)

## Compatibility
Long-term backward compatibility is not guaranteed. Minor releases may change spec paths, artifact
contracts, and runtime entrypoints.
