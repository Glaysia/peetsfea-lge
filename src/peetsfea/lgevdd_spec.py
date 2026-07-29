from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Literal

from peetsfea.lgevdd_constraints import (
    LgeEvddConstraintContext,
    LgeEvddConstraintRule,
    parse_lgevdd_constraint_rules,
    require_lgevdd_constraints_satisfied,
)

SPEC_VERSION = "0.2.0"
SCHEMA_ID = "peetsfea.lgevdd.planar.step.v2"
SUPPORTED_UNITS = "mm"
SUPPORTED_GEOMETRY_SCOPE = "primary_secondary_planar"
DEFAULT_SOURCE_TOML_PATH = Path(__file__).resolve().parent / "data" / "lgevdd_0.2.0_fixed.toml"

Point3 = tuple[float, float, float]


@dataclass(frozen=True)
class LgeEvddFr4Spec:
    object_id: str
    material: str
    center_xyz: Point3
    size_x_mm: float
    size_y_mm: float
    thickness_mm: float


@dataclass(frozen=True)
class LgeEvddPrimaryPlanarSpec:
    object_id: str
    material: str
    center_xyz: Point3
    center_keepout_width_x_mm: float
    center_keepout_height_y_mm: float
    lead_extension_x_mm: float
    turns: int
    layer_count: int
    trace_width_mm: float
    copper_thickness_mm: float
    inner_clearance_x_mm: float
    inner_clearance_y_mm: float
    turn_gap_x_mm: float
    turn_gap_y_mm: float
    connector_diameter_ratio_to_trace_width: float
    connector_circle_segments: int


@dataclass(frozen=True)
class LgeEvddSecondaryPlanarSpec:
    object_id: str
    body_ids: tuple[str, str]
    material: str
    body_count: int
    turns: int
    layer_count: int
    trace_width_mm: float
    copper_thickness_mm: float
    inner_clearance_x_mm: float
    inner_clearance_y_mm: float
    turn_gap_x_mm: float
    turn_gap_y_mm: float
    secondary_preg_mm: float
    lead_extension_x_mm: float


@dataclass(frozen=True)
class LgeEvddPcbSpec:
    source_toml_path: str
    units: Literal["mm"]
    legacy_winding_window_depth_mm: float
    fr4: LgeEvddFr4Spec
    primary: LgeEvddPrimaryPlanarSpec
    secondary: LgeEvddSecondaryPlanarSpec
    constraints: tuple[LgeEvddConstraintRule, ...]


def _require_key(table: dict[str, object], key: str, context: str) -> object:
    if key not in table:
        raise ValueError(f"{context} is missing required key {key!r}")
    return table[key]


def _require_table(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{context} must be a table")
    return value


def _require_non_empty_str(table: dict[str, object], key: str, context: str) -> str:
    raw_value = _require_key(table, key, context)
    if not isinstance(raw_value, str):
        raise TypeError(f"{context}.{key} must be str")
    if raw_value == "":
        raise ValueError(f"{context}.{key} must be non-empty")
    return raw_value


def _require_bool(table: dict[str, object], key: str, context: str, expected: bool) -> bool:
    raw_value = _require_key(table, key, context)
    if not isinstance(raw_value, bool):
        raise TypeError(f"{context}.{key} must be bool")
    if raw_value is not expected:
        raise ValueError(f"{context}.{key} must be {str(expected).lower()}")
    return raw_value


def _require_point3(table: dict[str, object], key: str, context: str) -> Point3:
    raw_value = _require_key(table, key, context)
    if isinstance(raw_value, (str, bytes)) or not isinstance(raw_value, list):
        raise TypeError(f"{context}.{key} must be a list of three numbers")
    if len(raw_value) != 3:
        raise ValueError(f"{context}.{key} must contain exactly three entries")
    parsed: list[float] = []
    for index, raw_component in enumerate(raw_value):
        if isinstance(raw_component, bool) or not isinstance(raw_component, (int, float)):
            raise TypeError(f"{context}.{key}[{index}] must be numeric")
        parsed.append(float(raw_component))
    return (parsed[0], parsed[1], parsed[2])


def _require_two_unique_strings(
    table: dict[str, object],
    key: str,
    context: str,
) -> tuple[str, str]:
    raw_values = _require_key(table, key, context)
    if isinstance(raw_values, (str, bytes)) or not isinstance(raw_values, list):
        raise TypeError(f"{context}.{key} must be a list of two strings")
    if len(raw_values) != 2:
        raise ValueError(f"{context}.{key} must contain exactly two entries")
    parsed: list[str] = []
    for index, raw_value in enumerate(raw_values):
        if not isinstance(raw_value, str):
            raise TypeError(f"{context}.{key}[{index}] must be str")
        if raw_value == "":
            raise ValueError(f"{context}.{key}[{index}] must be non-empty")
        parsed.append(raw_value)
    if parsed[0] == parsed[1]:
        raise ValueError(f"{context}.{key} entries must be unique")
    return (parsed[0], parsed[1])


def _require_fixed_float_range(
    table: dict[str, object],
    key: str,
    context: str,
    *,
    positive: bool,
) -> float:
    raw_range_table = _require_key(table, key, context)
    range_table = _require_table(raw_range_table, f"{context}.{key}")
    raw_range = _require_key(range_table, "range", f"{context}.{key}")
    if isinstance(raw_range, (str, bytes)) or not isinstance(raw_range, list):
        raise TypeError(f"{context}.{key}.range must be [integer, start, end, count]")
    if len(raw_range) != 4:
        raise ValueError(f"{context}.{key}.range must contain exactly four entries")

    raw_integer, raw_start, raw_end, raw_count = raw_range
    if raw_integer is not False:
        raise ValueError(f"{context}.{key}.range[0] must be false")
    if isinstance(raw_start, bool) or not isinstance(raw_start, (int, float)):
        raise TypeError(f"{context}.{key}.range[1] must be numeric")
    if isinstance(raw_end, bool) or not isinstance(raw_end, (int, float)):
        raise TypeError(f"{context}.{key}.range[2] must be numeric")
    if isinstance(raw_count, bool) or not isinstance(raw_count, int):
        raise TypeError(f"{context}.{key}.range[3] must be int")

    start = float(raw_start)
    end = float(raw_end)
    if start != end or raw_count != 1:
        raise ValueError(
            f"{context}.{key}.range must be fixed with start == end and count == 1 "
            f"(actual={raw_range!r})"
        )
    if positive and start <= 0.0:
        raise ValueError(f"{context}.{key} must be > 0 (actual={start})")
    return start


def _require_fixed_int_range(
    table: dict[str, object],
    key: str,
    context: str,
    *,
    positive: bool,
) -> int:
    raw_range_table = _require_key(table, key, context)
    range_table = _require_table(raw_range_table, f"{context}.{key}")
    raw_range = _require_key(range_table, "range", f"{context}.{key}")
    if isinstance(raw_range, (str, bytes)) or not isinstance(raw_range, list):
        raise TypeError(f"{context}.{key}.range must be [integer, start, end, count]")
    if len(raw_range) != 4:
        raise ValueError(f"{context}.{key}.range must contain exactly four entries")

    raw_integer, raw_start, raw_end, raw_count = raw_range
    if raw_integer is not True:
        raise ValueError(f"{context}.{key}.range[0] must be true")
    if isinstance(raw_start, bool) or not isinstance(raw_start, int):
        raise TypeError(f"{context}.{key}.range[1] must be int")
    if isinstance(raw_end, bool) or not isinstance(raw_end, int):
        raise TypeError(f"{context}.{key}.range[2] must be int")
    if isinstance(raw_count, bool) or not isinstance(raw_count, int):
        raise TypeError(f"{context}.{key}.range[3] must be int")
    if raw_start != raw_end or raw_count != 1:
        raise ValueError(
            f"{context}.{key}.range must be fixed with start == end and count == 1 "
            f"(actual={raw_range!r})"
        )
    if positive and raw_start <= 0:
        raise ValueError(f"{context}.{key} must be > 0 (actual={raw_start})")
    return raw_start


def _require_modeled_object(
    root: dict[str, object],
    *,
    role: str,
    context: str,
) -> dict[str, object]:
    raw_objects = _require_key(root, "modeled_objects", context)
    if isinstance(raw_objects, (str, bytes)) or not isinstance(raw_objects, list):
        raise TypeError(f"{context}.modeled_objects must be an array of tables")
    matches: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for index, raw_object in enumerate(raw_objects):
        object_context = f"{context}.modeled_objects[{index}]"
        object_table = _require_table(raw_object, object_context)
        object_id = _require_non_empty_str(object_table, "object_id", object_context)
        if object_id in seen_ids:
            raise ValueError(f"{context}.modeled_objects contains duplicate object_id {object_id!r}")
        seen_ids.add(object_id)
        object_role = _require_non_empty_str(object_table, "role", object_context)
        if object_role == role:
            matches.append(object_table)
    if len(matches) != 1:
        raise ValueError(
            f"{context} must contain exactly one role={role!r} object "
            f"(count={len(matches)})"
        )
    return matches[0]


def _parse_fr4(root: dict[str, object], *, context: str) -> LgeEvddFr4Spec:
    table = _require_modeled_object(root, role="fr4", context=context)
    dotted = "modeled_objects.fr4_board"
    _require_bool(table, "enabled", dotted, True)
    _require_bool(table, "model_state", dotted, True)
    primitive = _require_non_empty_str(table, "primitive", dotted)
    if primitive != "box":
        raise ValueError(f"{dotted}.primitive must be 'box' (actual={primitive!r})")
    plane = _require_non_empty_str(table, "plane", dotted)
    if plane != "XY":
        raise ValueError(f"{dotted}.plane must be 'XY' (actual={plane!r})")
    return LgeEvddFr4Spec(
        object_id=_require_non_empty_str(table, "object_id", dotted),
        material=_require_non_empty_str(table, "material", dotted),
        center_xyz=_require_point3(table, "center_xyz", dotted),
        size_x_mm=_require_fixed_float_range(table, "size_x_mm", dotted, positive=True),
        size_y_mm=_require_fixed_float_range(table, "size_y_mm", dotted, positive=True),
        thickness_mm=_require_fixed_float_range(table, "thickness_mm", dotted, positive=True),
    )


def _parse_primary(root: dict[str, object], *, context: str) -> LgeEvddPrimaryPlanarSpec:
    table = _require_modeled_object(root, role="primary_planar_coil", context=context)
    dotted = "modeled_objects.primary_planar_coil"
    _require_bool(table, "enabled", dotted, True)
    _require_bool(table, "model_state", dotted, True)
    expected_strings = {
        "conductor_kind": "planar",
        "plane": "XY",
        "terminal_side": "positive_x",
        "stack_axis": "Z",
    }
    for key, expected in expected_strings.items():
        actual = _require_non_empty_str(table, key, dotted)
        if actual != expected:
            raise ValueError(f"{dotted}.{key} must be {expected!r} (actual={actual!r})")
    mirror_normal = _require_point3(table, "bottom_layer_mirror_normal_xyz", dotted)
    if mirror_normal != (0.0, 1.0, 0.0):
        raise ValueError(
            f"{dotted}.bottom_layer_mirror_normal_xyz must be [0, 1, 0] "
            f"(actual={mirror_normal!r})"
        )
    return LgeEvddPrimaryPlanarSpec(
        object_id=_require_non_empty_str(table, "object_id", dotted),
        material=_require_non_empty_str(table, "material", dotted),
        center_xyz=_require_point3(table, "center_xyz", dotted),
        center_keepout_width_x_mm=_require_fixed_float_range(
            table,
            "center_keepout_width_x_mm",
            dotted,
            positive=True,
        ),
        center_keepout_height_y_mm=_require_fixed_float_range(
            table,
            "center_keepout_height_y_mm",
            dotted,
            positive=True,
        ),
        lead_extension_x_mm=_require_fixed_float_range(
            table,
            "lead_extension_x_mm",
            dotted,
            positive=True,
        ),
        turns=_require_fixed_int_range(table, "turns", dotted, positive=True),
        layer_count=_require_fixed_int_range(table, "layer_count", dotted, positive=True),
        trace_width_mm=_require_fixed_float_range(
            table,
            "trace_width_mm",
            dotted,
            positive=True,
        ),
        copper_thickness_mm=_require_fixed_float_range(
            table,
            "copper_thickness_mm",
            dotted,
            positive=True,
        ),
        inner_clearance_x_mm=_require_fixed_float_range(
            table,
            "inner_clearance_x_mm",
            dotted,
            positive=True,
        ),
        inner_clearance_y_mm=_require_fixed_float_range(
            table,
            "inner_clearance_y_mm",
            dotted,
            positive=True,
        ),
        turn_gap_x_mm=_require_fixed_float_range(
            table,
            "turn_gap_x_mm",
            dotted,
            positive=True,
        ),
        turn_gap_y_mm=_require_fixed_float_range(
            table,
            "turn_gap_y_mm",
            dotted,
            positive=True,
        ),
        connector_diameter_ratio_to_trace_width=_require_fixed_float_range(
            table,
            "connector_diameter_ratio_to_trace_width",
            dotted,
            positive=True,
        ),
        connector_circle_segments=_require_fixed_int_range(
            table,
            "connector_circle_segments",
            dotted,
            positive=True,
        ),
    )


def _parse_secondary(
    root: dict[str, object],
    *,
    context: str,
) -> LgeEvddSecondaryPlanarSpec:
    table = _require_modeled_object(root, role="secondary_planar_coil", context=context)
    dotted = "modeled_objects.secondary_planar_coil"
    _require_bool(table, "enabled", dotted, True)
    _require_bool(table, "model_state", dotted, True)
    expected_strings = {
        "center_tap_connection": "external",
        "conductor_kind": "planar",
        "layer_bridge_cross_section": "rectangle",
        "plane": "XY",
        "placement_reference": "primary_planar_coil",
        "stack_axis": "Z",
        "terminal_side": "negative_x",
    }
    for key, expected in expected_strings.items():
        actual = _require_non_empty_str(table, key, dotted)
        if actual != expected:
            raise ValueError(f"{dotted}.{key} must be {expected!r} (actual={actual!r})")
    body_ids = _require_two_unique_strings(table, "body_ids", dotted)
    body_count = _require_fixed_int_range(table, "body_count", dotted, positive=True)
    if body_count != len(body_ids):
        raise ValueError(
            f"{dotted}.body_count must equal len(body_ids) "
            f"(body_count={body_count}, body_ids={body_ids})"
        )
    return LgeEvddSecondaryPlanarSpec(
        object_id=_require_non_empty_str(table, "object_id", dotted),
        body_ids=body_ids,
        material=_require_non_empty_str(table, "material", dotted),
        body_count=body_count,
        turns=_require_fixed_int_range(table, "turns", dotted, positive=True),
        layer_count=_require_fixed_int_range(table, "layer_count", dotted, positive=True),
        trace_width_mm=_require_fixed_float_range(
            table,
            "trace_width_mm",
            dotted,
            positive=True,
        ),
        copper_thickness_mm=_require_fixed_float_range(
            table,
            "copper_thickness_mm",
            dotted,
            positive=True,
        ),
        inner_clearance_x_mm=_require_fixed_float_range(
            table,
            "inner_clearance_x_mm",
            dotted,
            positive=True,
        ),
        inner_clearance_y_mm=_require_fixed_float_range(
            table,
            "inner_clearance_y_mm",
            dotted,
            positive=True,
        ),
        turn_gap_x_mm=_require_fixed_float_range(
            table,
            "turn_gap_x_mm",
            dotted,
            positive=True,
        ),
        turn_gap_y_mm=_require_fixed_float_range(
            table,
            "turn_gap_y_mm",
            dotted,
            positive=True,
        ),
        secondary_preg_mm=_require_fixed_float_range(
            table,
            "secondary_preg_mm",
            dotted,
            positive=True,
        ),
        lead_extension_x_mm=_require_fixed_float_range(
            table,
            "lead_extension_x_mm",
            dotted,
            positive=True,
        ),
    )


def _constraint_context(
    *,
    legacy_winding_window_depth_mm: float,
    fr4: LgeEvddFr4Spec,
    primary: LgeEvddPrimaryPlanarSpec,
    secondary: LgeEvddSecondaryPlanarSpec,
) -> LgeEvddConstraintContext:
    primary_prefix = f"modeled_objects.{primary.object_id}"
    secondary_prefix = f"modeled_objects.{secondary.object_id}"
    return LgeEvddConstraintContext(
        primary_object_id=primary.object_id,
        secondary_object_id=secondary.object_id,
        path_values={
            "fixed_dimensions.legacy_winding_window_depth_mm": legacy_winding_window_depth_mm,
            f"modeled_objects.{fr4.object_id}.size_x_mm": fr4.size_x_mm,
            f"modeled_objects.{fr4.object_id}.size_y_mm": fr4.size_y_mm,
            f"modeled_objects.{fr4.object_id}.thickness_mm": fr4.thickness_mm,
            f"{primary_prefix}.center_keepout_width_x_mm": primary.center_keepout_width_x_mm,
            f"{primary_prefix}.center_keepout_height_y_mm": primary.center_keepout_height_y_mm,
            f"{primary_prefix}.lead_extension_x_mm": primary.lead_extension_x_mm,
            f"{primary_prefix}.turns": primary.turns,
            f"{primary_prefix}.layer_count": primary.layer_count,
            f"{primary_prefix}.trace_width_mm": primary.trace_width_mm,
            f"{primary_prefix}.copper_thickness_mm": primary.copper_thickness_mm,
            f"{primary_prefix}.inner_clearance_x_mm": primary.inner_clearance_x_mm,
            f"{primary_prefix}.inner_clearance_y_mm": primary.inner_clearance_y_mm,
            f"{primary_prefix}.turn_gap_x_mm": primary.turn_gap_x_mm,
            f"{primary_prefix}.turn_gap_y_mm": primary.turn_gap_y_mm,
            f"{primary_prefix}.connector_diameter_ratio_to_trace_width": (
                primary.connector_diameter_ratio_to_trace_width
            ),
            f"{primary_prefix}.connector_circle_segments": primary.connector_circle_segments,
            f"{secondary_prefix}.body_count": secondary.body_count,
            f"{secondary_prefix}.turns": secondary.turns,
            f"{secondary_prefix}.layer_count": secondary.layer_count,
            f"{secondary_prefix}.trace_width_mm": secondary.trace_width_mm,
            f"{secondary_prefix}.copper_thickness_mm": secondary.copper_thickness_mm,
            f"{secondary_prefix}.inner_clearance_x_mm": secondary.inner_clearance_x_mm,
            f"{secondary_prefix}.inner_clearance_y_mm": secondary.inner_clearance_y_mm,
            f"{secondary_prefix}.turn_gap_x_mm": secondary.turn_gap_x_mm,
            f"{secondary_prefix}.turn_gap_y_mm": secondary.turn_gap_y_mm,
            f"{secondary_prefix}.secondary_preg_mm": secondary.secondary_preg_mm,
            f"{secondary_prefix}.lead_extension_x_mm": secondary.lead_extension_x_mm,
        },
    )


def load_lgevdd_pcb_spec(toml_path: Path) -> LgeEvddPcbSpec:
    raw_spec = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    root = _require_table(raw_spec, toml_path.name)

    spec_version = _require_non_empty_str(root, "spec_version", toml_path.name)
    if spec_version != SPEC_VERSION:
        raise ValueError(f"spec_version must be {SPEC_VERSION!r} (actual={spec_version!r})")
    schema_id = _require_non_empty_str(root, "schema_id", toml_path.name)
    if schema_id != SCHEMA_ID:
        raise ValueError(f"schema_id must be {SCHEMA_ID!r} (actual={schema_id!r})")
    _require_bool(root, "runtime_compatible", toml_path.name, True)

    design = _require_table(_require_key(root, "design", toml_path.name), "design")
    units = _require_non_empty_str(design, "units", "design")
    if units != SUPPORTED_UNITS:
        raise ValueError(f"design.units must be {SUPPORTED_UNITS!r} (actual={units!r})")
    scope = _require_non_empty_str(design, "geometry_scope", "design")
    if scope != SUPPORTED_GEOMETRY_SCOPE:
        raise ValueError(
            f"design.geometry_scope must be {SUPPORTED_GEOMETRY_SCOPE!r} "
            f"(actual={scope!r})"
        )

    backend = _require_table(_require_key(root, "backend", toml_path.name), "backend")
    authoring_tool = _require_non_empty_str(backend, "authoring_tool", "backend")
    if authoring_tool != "build123d":
        raise ValueError(f"backend.authoring_tool must be 'build123d' (actual={authoring_tool!r})")
    interchange_format = _require_non_empty_str(backend, "interchange_format", "backend")
    if interchange_format != "step":
        raise ValueError(
            f"backend.interchange_format must be 'step' (actual={interchange_format!r})"
        )

    fixed_dimensions = _require_table(
        _require_key(root, "fixed_dimensions", toml_path.name),
        "fixed_dimensions",
    )
    legacy_window = _require_fixed_float_range(
        fixed_dimensions,
        "legacy_winding_window_depth_mm",
        "fixed_dimensions",
        positive=True,
    )
    fr4 = _parse_fr4(root, context=toml_path.name)
    primary = _parse_primary(root, context=toml_path.name)
    secondary = _parse_secondary(root, context=toml_path.name)
    if primary.center_xyz[2] != fr4.center_xyz[2]:
        raise ValueError(
            "primary_planar_coil.center_xyz[2] must equal fr4_board.center_xyz[2] "
            f"(primary_z={primary.center_xyz[2]}, fr4_z={fr4.center_xyz[2]})"
        )

    constraints_table = _require_table(
        _require_key(root, "constraints", toml_path.name),
        f"{toml_path.name}.constraints",
    )
    _require_bool(constraints_table, "require_single_series_path", "constraints", True)
    _require_bool(
        constraints_table,
        "require_connector_overlap_with_both_layers",
        "constraints",
        True,
    )
    _require_bool(
        constraints_table,
        "require_external_center_tap_connection",
        "constraints",
        True,
    )
    rules = parse_lgevdd_constraint_rules(root, context=toml_path.name)
    require_lgevdd_constraints_satisfied(
        rules=rules,
        constraint_context=_constraint_context(
            legacy_winding_window_depth_mm=legacy_window,
            fr4=fr4,
            primary=primary,
            secondary=secondary,
        ),
    )
    return LgeEvddPcbSpec(
        source_toml_path=str(toml_path.resolve()),
        units="mm",
        legacy_winding_window_depth_mm=legacy_window,
        fr4=fr4,
        primary=primary,
        secondary=secondary,
        constraints=rules,
    )


__all__ = [
    "DEFAULT_SOURCE_TOML_PATH",
    "LgeEvddFr4Spec",
    "LgeEvddPcbSpec",
    "LgeEvddPrimaryPlanarSpec",
    "LgeEvddSecondaryPlanarSpec",
    "Point3",
    "SCHEMA_ID",
    "SPEC_VERSION",
    "load_lgevdd_pcb_spec",
]
