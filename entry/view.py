"""View one sampled SSW design in the OCP viewer (with per-body color and transparency).

By default this calls ``entry/sample.py`` to generate STEP files for the seed range, then shows
``--view-seed`` in the OCP viewer. Pass ``--no-sample`` to skip generation and view a seed that
was already sampled into the output directory. Pass ``--fixed`` to generate and view the authored
fixed-point TOML (``peetsfea data 0.3.x_fixed.toml``) instead of a sampled seed.

The viewer shows the rebuilt ``cq.Assembly`` (copper/coil/ferrite/non-model colors and
transparency), not the flattened STEP re-import which renders as a single default material.

Run from ``run/``:

    ../.venv/bin/python ../entry/view.py --seed-start 0 --seed-end 9 --view-seed 3
    ../.venv/bin/python ../entry/view.py --view-seed 3 --no-sample
    ../.venv/bin/python ../entry/view.py --fixed   # view peetsfea data 0.3.x_fixed.toml
    ../.venv/bin/python ../entry/view.py --debug   # use the hardcoded DEBUG_* constants
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocp_vscode import Camera, Collapse, show

from peetsfea.ssw_step import (
    DEFAULT_SOURCE_TOML_PATH,
    build_ssw_assembly,
    export_ssw_step_artifacts,
    load_ssw_fixed_spec,
)

from entry.sample import (
    DEFAULT_OUTPUT_DIR,
    SCENE_STEP_NAME,
    RunConfig,
    SampledStep,
    add_sampling_arguments,
    run_sampling,
    seed_output_dir,
)
from peetsfea.ssw_design_space import DEFAULT_REFERENCE_TOML_PATH

OCP_PORT = 3939
TOKEN_TOML_NAME = "coil_making_token.toml"
FIXED_SUBDIR = "fixed"
DEFAULT_FIXED_TOML = DEFAULT_SOURCE_TOML_PATH  # peetsfea data 0.3.x_fixed.toml
FIXED_SEED = -1  # sentinel: not sampled from a seed

# --debug uses these hardcoded constants instead of CLI args, so the VS Code launch.json
# config can run `view.py --debug` with no arguments. Edit these to control a debug run.
DEBUG_SEED_START = 0
DEBUG_SEED_END = 10
DEBUG_VIEW_SEED = 9
DEBUG_JOBS = 12
DEBUG_NO_SAMPLE = False
DEBUG_FIXED = True
DEBUG_OUTPUT_DIR = DEFAULT_OUTPUT_DIR
DEBUG_SWEEP_TOML = DEFAULT_REFERENCE_TOML_PATH
DEBUG_FIXED_TOML = DEFAULT_FIXED_TOML


@dataclass(frozen=True)
class ViewConfig:
    seed_start: int
    seed_end: int
    view_seed: int
    jobs: int
    no_sample: bool
    fixed: bool
    output_dir: Path
    sweep_toml: Path
    fixed_toml: Path


def load_existing_sample(*, output_root: Path, seed: int) -> SampledStep:
    """Reconstruct a SampledStep for an already-generated seed directory (for --no-sample)."""
    sample_dir = seed_output_dir(output_root=output_root, seed=seed)
    step_path = sample_dir / SCENE_STEP_NAME
    if not step_path.is_file():
        raise FileNotFoundError(
            f"no generated STEP for seed {seed}: {step_path} (run without --no-sample first)"
        )
    design_tomls = [p for p in sorted(sample_dir.glob("*.toml")) if p.name != TOKEN_TOML_NAME]
    if len(design_tomls) != 1:
        raise RuntimeError(
            f"expected exactly one design TOML in {sample_dir} (found {[p.name for p in design_tomls]})"
        )
    toml_path = design_tomls[0]
    return SampledStep(
        seed=seed,
        design_id=toml_path.stem,
        toml_path=toml_path,
        step_path=step_path,
        sample_dir=sample_dir,
    )


def generate_fixed(*, fixed_toml: Path, output_root: Path) -> SampledStep:
    """Export the authored fixed-point TOML (peetsfea data 0.3.x_fixed.toml) to a STEP scene."""
    if not fixed_toml.is_file():
        raise FileNotFoundError(f"fixed TOML does not exist: {fixed_toml}")
    fixed_dir = output_root / FIXED_SUBDIR
    fixed_dir.mkdir(parents=True, exist_ok=True)
    artifacts = export_ssw_step_artifacts(source_toml_path=fixed_toml, output_dir=fixed_dir, seed=0)
    step_path = Path(artifacts["scene_step_path"])
    if not step_path.is_file():
        raise FileNotFoundError(f"fixed STEP export did not create a scene file: {step_path}")
    return SampledStep(
        seed=FIXED_SEED,
        design_id=fixed_toml.stem,
        toml_path=fixed_toml,
        step_path=step_path,
        sample_dir=fixed_dir,
    )


def _display_name(sample: SampledStep) -> str:
    if sample.seed == FIXED_SEED:
        return f"fixed_{sample.design_id}"
    return f"seed_{sample.seed:05d}_{sample.design_id}"


def show_sample_in_ocp(sample: SampledStep) -> None:
    # Show the cq.Assembly rebuilt from the sampled spec, not the imported STEP: the assembly
    # carries per-body color and transparency (copper/coil/ferrite/non-model), whereas a
    # STEP re-import flattens everything to a single default (yellow) material.
    spec = load_ssw_fixed_spec(sample.toml_path)
    assembly = build_ssw_assembly(spec)
    show(
        assembly,
        names=[_display_name(sample)],
        axes=True,
        axes0=True,
        grid=True,
        collapse=Collapse.ROOT,
        reset_camera=Camera.RESET,
        port=OCP_PORT,
    )


def _resolve_config(argv: list[str]) -> ViewConfig:
    parser = argparse.ArgumentParser(description="Generate (via sample.py) and view one SSW design in OCP.")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="ignore CLI args and use the hardcoded DEBUG_* constants (for VS Code launch.json)",
    )
    parser.add_argument("--view-seed", type=int, default=None, help="seed whose design is shown in OCP")
    parser.add_argument(
        "--no-sample",
        action="store_true",
        help="do not re-run sampling; view a seed already generated in --output-dir",
    )
    parser.add_argument(
        "--fixed",
        action="store_true",
        help="ignore seeds; generate and view the authored fixed-point TOML (peetsfea data 0.3.x_fixed.toml)",
    )
    parser.add_argument("--fixed-toml", type=Path, default=DEFAULT_FIXED_TOML, help="fixed-point TOML for --fixed")
    add_sampling_arguments(parser)
    args = parser.parse_args(argv)
    if args.debug:
        return ViewConfig(
            seed_start=DEBUG_SEED_START,
            seed_end=DEBUG_SEED_END,
            view_seed=DEBUG_VIEW_SEED,
            jobs=DEBUG_JOBS,
            no_sample=DEBUG_NO_SAMPLE,
            fixed=DEBUG_FIXED,
            output_dir=DEBUG_OUTPUT_DIR,
            sweep_toml=DEBUG_SWEEP_TOML,
            fixed_toml=DEBUG_FIXED_TOML,
        )
    if args.jobs < 1:
        parser.error(f"--jobs must be >= 1 (actual={args.jobs})")
    if args.fixed:
        if args.no_sample:
            parser.error("--fixed and --no-sample are mutually exclusive")
        # seeds are unused in fixed mode.
        return ViewConfig(
            seed_start=FIXED_SEED,
            seed_end=FIXED_SEED,
            view_seed=FIXED_SEED,
            jobs=args.jobs,
            no_sample=False,
            fixed=True,
            output_dir=args.output_dir,
            sweep_toml=args.sweep_toml,
            fixed_toml=args.fixed_toml,
        )
    if args.no_sample:
        if args.view_seed is None:
            parser.error("--view-seed is required with --no-sample")
        # seed range is unused when not sampling; pin it to the view seed.
        return ViewConfig(
            seed_start=args.view_seed,
            seed_end=args.view_seed,
            view_seed=args.view_seed,
            jobs=args.jobs,
            no_sample=True,
            fixed=False,
            output_dir=args.output_dir,
            sweep_toml=args.sweep_toml,
            fixed_toml=args.fixed_toml,
        )
    if args.seed_start is None or args.seed_end is None:
        parser.error("--seed-start and --seed-end are required unless --debug, --no-sample, or --fixed is set")
    if args.seed_end < args.seed_start:
        parser.error(f"--seed-end ({args.seed_end}) must be >= --seed-start ({args.seed_start})")
    view_seed = args.seed_start if args.view_seed is None else args.view_seed
    if not (args.seed_start <= view_seed <= args.seed_end):
        parser.error(f"--view-seed ({view_seed}) must be within [{args.seed_start}, {args.seed_end}]")
    return ViewConfig(
        seed_start=args.seed_start,
        seed_end=args.seed_end,
        view_seed=view_seed,
        jobs=args.jobs,
        no_sample=False,
        fixed=False,
        output_dir=args.output_dir,
        sweep_toml=args.sweep_toml,
        fixed_toml=args.fixed_toml,
    )


def main(argv: list[str] | None = None) -> SampledStep:
    config = _resolve_config(sys.argv[1:] if argv is None else argv)
    if config.fixed:
        print(f"--fixed set; generating STEP from {config.fixed_toml}")
        view_sample = generate_fixed(fixed_toml=config.fixed_toml, output_root=config.output_dir)
        print(f"\nShowing fixed design ({view_sample.design_id}) in OCP on port {OCP_PORT} ...")
        show_sample_in_ocp(view_sample)
        return view_sample
    if config.no_sample:
        print(f"--no-sample set; reusing generated artifacts under {config.output_dir}")
        view_sample = load_existing_sample(output_root=config.output_dir, seed=config.view_seed)
    else:
        samples = run_sampling(
            RunConfig(
                seed_start=config.seed_start,
                seed_end=config.seed_end,
                output_dir=config.output_dir,
                sweep_toml=config.sweep_toml,
                jobs=config.jobs,
            )
        )
        view_sample = next(sample for sample in samples if sample.seed == config.view_seed)
    print(f"\nShowing seed {config.view_seed} ({view_sample.design_id}) in OCP on port {OCP_PORT} ...")
    show_sample_in_ocp(view_sample)
    return view_sample


if __name__ == "__main__":
    main()
