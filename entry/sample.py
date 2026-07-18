"""Sample random in-design-space SSW STEP files over a seed range.

Each seed in ``[--seed-start, --seed-end]`` draws one random point inside the reference design
space (``peetsfea data 0.3.x_sweep.toml``), freezes it to a fixed TOML, and exports a STEP scene plus
its ledger/token TOML into a gitignored output directory (one ``seed_<NNNNN>/`` per seed). This
module only generates artifacts; use ``entry/view.py`` to display a seed in the OCP viewer.

Run from ``run/``:

    ../.venv/bin/python ../entry/sample.py --seed-start 0 --seed-end 9
    ../.venv/bin/python ../entry/sample.py --seed-start 0 --seed-end 99 --jobs 10
    ../.venv/bin/python ../entry/sample.py --debug   # use the hardcoded DEBUG_* constants
"""

from __future__ import annotations

import argparse
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peetsfea.ssw_design_space import DEFAULT_REFERENCE_TOML_PATH, sample_ssw_fixed_tomls
from peetsfea.ssw_step import export_ssw_step_artifacts

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "run" / "ssw_step_samples"
SCENE_STEP_NAME = "ssw_scene.step"

# --debug uses these hardcoded constants instead of CLI args, so the VS Code launch.json
# config can run `sample.py --debug` with no arguments. Edit these to control a debug run.
DEBUG_SEED_START = 0
DEBUG_SEED_END = 9
DEBUG_JOBS = 10
DEBUG_OUTPUT_DIR = DEFAULT_OUTPUT_DIR
DEBUG_SWEEP_TOML = DEFAULT_REFERENCE_TOML_PATH


class SampledStep:
    def __init__(self, *, seed: int, design_id: str, toml_path: Path, step_path: Path, sample_dir: Path) -> None:
        self.seed = seed
        self.design_id = design_id
        self.toml_path = toml_path
        self.step_path = step_path
        self.sample_dir = sample_dir


def seed_output_dir(*, output_root: Path, seed: int) -> Path:
    return output_root / f"seed_{seed:05d}"


def generate_step_for_seed(
    *,
    seed: int,
    sweep_toml_path: Path,
    output_root: Path,
    reference_toml_path: Path,
) -> SampledStep:
    sample_dir = seed_output_dir(output_root=output_root, seed=seed)
    shutil.rmtree(sample_dir, ignore_errors=True)
    sample_dir.mkdir(parents=True, exist_ok=True)
    batch = sample_ssw_fixed_tomls(
        sample_count=1,
        seed=seed,
        sweep_toml_path=sweep_toml_path,
        output_dir=sample_dir,
        reference_toml_path=reference_toml_path,
    )
    sample = batch.samples[0]
    artifacts = export_ssw_step_artifacts(source_toml_path=sample.toml_path, output_dir=sample_dir, seed=seed)
    step_path = Path(artifacts["scene_step_path"])
    if not step_path.is_file():
        raise FileNotFoundError(f"STEP export did not create a scene file for seed {seed}: {step_path}")
    return SampledStep(
        seed=seed,
        design_id=sample.design_id,
        toml_path=sample.toml_path,
        step_path=step_path,
        sample_dir=sample_dir,
    )


def generate_steps(*, seeds: list[int], sweep_toml_path: Path, output_root: Path, jobs: int) -> list[SampledStep]:
    """Generate one STEP per seed, in parallel when ``jobs > 1``.

    Each seed writes to its own ``seed_<NNNNN>/`` directory, so the per-seed work is fully
    independent and safe to run across processes. Results are returned ordered by seed.
    """
    if jobs <= 1 or len(seeds) <= 1:
        return [
            generate_step_for_seed(
                seed=seed,
                sweep_toml_path=sweep_toml_path,
                output_root=output_root,
                reference_toml_path=sweep_toml_path,
            )
            for seed in seeds
        ]
    by_seed: dict[int, SampledStep] = {}
    with ProcessPoolExecutor(max_workers=min(jobs, len(seeds))) as executor:
        futures = {
            executor.submit(
                generate_step_for_seed,
                seed=seed,
                sweep_toml_path=sweep_toml_path,
                output_root=output_root,
                reference_toml_path=sweep_toml_path,
            ): seed
            for seed in seeds
        }
        for future in as_completed(futures):
            seed = futures[future]
            try:
                by_seed[seed] = future.result()
            except Exception as exc:
                raise RuntimeError(f"SSW STEP generation failed for seed {seed}") from exc
    return [by_seed[seed] for seed in seeds]


@dataclass(frozen=True)
class RunConfig:
    seed_start: int
    seed_end: int
    output_dir: Path
    sweep_toml: Path
    jobs: int


def run_sampling(config: RunConfig) -> list[SampledStep]:
    """Generate every seed in the config's range and print a seed -> design_id -> step index."""
    if config.seed_end < config.seed_start:
        raise ValueError(f"seed_end ({config.seed_end}) must be >= seed_start ({config.seed_start})")
    if config.jobs < 1:
        raise ValueError(f"jobs must be >= 1 (actual={config.jobs})")
    config.output_dir.mkdir(parents=True, exist_ok=True)
    seeds = list(range(config.seed_start, config.seed_end + 1))
    worker_count = min(config.jobs, len(seeds))
    print(f"Generating {len(seeds)} SSW STEP file(s) with {worker_count} worker(s) ...")
    samples = generate_steps(
        seeds=seeds,
        sweep_toml_path=config.sweep_toml,
        output_root=config.output_dir,
        jobs=config.jobs,
    )
    print(f"\nGenerated {len(samples)} SSW STEP file(s) under {config.output_dir}")
    print(f"{'seed':>6}  {'design_id':<24}  step")
    for sample in samples:
        print(f"{sample.seed:>6}  {sample.design_id:<24}  {sample.step_path}")
    return samples


def add_sampling_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the shared generation arguments (reused by entry/view.py)."""
    parser.add_argument("--seed-start", type=int, default=None, help="first seed (inclusive)")
    parser.add_argument("--seed-end", type=int, default=None, help="last seed (inclusive)")
    parser.add_argument("--jobs", "-j", type=int, default=1, help="parallel worker processes for generation")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="gitignored output root")
    parser.add_argument("--sweep-toml", type=Path, default=DEFAULT_REFERENCE_TOML_PATH, help="sweep SSOT TOML")


def _resolve_config(argv: list[str]) -> RunConfig:
    parser = argparse.ArgumentParser(description="Generate random in-space SSW STEP files over a seed range.")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="ignore CLI args and use the hardcoded DEBUG_* constants (for VS Code launch.json)",
    )
    add_sampling_arguments(parser)
    args = parser.parse_args(argv)
    if args.debug:
        return RunConfig(
            seed_start=DEBUG_SEED_START,
            seed_end=DEBUG_SEED_END,
            output_dir=DEBUG_OUTPUT_DIR,
            sweep_toml=DEBUG_SWEEP_TOML,
            jobs=DEBUG_JOBS,
        )
    if args.seed_start is None or args.seed_end is None:
        parser.error("--seed-start and --seed-end are required unless --debug is set")
    if args.jobs < 1:
        parser.error(f"--jobs must be >= 1 (actual={args.jobs})")
    return RunConfig(
        seed_start=args.seed_start,
        seed_end=args.seed_end,
        output_dir=args.output_dir,
        sweep_toml=args.sweep_toml,
        jobs=args.jobs,
    )


def main(argv: list[str] | None = None) -> list[SampledStep]:
    config = _resolve_config(sys.argv[1:] if argv is None else argv)
    return run_sampling(config)


if __name__ == "__main__":
    main()
