---
title: Palace Second Backend Roadmap
created: 2026-06-14
updated: 2026-06-14
tags:
  - palace
  - hfss
  - em
  - roadmap
  - surrogate
---

# Palace Second Backend Roadmap

## Purpose
- Use Palace as a second frequency-domain EM backend to reduce the HFSS bottleneck.
- Keep HFSS as the reference solver until Palace agreement is measured and documented.
- Preserve one geometry/spec identity across HFSS, Palace, and later ML datasets.
- Build the data foundation for transformer/surrogate models that predict network values, losses, and eventually field quantities.

## Scope
- Target active 0.3.8.0 two-port and SSW coil workflows.
- Target frequency-domain driven simulations only. Transient simulation is out of scope for the first backend.
- Target terminal-network-equivalent outputs: 2-port S/Z matrices, port voltages/currents, derived L/M/k/Q/FOM values, losses, and fields.
- Treat Palace output as a solver result, not as a silent fallback for failed HFSS runs.

## External Solver Basis
- Palace is a C++17, MPI-capable, open-source 3D FEM electromagnetic solver.
- Palace supports frequency-domain driven simulations with lumped or numeric wave ports.
- Palace writes port S-parameters, lumped port voltages/currents, field outputs, and domain/boundary postprocessing outputs.
- Relevant upstream references:
  - [Palace GitHub](https://github.com/awslabs/palace)
  - [Problem Types](https://awslabs.github.io/palace/stable/guide/problem/)
  - [Boundary Conditions](https://awslabs.github.io/palace/stable/guide/boundaries/)
  - [Postprocessing and Visualization](https://awslabs.github.io/palace/stable/guide/postprocessing/)
  - [Domains Configuration](https://awslabs.github.io/palace/stable/config/domains/)

## Ground Rules
- Backend selection belongs to runner/build code, not to a geometry-dependent TOML branch.
- The same source geometry, material ledger, port ledger, frequency set, and design identity must feed both solvers.
- No solver equivalence claim is valid until the same design point has HFSS and Palace artifacts side by side.
- A Palace run that cannot reproduce required terminal-network outputs must fail the backend run, not degrade into a partial result.
- Raw solver files must be retained long enough to audit report math, signs, units, and mesh settings.

## Target Common Output Contract
- `em_result.json`: normalized solver-neutral result summary.
- `network.csv`: frequency, complex S matrix, complex Z matrix, port reference data.
- `derived.csv`: Ltx, Lrx, M, k, R/Q/FOM/eta metrics.
- `port_vi.csv`: complex peak port voltages and currents with explicit current direction.
- `loss.csv`: copper, dielectric, ferrite, boundary, and total loss rows when available.
- `field_index.json`: references to field files, probes, slices, coordinate frame, and field units.
- `solver_manifest.json`: solver name/version, run command, mesh inputs, convergence settings, source TOML, geometry identity, and postprocess version.

## Phases

### Phase 0: Palace Feasibility Fixture
- Install or build a pinned Palace binary outside the active runtime path.
- Run one upstream Palace example to prove the binary, MPI launch path, CSV outputs, and ParaView field output.
- Record the exact Palace version, build flags, and command shape.
- No peetsfea runtime behavior changes in this phase.

### Phase 1: Solver-Neutral Result Schema
- Define parser/output structures for network, port V/I, derived values, losses, and fields.
- Map existing HFSS report outputs into the same schema before adding Palace.
- Write the S-to-Z and V/I-to-Z postprocess formulas with explicit reference impedance handling.
- Add fixture tests for sign convention, matrix shape, units, and complex number serialization.

### Phase 2: Minimal Two-Port Cross-Solver Check
- Use the active minimal STEP two-port baseline as the first controlled comparison.
- Generate the same geometry and port ledger once, then feed HFSS and Palace backend-specific adapters.
- Compare S and Z matrices over the existing frequency sweep.
- Acceptance target:
  - Matrix shape, units, and reciprocity must match exactly.
  - Low-complexity fixture L/R/Z values should converge within a tight tolerance after mesh refinement.
  - Any sign inversion in Z12/Z21 must be traced to port current direction and fixed in the common postprocess layer.

### Phase 3: SSW Cross-Solver Ladder
- Add SSW fixtures in increasing physics complexity:
  - TX/RX copper only.
  - TX/RX with FR4.
  - TX/RX with ferrite sheet.
  - Under-coil enabled case.
- Compare scalar metrics first: Ltx, Lrx, M, k, Rtx, Rrx, Qtx, Qrx, FOM.
- Compare full frequency curves only after scalar values are stable at 6.78 MHz.
- Keep ferrite comparisons separate because permeability/loss modeling can dominate solver differences.

### Phase 4: Data Capture for Surrogate Training
- Store both raw solver artifacts and normalized results for every accepted design point.
- Include failed samples with structured failure reasons, but do not train scalar regressors on failed solver outputs.
- Split datasets by topology and parameter ranges, not only by random row split.
- Track solver provenance so a future model can distinguish HFSS labels, Palace labels, and cross-solver-calibrated labels.
- Use active learning later: run the expensive solver on points where the surrogate uncertainty or HFSS/Palace disagreement is high.

### Phase 5: Geometry Token Contract
- Treat geometry generation tokens as the canonical ML input, not screenshots or CAD filenames.
- Tokens should describe physical operations and semantic ownership:
  - role, material, layer, conductor path, port endpoints, ferrite domain, non-model context, and boundary domain.
- Token payloads should be scalar/list/ref-only and deterministic.
- The same token stream should regenerate the geometry ledger, mesh intent, solver config, and ML feature input.
- Avoid encoding solver-specific mesh accidents as geometry truth.

### Phase 6: Surrogate Model Ladder
- Start with scalar targets: Z matrix, L/M/k/Q, losses, and eta metrics.
- Add curve targets after scalar calibration works: frequency-dependent S/Z curves.
- Add field targets last:
  - selected probes,
  - fixed 2D slices,
  - integrated domain quantities,
  - coordinate-conditioned field queries.
- Keep a physics sanity layer around model predictions: reciprocity, passivity checks, sign conventions, nonnegative losses, and monotonic constraints where physically justified.

## Validation Matrix

| Stage | Geometry | Physics | Required Comparison |
| --- | --- | --- | --- |
| V0 | Minimal two-port | copper pads, vacuum | S/Z matrix, port V/I |
| V1 | Simple coil pair | copper, no ferrite | L/M/k, R/Q, field probes |
| V2 | SSW pair | copper + FR4 | S/Z, losses, field slices |
| V3 | SSW + ferrite | ferrite loss/permeability | scalar trends, total loss, field concentration |
| V4 | Full design-space sample | active 0.3.8.0 SSW surface | distribution-level HFSS/Palace agreement |

## Risks
- Port normalization can make two correct solvers appear wrong.
- Mesh refinement near port gaps and copper edges can dominate Rac and Q.
- Ferrite material models may not be identical between HFSS and Palace.
- Large air domains at 6.78 MHz can be numerically awkward for full-wave FEM.
- ML labels will inherit solver bias unless HFSS/Palace disagreement is tracked.

## First Concrete Deliverables
- A pinned Palace sanity-run note under `run/` output.
- A solver-neutral `em_result.json` schema draft.
- A minimal two-port HFSS-vs-Palace comparison report.
- A small SSW no-ferrite comparison report.
- A decision note stating whether Palace can become a trusted second backend for dataset expansion.
