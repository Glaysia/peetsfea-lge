from __future__ import annotations

import hashlib
import json
import random
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
import tomllib

from peetsfea.errors import PeetsfeaStageError
from peetsfea.ssw_step import build_ssw_body_boxes, load_ssw_fixed_spec

SPEC_VERSION = "0.3.9.0"
SCHEMA_ID = "peetsfea.ssw_coil.step.v1"
DEFAULT_REFERENCE_TOML_PATH = Path(__file__).resolve().parent / "data" / "0.3.x_sweep.toml"

RangeValue = int | float
TomlRoot = dict[str, object]


@dataclass(frozen=True)
class SswDesignSpaceViolation:
    path: str
    code: str
    message: str


@dataclass(frozen=True)
class SswDesignSpaceCheckResult:
    is_subset: bool
    is_point: bool
    dimension_count: int
    free_owner_paths: tuple[str, ...]
    violations: tuple[SswDesignSpaceViolation, ...]


@dataclass(frozen=True)
class SswAedtIdentity:
    design_id: str
    aedt_filename: str
    point_hash: str
    dimension_count: int
    free_owner_paths: tuple[str, ...]


@dataclass(frozen=True)
class SswSampledToml:
    index: int
    toml_path: Path
    design_id: str
    aedt_filename: str
    point_hash: str
    point_values: dict[str, RangeValue]


@dataclass(frozen=True)
class SswSampledTomlBatch:
    sample_count: int
    seed: int
    source_toml_path: Path
    reference_toml_path: Path
    output_dir: Path
    dimension_count: int
    free_owner_paths: tuple[str, ...]
    samples: tuple[SswSampledToml, ...]


@dataclass(frozen=True)
class _RangeDefinition:
    path: str
    is_integer: bool
    lower: float
    upper: float
    count: int


def _require_table(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{context} must be a table")
    return value


def _require_key(table: dict[str, object], key: str, context: str) -> object:
    if key not in table:
        raise ValueError(f"{context} is missing required key {key!r}")
    return table[key]


def _require_non_empty_str(table: dict[str, object], key: str, context: str) -> str:
    raw_value = _require_key(table, key, context)
    if not isinstance(raw_value, str) or raw_value == "":
        raise TypeError(f"{context}.{key} must be a non-empty str")
    return raw_value


def _range_number(value: object, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{context} must be numeric")
    return float(value)


def _range_count(value: object, context: str) -> int:
    count_float = _range_number(value, context)
    count = int(count_float)
    if float(count) != count_float:
        raise ValueError(f"{context} must be an integer count")
    return count


def _range_definition(table: dict[str, object], path: str) -> _RangeDefinition:
    raw_range = _require_key(table, "range", path)
    if isinstance(raw_range, (str, bytes)) or not isinstance(raw_range, list):
        raise TypeError(f"{path}.range must be a list")
    if len(raw_range) != 4:
        raise ValueError(f"{path}.range must contain exactly four entries")
    raw_integer = raw_range[0]
    if not isinstance(raw_integer, bool):
        raise TypeError(f"{path}.range[0] must be bool")
    lower = _range_number(raw_range[1], f"{path}.range[1]")
    upper = _range_number(raw_range[2], f"{path}.range[2]")
    count = _range_count(raw_range[3], f"{path}.range[3]")
    if lower > upper:
        raise ValueError(f"{path}.range lower must be <= upper")
    return _RangeDefinition(path=path, is_integer=raw_integer, lower=lower, upper=upper, count=count)


def _load_toml_root_from_text(toml_text: str, source_name: str) -> TomlRoot:
    raw_root = tomllib.loads(toml_text)
    root = _require_table(raw_root, source_name)
    spec_version = _require_non_empty_str(root, "spec_version", source_name)
    if spec_version != SPEC_VERSION:
        raise ValueError(f"{source_name} spec_version must be {SPEC_VERSION!r} (actual={spec_version!r})")
    schema_id = _require_non_empty_str(root, "schema_id", source_name)
    if schema_id != SCHEMA_ID:
        raise ValueError(f"{source_name} schema_id must be {SCHEMA_ID!r} (actual={schema_id!r})")
    return root


def _load_toml_root(toml_path: Path) -> TomlRoot:
    return _load_toml_root_from_text(toml_path.read_text(encoding="utf-8"), str(toml_path))


def _record_range(ranges: dict[str, _RangeDefinition], table: dict[str, object], path: str) -> None:
    if path in ranges:
        raise ValueError(f"duplicate SSW design-space range path {path!r}")
    ranges[path] = _range_definition(table, path)


def _collect_section_ranges(
    *,
    root: TomlRoot,
    section_name: Literal["fixed_dimensions", "ferrite"],
    ranges: dict[str, _RangeDefinition],
) -> None:
    if section_name not in root:
        return
    section = _require_table(root[section_name], section_name)
    for key, raw_child in section.items():
        if not isinstance(raw_child, dict):
            continue
        child = _require_table(raw_child, f"{section_name}.{key}")
        if "range" in child:
            _record_range(ranges, child, f"{section_name}.{key}")


def _collect_modeled_object_ranges(*, root: TomlRoot, ranges: dict[str, _RangeDefinition]) -> None:
    if "modeled_objects" not in root:
        return
    raw_objects = root["modeled_objects"]
    if isinstance(raw_objects, (str, bytes)) or not isinstance(raw_objects, list):
        raise TypeError("modeled_objects must be an array of tables")
    seen_roles: set[str] = set()
    for index, raw_object in enumerate(raw_objects):
        context = f"modeled_objects[{index}]"
        table = _require_table(raw_object, context)
        role = _require_non_empty_str(table, "role", context)
        if role in seen_roles:
            raise ValueError(f"modeled_objects role must be unique (duplicate={role!r})")
        seen_roles.add(role)
        for key, raw_child in table.items():
            if key in {"object_id", "role", "material", "model_state"}:
                continue
            if not isinstance(raw_child, dict):
                continue
            child = _require_table(raw_child, f"{context}.{key}")
            if "range" in child:
                _record_range(ranges, child, f"modeled_objects[role={role}].{key}")


def _range_definitions(root: TomlRoot) -> dict[str, _RangeDefinition]:
    ranges: dict[str, _RangeDefinition] = {}
    _collect_section_ranges(root=root, section_name="fixed_dimensions", ranges=ranges)
    _collect_section_ranges(root=root, section_name="ferrite", ranges=ranges)
    _collect_modeled_object_ranges(root=root, ranges=ranges)
    return ranges


def _reference_free_ranges(reference_toml_path: Path) -> dict[str, _RangeDefinition]:
    reference_ranges = _range_definitions(_load_toml_root(reference_toml_path))
    free_ranges: dict[str, _RangeDefinition] = {}
    for path, range_def in reference_ranges.items():
        if range_def.count != 1:
            if range_def.count <= 0:
                raise ValueError(f"reference free range count must be positive (path={path}, count={range_def.count})")
            free_ranges[path] = range_def
    return free_ranges


def _violation(path: str, code: str, message: str) -> SswDesignSpaceViolation:
    return SswDesignSpaceViolation(path=path, code=code, message=message)


def _integer_value_violations(*, candidate: _RangeDefinition) -> tuple[SswDesignSpaceViolation, ...]:
    if not candidate.is_integer:
        return ()
    violations: list[SswDesignSpaceViolation] = []
    if float(int(candidate.lower)) != candidate.lower:
        violations.append(
            _violation(candidate.path, "integer_lower_not_integral", "candidate integer lower bound must be integral")
        )
    if float(int(candidate.upper)) != candidate.upper:
        violations.append(
            _violation(candidate.path, "integer_upper_not_integral", "candidate integer upper bound must be integral")
        )
    return tuple(violations)


def _range_violations(*, reference: _RangeDefinition, candidate: _RangeDefinition) -> tuple[SswDesignSpaceViolation, ...]:
    violations: list[SswDesignSpaceViolation] = []
    if candidate.is_integer != reference.is_integer:
        violations.append(
            _violation(
                candidate.path,
                "integer_flag_mismatch",
                "candidate integer flag must match the reference free range",
            )
        )
    if candidate.count <= 0:
        violations.append(_violation(candidate.path, "non_positive_count", "candidate count must be positive"))
    if candidate.lower < reference.lower:
        violations.append(
            _violation(candidate.path, "lower_bound_outside_reference", "candidate lower bound is below reference")
        )
    if candidate.upper > reference.upper:
        violations.append(
            _violation(candidate.path, "upper_bound_outside_reference", "candidate upper bound is above reference")
        )
    violations.extend(_integer_value_violations(candidate=candidate))
    return tuple(violations)


def _is_point(candidate_ranges: dict[str, _RangeDefinition], free_owner_paths: tuple[str, ...]) -> bool:
    for path in free_owner_paths:
        candidate = candidate_ranges[path]
        if candidate.lower != candidate.upper:
            return False
    return True


def _check_ranges_in_design_space(
    candidate_ranges: dict[str, _RangeDefinition],
    reference_toml_path: Path,
) -> SswDesignSpaceCheckResult:
    free_ranges = _reference_free_ranges(reference_toml_path)
    free_owner_paths = tuple(sorted(free_ranges))
    violations: list[SswDesignSpaceViolation] = []
    for path in free_owner_paths:
        reference = free_ranges[path]
        if path not in candidate_ranges:
            violations.append(_violation(path, "missing_free_path", "candidate is missing reference free range path"))
            continue
        candidate = candidate_ranges[path]
        violations.extend(_range_violations(reference=reference, candidate=candidate))
    is_subset = len(violations) == 0
    is_point = is_subset and _is_point(candidate_ranges, free_owner_paths)
    return SswDesignSpaceCheckResult(
        is_subset=is_subset,
        is_point=is_point,
        dimension_count=len(free_owner_paths),
        free_owner_paths=free_owner_paths,
        violations=tuple(violations),
    )


def check_ssw_toml_in_design_space(
    candidate_toml_path: Path,
    reference_toml_path: Path = DEFAULT_REFERENCE_TOML_PATH,
) -> SswDesignSpaceCheckResult:
    candidate_ranges = _range_definitions(_load_toml_root(candidate_toml_path))
    return _check_ranges_in_design_space(candidate_ranges, reference_toml_path)


def check_ssw_toml_text_in_design_space(
    candidate_toml_text: str,
    reference_toml_path: Path = DEFAULT_REFERENCE_TOML_PATH,
    source_name: str = "<sweep_toml_text>",
) -> SswDesignSpaceCheckResult:
    candidate_ranges = _range_definitions(_load_toml_root_from_text(candidate_toml_text, source_name))
    return _check_ranges_in_design_space(candidate_ranges, reference_toml_path)


def _point_value(range_def: _RangeDefinition) -> RangeValue:
    if range_def.lower != range_def.upper:
        raise ValueError(f"{range_def.path} is not a realized point range")
    if range_def.is_integer:
        return int(range_def.lower)
    return float(range_def.lower)


def _identity_payload(
    *,
    candidate_ranges: dict[str, _RangeDefinition],
    free_owner_paths: tuple[str, ...],
) -> dict[str, object]:
    point_values: dict[str, RangeValue] = {}
    for path in free_owner_paths:
        point_values[path] = _point_value(candidate_ranges[path])
    return {
        "free_owner_paths": list(free_owner_paths),
        "point_values": point_values,
    }


def _point_values_from_ranges(
    *,
    candidate_ranges: dict[str, _RangeDefinition],
    free_owner_paths: tuple[str, ...],
) -> dict[str, RangeValue]:
    payload = _identity_payload(candidate_ranges=candidate_ranges, free_owner_paths=free_owner_paths)
    point_values = payload["point_values"]
    assert isinstance(point_values, dict), "identity payload point_values must be a dict"
    typed_values: dict[str, RangeValue] = {}
    for path in free_owner_paths:
        if path not in point_values:
            raise ValueError(f"identity payload is missing point value for {path!r}")
        value = point_values[path]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"identity payload point value must be numeric (path={path}, value={value!r})")
        typed_values[path] = value
    return typed_values


def _point_hash(payload: dict[str, object]) -> str:
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.blake2b(payload_bytes, digest_size=8).hexdigest()


def _raise_for_check_failure(result: SswDesignSpaceCheckResult) -> None:
    if result.is_subset:
        return
    details = "; ".join(f"{violation.path}:{violation.code}" for violation in result.violations)
    raise ValueError(f"SSW candidate TOML is outside the reference design space ({details})")


def _raise_for_non_point(candidate_ranges: dict[str, _RangeDefinition], free_owner_paths: tuple[str, ...]) -> None:
    non_point_paths: list[str] = []
    for path in free_owner_paths:
        candidate = candidate_ranges[path]
        if candidate.lower != candidate.upper:
            non_point_paths.append(path)
    if len(non_point_paths) != 0:
        raise ValueError(
            "SSW AEDT identity requires a single realized point; non-point free paths: "
            + ", ".join(non_point_paths)
        )


def _require_int_argument(value: int, context: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{context} must be an int")


def _require_positive_int_argument(value: int, context: str) -> None:
    _require_int_argument(value, context)
    if value <= 0:
        raise ValueError(f"{context} must be positive")


def _raise_for_non_reference_varying_ranges(
    candidate_ranges: dict[str, _RangeDefinition],
    free_owner_paths: tuple[str, ...],
) -> None:
    free_path_set = set(free_owner_paths)
    varying_paths: list[str] = []
    for path, range_def in candidate_ranges.items():
        if path in free_path_set:
            continue
        if range_def.lower != range_def.upper or range_def.count != 1:
            varying_paths.append(path)
    if len(varying_paths) != 0:
        raise ValueError(
            "SSW sampling only varies reference free paths; non-reference varying ranges: "
            + ", ".join(sorted(varying_paths))
        )


def _sample_range_value(rng: random.Random, range_def: _RangeDefinition) -> RangeValue:
    if range_def.is_integer:
        return rng.randint(int(range_def.lower), int(range_def.upper))
    return float(rng.uniform(range_def.lower, range_def.upper))


def _sample_point_values(
    *,
    rng: random.Random,
    candidate_ranges: dict[str, _RangeDefinition],
    free_owner_paths: tuple[str, ...],
) -> dict[str, RangeValue]:
    point_values: dict[str, RangeValue] = {}
    for path in free_owner_paths:
        point_values[path] = _sample_range_value(rng, candidate_ranges[path])
    return point_values


def _assignment_key(stripped_line: str) -> str:
    if "=" not in stripped_line:
        return ""
    key, _separator, _value = stripped_line.partition("=")
    return key.strip()


def _line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    return ""


def _line_indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" \t"))]


def _format_range_value(value: RangeValue) -> str:
    if isinstance(value, int):
        return str(value)
    return repr(float(value))


def _format_frozen_range(range_def: _RangeDefinition, point_value: RangeValue) -> str:
    integer_flag = "true" if range_def.is_integer else "false"
    formatted_value = _format_range_value(point_value)
    return f"[{integer_flag}, {formatted_value}, {formatted_value}, 1]"


def _section_path_from_header(
    *,
    header: str,
    modeled_role: str,
    modeled_role_is_bound: bool,
) -> tuple[bool, str]:
    if header.startswith("fixed_dimensions."):
        return (True, header)
    if header.startswith("ferrite."):
        return (True, header)
    if header.startswith("modeled_objects."):
        if not modeled_role_is_bound:
            raise ValueError(f"modeled_objects range table {header!r} appears before its role")
        field = header.removeprefix("modeled_objects.")
        return (True, f"modeled_objects[role={modeled_role}].{field}")
    return (False, "")


def _role_from_assignment(stripped_line: str) -> str:
    raw_table = tomllib.loads(stripped_line)
    table = _require_table(raw_table, "modeled_objects.role")
    return _require_non_empty_str(table, "role", "modeled_objects")


def _sampled_toml_text(
    *,
    source_text: str,
    point_values: dict[str, RangeValue],
    candidate_ranges: dict[str, _RangeDefinition],
) -> str:
    rendered_lines: list[str] = []
    replaced_paths: set[str] = set()
    modeled_role = ""
    modeled_role_is_bound = False
    inside_modeled_object = False
    current_path = ""
    current_path_is_bound = False
    for line in source_text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("[[") and stripped.endswith("]]"):
            array_header = stripped[2:-2].strip()
            inside_modeled_object = array_header == "modeled_objects"
            modeled_role = ""
            modeled_role_is_bound = False
            current_path = ""
            current_path_is_bound = False
        elif stripped.startswith("[") and stripped.endswith("]"):
            section_header = stripped[1:-1].strip()
            current_path_is_bound, current_path = _section_path_from_header(
                header=section_header,
                modeled_role=modeled_role,
                modeled_role_is_bound=modeled_role_is_bound,
            )
        elif inside_modeled_object and _assignment_key(stripped) == "role":
            modeled_role = _role_from_assignment(stripped)
            modeled_role_is_bound = True

        if current_path_is_bound and _assignment_key(stripped) == "range" and current_path in point_values:
            if current_path in replaced_paths:
                raise ValueError(f"duplicate range line for sampled path {current_path!r}")
            range_def = candidate_ranges[current_path]
            rendered_lines.append(
                f"{_line_indent(line)}range = {_format_frozen_range(range_def, point_values[current_path])}"
                f"{_line_ending(line)}"
            )
            replaced_paths.add(current_path)
            continue
        rendered_lines.append(line)
    missing_paths = tuple(sorted(set(point_values) - replaced_paths))
    if len(missing_paths) != 0:
        raise ValueError("sampled TOML source is missing range lines for paths: " + ", ".join(missing_paths))
    return "".join(rendered_lines)


def build_ssw_aedt_identity(
    candidate_toml_path: Path,
    reference_toml_path: Path = DEFAULT_REFERENCE_TOML_PATH,
) -> SswAedtIdentity:
    result = check_ssw_toml_in_design_space(candidate_toml_path, reference_toml_path)
    _raise_for_check_failure(result)
    candidate_ranges = _range_definitions(_load_toml_root(candidate_toml_path))
    _raise_for_non_point(candidate_ranges, result.free_owner_paths)
    payload = _identity_payload(candidate_ranges=candidate_ranges, free_owner_paths=result.free_owner_paths)
    point_hash = _point_hash(payload)
    design_id = f"{SPEC_VERSION.replace('.', '_')}_p{point_hash}"
    return SswAedtIdentity(
        design_id=design_id,
        aedt_filename=f"{design_id}.aedt",
        point_hash=point_hash,
        dimension_count=result.dimension_count,
        free_owner_paths=result.free_owner_paths,
    )


def point_values_for_ssw_fixed_toml(
    candidate_toml_path: Path,
    reference_toml_path: Path = DEFAULT_REFERENCE_TOML_PATH,
) -> dict[str, RangeValue]:
    result = check_ssw_toml_in_design_space(candidate_toml_path, reference_toml_path)
    _raise_for_check_failure(result)
    candidate_ranges = _range_definitions(_load_toml_root(candidate_toml_path))
    _raise_for_non_point(candidate_ranges, result.free_owner_paths)
    return _point_values_from_ranges(candidate_ranges=candidate_ranges, free_owner_paths=result.free_owner_paths)


def sample_ssw_fixed_tomls(
    sample_count: int,
    seed: int,
    sweep_toml_path: Path,
    output_dir: Path,
    reference_toml_path: Path = DEFAULT_REFERENCE_TOML_PATH,
    max_attempts_per_sample: int = 1000,
) -> SswSampledTomlBatch:
    _require_positive_int_argument(sample_count, "sample_count")
    _require_int_argument(seed, "seed")
    _require_positive_int_argument(max_attempts_per_sample, "max_attempts_per_sample")
    result = check_ssw_toml_in_design_space(sweep_toml_path, reference_toml_path)
    _raise_for_check_failure(result)
    candidate_ranges = _range_definitions(_load_toml_root(sweep_toml_path))
    _raise_for_non_reference_varying_ranges(candidate_ranges, result.free_owner_paths)
    source_text = sweep_toml_path.read_text(encoding="utf-8")
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    samples: list[SswSampledToml] = []
    seen_design_ids: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="ssw_sample_attempt_", dir=output_dir) as temp_dir_text:
        temp_dir = Path(temp_dir_text)
        for index in range(sample_count):
            accepted = False
            last_rejection = "no attempts were made"
            for attempt in range(max_attempts_per_sample):
                point_values = _sample_point_values(
                    rng=rng,
                    candidate_ranges=candidate_ranges,
                    free_owner_paths=result.free_owner_paths,
                )
                sampled_text = _sampled_toml_text(
                    source_text=source_text,
                    point_values=point_values,
                    candidate_ranges=candidate_ranges,
                )
                attempt_path = temp_dir / f"sample_{index:05d}_{attempt:05d}.toml"
                attempt_path.write_text(sampled_text, encoding="utf-8")
                try:
                    spec = load_ssw_fixed_spec(attempt_path)
                    build_ssw_body_boxes(spec)
                except ValueError as exc:
                    last_rejection = f"fixed spec validation failed: {exc}"
                    attempt_path.unlink()
                    continue
                identity = build_ssw_aedt_identity(attempt_path, reference_toml_path)
                accepted_ranges = _range_definitions(_load_toml_root(attempt_path))
                accepted_point_values = _point_values_from_ranges(
                    candidate_ranges=accepted_ranges,
                    free_owner_paths=result.free_owner_paths,
                )
                if identity.design_id in seen_design_ids:
                    last_rejection = f"duplicate sampled design_id {identity.design_id!r}"
                    attempt_path.unlink()
                    continue
                final_path = output_dir / f"{identity.design_id}.toml"
                if final_path.exists():
                    raise FileExistsError(f"sample output already exists: {final_path}")
                attempt_path.replace(final_path)
                seen_design_ids.add(identity.design_id)
                samples.append(
                    SswSampledToml(
                        index=index,
                        toml_path=final_path,
                        design_id=identity.design_id,
                        aedt_filename=identity.aedt_filename,
                        point_hash=identity.point_hash,
                        point_values=accepted_point_values,
                    )
                )
                accepted = True
                break
            if not accepted:
                raise RuntimeError(
                    f"failed to generate SSW sample {index} after {max_attempts_per_sample} attempts: "
                    f"{last_rejection}"
                )
    return SswSampledTomlBatch(
        sample_count=sample_count,
        seed=seed,
        source_toml_path=sweep_toml_path,
        reference_toml_path=reference_toml_path,
        output_dir=output_dir,
        dimension_count=result.dimension_count,
        free_owner_paths=result.free_owner_paths,
        samples=tuple(samples),
    )


def _design_space_violation_message(result: SswDesignSpaceCheckResult) -> str:
    return "; ".join(f"{violation.path}:{violation.code}" for violation in result.violations)


def validate_sweep_toml_text(sweep_text: str) -> None:
    """Raise :class:`PeetsfeaStageError` when ``sweep_text`` leaves the reference design space.

    Full strictness: bounds, integer-flag parity, and positive counts are all checked against
    the reference sweep SSOT (:data:`DEFAULT_REFERENCE_TOML_PATH`). Returns ``None`` when valid.
    """
    try:
        result = check_ssw_toml_text_in_design_space(sweep_text, source_name="<sweep_toml_text>")
    except (TypeError, ValueError) as exc:
        raise PeetsfeaStageError(stage="validate", error_type=type(exc).__name__, message=str(exc)) from exc
    if not result.is_subset:
        raise PeetsfeaStageError(
            stage="validate",
            error_type="design_space_violation",
            message=f"sweep TOML is outside the reference design space ({_design_space_violation_message(result)})",
        )


def sample_fixed_candidates_from_toml_text(sweep_text: str, count: int, seed: int) -> list[str]:
    """Expand a sweep TOML text into ``count`` fixed candidate TOML texts.

    Deterministic for a given ``(sweep_text, count, seed)``. The scratch directory honors the
    ambient ``TMPDIR``/``TMP`` environment so the runner controls placement (no hardcoded
    ``/tmp`` or ``/dev/shm`` use).
    """
    validate_sweep_toml_text(sweep_text)
    try:
        with tempfile.TemporaryDirectory(prefix="ssw_candidate_") as scratch_text:
            scratch_dir = Path(scratch_text)
            sweep_path = scratch_dir / "sweep.toml"
            sweep_path.write_text(sweep_text, encoding="utf-8")
            batch = sample_ssw_fixed_tomls(
                sample_count=count,
                seed=seed,
                sweep_toml_path=sweep_path,
                output_dir=scratch_dir / "candidates",
            )
            return [sample.toml_path.read_text(encoding="utf-8") for sample in batch.samples]
    except PeetsfeaStageError:
        raise
    except (TypeError, ValueError, RuntimeError, FileExistsError) as exc:
        raise PeetsfeaStageError(stage="sample", error_type=type(exc).__name__, message=str(exc)) from exc


__all__ = [
    "DEFAULT_REFERENCE_TOML_PATH",
    "SswAedtIdentity",
    "SswDesignSpaceCheckResult",
    "SswDesignSpaceViolation",
    "SswSampledToml",
    "SswSampledTomlBatch",
    "build_ssw_aedt_identity",
    "check_ssw_toml_in_design_space",
    "check_ssw_toml_text_in_design_space",
    "point_values_for_ssw_fixed_toml",
    "sample_fixed_candidates_from_toml_text",
    "sample_ssw_fixed_tomls",
    "validate_sweep_toml_text",
]
