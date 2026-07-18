from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, TypedDict, cast
import tomllib

import cadquery as cq

from peetsfea import coilmaker
from peetsfea.console_log import log_call_duration
from peetsfea.ssw_step_constraints import (
    SswConstraintCoil,
    SswConstraintRule,
    parse_ssw_constraint_rules,
    require_ssw_constraints_satisfied,
)

DEFAULT_SOURCE_TOML_PATH = Path(__file__).resolve().parent / "data" / "0.3.x_fixed.toml"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "run" / "ssw_0_3_0_fixed"
DEFAULT_SCENE_STEP_NAME = "ssw_scene.step"
DEFAULT_LEDGER_NAME = "ssw_step_ledger.json"
DEFAULT_TOKEN_TOML_NAME = "coil_making_token.toml"
SPEC_VERSION = "0.3.9.0"
SCHEMA_ID = "peetsfea.ssw_coil.step.v1"
SUPPORTED_UNITS = "mm"
MULL_FERRITE_MATERIAL = "mull_ferrite"
MULL_FERRITE_TRANSPARENCY = 0.0
_NONE_TYPE = type(None)

Point3 = tuple[float, float, float]
Role = Literal["tx_ssw_coil", "tx_under_coil", "rx_ssw_coil"]
BodyRole = Literal["fr4", "copper", "non_model", "ferrite"]


class _ChildNameCarrier(Protocol):
    name: object


class _ChildObjectCarrier(Protocol):
    obj: object


class _ChildLocationCarrier(Protocol):
    loc: object


@dataclass(frozen=True)
class FrozenRange:
    is_integer: bool
    value: float


@dataclass(frozen=True)
class FixedDimensions:
    fr4_thickness_mm: float
    copper_thickness_mm: float
    port_length_mm: float
    port_landing_pad_mm: float
    port_landing_drop_mm: float
    port_landing_overlap_mm: float
    width_max_mm: float
    height_max_mm: float
    tx_rx_min_distance_mm: float
    mull_ferrite_thickness_mm: float


@dataclass(frozen=True)
class SswCoilParameters:
    role: Role
    is_under_coil_enabled: bool
    width_ratio: float
    height_ratio: float
    is_ssw_enabled: bool
    turn_n_int: int
    gap_ratio: float
    void_area_ratio: float
    void_profile: int
    no_ssw_qturn_start_int: int
    no_ssw_qturn_n_int: int
    pcb_gap_mm: float
    twist_factor: int

    def width_mm(self, fixed: FixedDimensions) -> float:
        return fixed.width_max_mm * self.width_ratio

    def height_mm(self, fixed: FixedDimensions) -> float:
        return fixed.height_max_mm * self.height_ratio


@dataclass(frozen=True)
class NonModelBox:
    object_id: str
    kind: str
    material: str
    origin_xyz: Point3
    size_xyz: Point3
    transparency: float


@dataclass(frozen=True)
class FerriteParameters:
    tx_mull_is_enabled: bool
    tx_mull_position_ratio: float
    tx_mull_sheet_count: int
    rx_mull_is_enabled: bool
    rx_mull_position_ratio: float


@dataclass(frozen=True)
class SswFixedSpec:
    source_toml_path: str
    units: Literal["mm"]
    fixed: FixedDimensions
    ferrite: FerriteParameters
    non_model_objects: tuple[NonModelBox, ...]
    constraints: tuple[SswConstraintRule, ...]
    tx: SswCoilParameters
    tx_under: SswCoilParameters
    rx: SswCoilParameters


@dataclass(frozen=True)
class _BodyBox:
    name: str
    role: BodyRole
    material: str
    center_xyz: Point3
    size_xyz: Point3
    transparency: float


@dataclass(frozen=True)
class _CoilScenePart:
    params: SswCoilParameters
    assembly: cq.Assembly
    placement: cq.Location
    bodies: tuple[_BodyBox, ...]


@dataclass(frozen=True)
class _SswSceneBuild:
    spec: SswFixedSpec
    bodies: tuple[_BodyBox, ...]
    assembly: cq.Assembly
    parts: tuple[_CoilScenePart, ...]


@dataclass(frozen=True)
class _Bounds:
    xmin: float
    xmax: float
    ymin: float
    ymax: float
    zmin: float
    zmax: float

    @property
    def center_x(self) -> float:
        return (self.xmin + self.xmax) / 2.0

    @property
    def center_y(self) -> float:
        return (self.ymin + self.ymax) / 2.0

    @property
    def center_z(self) -> float:
        return (self.zmin + self.zmax) / 2.0

    @property
    def size_x(self) -> float:
        return self.xmax - self.xmin

    @property
    def size_y(self) -> float:
        return self.ymax - self.ymin

    @property
    def size_z(self) -> float:
        return self.zmax - self.zmin


class BodyLedgerEntry(TypedDict):
    object_id: str
    role: BodyRole
    material: str
    transparency: float
    center_xyz: list[float]
    size_xyz: list[float]


class SswStepLedger(TypedDict):
    source_toml_path: str
    scene_step_path: str
    token_toml_path: str
    seed: int
    units: Literal["mm"]
    body_names: list[str]
    copper_body_names: list[str]
    fr4_body_names: list[str]
    non_model_body_names: list[str]
    ferrite_body_names: list[str]
    bodies: list[BodyLedgerEntry]


class SswStepArtifacts(TypedDict):
    source_toml_path: str
    scene_step_path: str
    ledger_path: str
    token_toml_path: str
    seed: int
    body_names: list[str]


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


def _require_bool(value: object, context: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{context} must be bool")
    return value


def _require_numeric(value: object, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{context} must be numeric")
    return float(value)


def _require_point3(table: dict[str, object], key: str, context: str, *, positive: bool) -> Point3:
    raw_value = _require_key(table, key, context)
    if isinstance(raw_value, (str, bytes)) or not isinstance(raw_value, list):
        raise TypeError(f"{context}.{key} must be a list of three numbers")
    if len(raw_value) != 3:
        raise ValueError(f"{context}.{key} must contain exactly three entries")
    parsed: list[float] = []
    for index, raw_component in enumerate(raw_value):
        component = _require_numeric(raw_component, f"{context}.{key}[{index}]")
        if positive and component <= 0.0:
            raise ValueError(f"{context}.{key}[{index}] must be > 0")
        parsed.append(component)
    return (parsed[0], parsed[1], parsed[2])


def _require_frozen_range(table: dict[str, object], context: str) -> FrozenRange:
    raw_range = _require_key(table, "range", context)
    if isinstance(raw_range, (str, bytes)) or not isinstance(raw_range, list):
        raise TypeError(f"{context}.range must be a list")
    if len(raw_range) != 4:
        raise ValueError(f"{context}.range must contain exactly four entries")
    is_integer = _require_bool(raw_range[0], f"{context}.range[0]")
    lower = _require_numeric(raw_range[1], f"{context}.range[1]")
    upper = _require_numeric(raw_range[2], f"{context}.range[2]")
    count_float = _require_numeric(raw_range[3], f"{context}.range[3]")
    count = int(count_float)
    if float(count) != count_float:
        raise ValueError(f"{context}.range[3] must be an integer count")
    if lower != upper or count != 1:
        raise ValueError(f"{context}.range must be frozen as [*, value, value, 1] (actual={raw_range!r})")
    if is_integer and int(lower) != lower:
        raise ValueError(f"{context}.range integer value must be integral (actual={lower!r})")
    return FrozenRange(is_integer=is_integer, value=lower)


def _frozen_float(table: dict[str, object], key: str, context: str, *, positive: bool) -> float:
    child = _require_table(_require_key(table, key, context), f"{context}.{key}")
    value = _require_frozen_range(child, f"{context}.{key}").value
    if positive and value <= 0.0:
        raise ValueError(f"{context}.{key} must be positive")
    return value


def _frozen_int(table: dict[str, object], key: str, context: str, *, minimum: int) -> int:
    child = _require_table(_require_key(table, key, context), f"{context}.{key}")
    frozen = _require_frozen_range(child, f"{context}.{key}")
    if not frozen.is_integer:
        raise ValueError(f"{context}.{key} must be an integer range")
    value = int(frozen.value)
    if value < minimum:
        raise ValueError(f"{context}.{key} must be >= {minimum}")
    return value


def _frozen_bool_as_int(table: dict[str, object], key: str, context: str) -> bool:
    value = _frozen_int(table, key, context, minimum=0)
    if value not in {0, 1}:
        raise ValueError(f"{context}.{key} must be 0 or 1")
    return value == 1


def _required_float(table: dict[str, object], key: str, context: str) -> float:
    return _require_numeric(_require_key(table, key, context), f"{context}.{key}")


def _load_fixed_dimensions(root: dict[str, object]) -> FixedDimensions:
    table = _require_table(_require_key(root, "fixed_dimensions", "0.3.8.0 fixed spec"), "fixed_dimensions")
    return FixedDimensions(
        fr4_thickness_mm=_frozen_float(table, "fr4_thickness_mm", "fixed_dimensions", positive=True),
        copper_thickness_mm=_frozen_float(table, "copper_thickness_mm", "fixed_dimensions", positive=True),
        port_length_mm=_frozen_float(table, "port_length_mm", "fixed_dimensions", positive=True),
        port_landing_pad_mm=_frozen_float(table, "port_landing_pad_mm", "fixed_dimensions", positive=True),
        port_landing_drop_mm=_frozen_float(table, "port_landing_drop_mm", "fixed_dimensions", positive=True),
        port_landing_overlap_mm=_frozen_float(table, "port_landing_overlap_mm", "fixed_dimensions", positive=True),
        width_max_mm=_frozen_float(table, "width_max_mm", "fixed_dimensions", positive=True),
        height_max_mm=_frozen_float(table, "height_max_mm", "fixed_dimensions", positive=True),
        tx_rx_min_distance_mm=_frozen_float(table, "tx_rx_min_distance_mm", "fixed_dimensions", positive=True),
        mull_ferrite_thickness_mm=_frozen_float(
            table,
            "mull_ferrite_thickness_mm",
            "fixed_dimensions",
            positive=True,
        ),
    )


def _load_ferrite_parameters(root: dict[str, object]) -> FerriteParameters:
    table = _require_table(_require_key(root, "ferrite", "0.3.8.0 fixed spec"), "ferrite")
    tx_mull_is_enabled = _frozen_bool_as_int(table, "tx_mull_is_enabled", "ferrite")
    tx_mull_position_ratio = _frozen_float(table, "tx_mull_position_ratio", "ferrite", positive=False)
    tx_mull_sheet_count = _frozen_int(table, "tx_mull_sheet_count", "ferrite", minimum=1)
    rx_mull_is_enabled = _frozen_bool_as_int(table, "rx_mull_is_enabled", "ferrite")
    rx_mull_position_ratio = _frozen_float(table, "rx_mull_position_ratio", "ferrite", positive=False)
    if tx_mull_position_ratio < 0.0 or tx_mull_position_ratio > 1.0:
        raise ValueError("ferrite.tx_mull_position_ratio must be between 0 and 1")
    if rx_mull_position_ratio < 0.0 or rx_mull_position_ratio > 1.0:
        raise ValueError("ferrite.rx_mull_position_ratio must be between 0 and 1")
    return FerriteParameters(
        tx_mull_is_enabled=tx_mull_is_enabled,
        tx_mull_position_ratio=tx_mull_position_ratio,
        tx_mull_sheet_count=tx_mull_sheet_count,
        rx_mull_is_enabled=rx_mull_is_enabled,
        rx_mull_position_ratio=rx_mull_position_ratio,
    )


def _load_non_model_objects(root: dict[str, object]) -> tuple[NonModelBox, ...]:
    raw_objects = _require_key(root, "non_model_objects", "0.3.8.0 fixed spec")
    if isinstance(raw_objects, (str, bytes)) or not isinstance(raw_objects, list):
        raise TypeError("non_model_objects must be an array of tables")
    seen_ids: set[str] = set()
    boxes: list[NonModelBox] = []
    for index, raw_object in enumerate(raw_objects):
        context = f"non_model_objects[{index}]"
        table = _require_table(raw_object, context)
        object_id = _require_non_empty_str(table, "id", context)
        if object_id in seen_ids:
            raise ValueError(f"non_model_objects id must be unique (duplicate={object_id!r})")
        seen_ids.add(object_id)
        primitive = _require_non_empty_str(table, "primitive", context)
        if primitive != "box":
            raise ValueError(f"{context}.primitive must be 'box' (actual={primitive!r})")
        transparency = _required_float(table, "transparency", context)
        if transparency < 0.0 or transparency > 1.0:
            raise ValueError(f"{context}.transparency must be between 0 and 1")
        boxes.append(
            NonModelBox(
                object_id=object_id,
                kind=_require_non_empty_str(table, "kind", context),
                material=_require_non_empty_str(table, "material", context),
                origin_xyz=_require_point3(table, "origin_xyz", context, positive=False),
                size_xyz=_require_point3(table, "size_xyz", context, positive=True),
                transparency=transparency,
            )
        )
    return tuple(boxes)


def _modeled_object_by_role(raw_objects: object, role: Role) -> dict[str, object]:
    if isinstance(raw_objects, (str, bytes)) or not isinstance(raw_objects, list):
        raise TypeError("modeled_objects must be an array of tables")
    matches: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for index, raw_object in enumerate(raw_objects):
        table = _require_table(raw_object, f"modeled_objects[{index}]")
        object_id = _require_non_empty_str(table, "object_id", f"modeled_objects[{index}]")
        if object_id in seen_ids:
            raise ValueError(f"modeled_objects object_id must be unique (duplicate={object_id!r})")
        seen_ids.add(object_id)
        object_role = _require_non_empty_str(table, "role", f"modeled_objects[{index}]")
        if object_role == role:
            matches.append(table)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one modeled object with role {role!r} (count={len(matches)})")
    return matches[0]


def _load_coil_parameters(root: dict[str, object], role: Role) -> SswCoilParameters:
    table = _modeled_object_by_role(_require_key(root, "modeled_objects", "0.3.8.0 fixed spec"), role)
    is_under_coil_enabled = True
    if role == "tx_under_coil":
        is_under_coil_enabled = _frozen_bool_as_int(table, "is_under_coil_enabled", role)
        is_ssw_enabled = False
    else:
        is_ssw_enabled = _frozen_bool_as_int(table, "is_ssw_enabled", role)
    no_ssw_qturn_start_int = _frozen_int(table, "no_ssw_qturn_start_int", role, minimum=0)
    no_ssw_qturn_n_int = _frozen_int(table, "no_ssw_qturn_n_int", role, minimum=0)
    if role == "tx_ssw_coil" and not is_ssw_enabled:
        raise ValueError("tx_ssw_coil.is_ssw_enabled must stay enabled in 0.3.8.0")
    if role == "rx_ssw_coil" and not is_ssw_enabled:
        raise ValueError("rx_ssw_coil.is_ssw_enabled must stay enabled in 0.3.8.0")
    if role == "rx_ssw_coil" and no_ssw_qturn_start_int != 0:
        raise ValueError("rx_ssw_coil.no_ssw_qturn_start_int must be fixed to 0 in 0.3.8.0")
    if role == "rx_ssw_coil" and no_ssw_qturn_n_int != 0:
        raise ValueError("rx_ssw_coil.no_ssw_qturn_n_int must be fixed to 0 in 0.3.8.0")
    if role == "tx_under_coil" and no_ssw_qturn_start_int != 1:
        raise ValueError("tx_under_coil.no_ssw_qturn_start_int must be fixed to 1")
    if role == "tx_under_coil" and no_ssw_qturn_n_int != 0:
        raise ValueError("tx_under_coil.no_ssw_qturn_n_int must be fixed to 0")
    if no_ssw_qturn_start_int > 7:
        raise ValueError(f"{role}.no_ssw_qturn_start_int must be <= 7")
    if no_ssw_qturn_n_int > 3:
        raise ValueError(f"{role}.no_ssw_qturn_n_int must be <= 3")
    return SswCoilParameters(
        role=role,
        is_under_coil_enabled=is_under_coil_enabled,
        width_ratio=_frozen_float(table, "width_ratio", role, positive=True),
        height_ratio=_frozen_float(table, "height_ratio", role, positive=True),
        is_ssw_enabled=is_ssw_enabled,
        turn_n_int=_frozen_int(table, "turn_n_int", role, minimum=1),
        gap_ratio=_frozen_float(table, "gap_ratio", role, positive=True),
        void_area_ratio=_frozen_float(table, "void_area_ratio", role, positive=True),
        void_profile=_frozen_int(table, "void_profile", role, minimum=0),
        no_ssw_qturn_start_int=no_ssw_qturn_start_int,
        no_ssw_qturn_n_int=no_ssw_qturn_n_int,
        pcb_gap_mm=1.0 if role == "tx_under_coil" else _frozen_float(table, "pcb_gap_mm", role, positive=True),
        twist_factor=1 if role == "tx_under_coil" else _frozen_int(table, "twist_factor", role, minimum=1),
    )


def _constraint_coils_from_spec(spec: SswFixedSpec) -> tuple[SswConstraintCoil, ...]:
    return (
        SswConstraintCoil(
            object_id=spec.tx.role,
            is_ssw_enabled=spec.tx.is_ssw_enabled,
            turn_n_int=spec.tx.turn_n_int,
            twist_factor=spec.tx.twist_factor,
        ),
        SswConstraintCoil(
            object_id=spec.rx.role,
            is_ssw_enabled=spec.rx.is_ssw_enabled,
            turn_n_int=spec.rx.turn_n_int,
            twist_factor=spec.rx.twist_factor,
        ),
    )


@log_call_duration
def load_ssw_fixed_spec(toml_path: Path) -> SswFixedSpec:
    raw_spec = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    root = _require_table(raw_spec, toml_path.name)
    spec_version = _require_non_empty_str(root, "spec_version", toml_path.name)
    if spec_version != SPEC_VERSION:
        raise ValueError(f"spec_version must be {SPEC_VERSION!r} (actual={spec_version!r})")
    schema_id = _require_non_empty_str(root, "schema_id", toml_path.name)
    if schema_id != SCHEMA_ID:
        raise ValueError(f"schema_id must be {SCHEMA_ID!r} (actual={schema_id!r})")
    design = _require_table(_require_key(root, "design", toml_path.name), "design")
    units = _require_non_empty_str(design, "units", "design")
    if units != SUPPORTED_UNITS:
        raise ValueError(f"design.units must be {SUPPORTED_UNITS!r} (actual={units!r})")
    spec = SswFixedSpec(
        source_toml_path=str(toml_path),
        units="mm",
        fixed=_load_fixed_dimensions(root),
        ferrite=_load_ferrite_parameters(root),
        non_model_objects=_load_non_model_objects(root),
        constraints=parse_ssw_constraint_rules(root, context=toml_path.name),
        tx=_load_coil_parameters(root, "tx_ssw_coil"),
        tx_under=_load_coil_parameters(root, "tx_under_coil"),
        rx=_load_coil_parameters(root, "rx_ssw_coil"),
    )
    require_ssw_constraints_satisfied(rules=spec.constraints, coils=_constraint_coils_from_spec(spec))
    return spec


def _box(
    name: str,
    role: BodyRole,
    material: str,
    center_xyz: Point3,
    size_xyz: Point3,
    *,
    transparency: float,
) -> _BodyBox:
    if size_xyz[0] <= 0.0 or size_xyz[1] <= 0.0 or size_xyz[2] <= 0.0:
        raise ValueError(f"{name} dimensions must be positive (size_xyz={size_xyz!r})")
    if transparency < 0.0 or transparency > 1.0:
        raise ValueError(f"{name} transparency must be between 0 and 1")
    return _BodyBox(
        name=name,
        role=role,
        material=material,
        center_xyz=center_xyz,
        size_xyz=size_xyz,
        transparency=transparency,
    )


def _void_scale(params: SswCoilParameters) -> float:
    if params.void_area_ratio <= 0.0 or params.void_area_ratio >= 1.0:
        raise ValueError(f"{params.role}.void_area_ratio must be between 0 and 1")
    if params.void_profile == 0:
        return math.sqrt(params.void_area_ratio)
    if params.void_profile == 1:
        return math.sqrt(params.void_area_ratio)
    raise ValueError(f"{params.role}.void_profile must be 0 or 1")


def _connector_center(
    *,
    coil_center_xy: tuple[float, float],
    side: int,
    outer_width_mm: float,
    outer_height_mm: float,
    trace_width_mm: float,
) -> tuple[float, float]:
    center_x, center_y = coil_center_xy
    if side == 0:
        return (center_x + outer_width_mm / 2.0 - trace_width_mm / 2.0, center_y)
    if side == 1:
        return (center_x, center_y + outer_height_mm / 2.0 - trace_width_mm / 2.0)
    if side == 2:
        return (center_x - outer_width_mm / 2.0 + trace_width_mm / 2.0, center_y)
    if side == 3:
        return (center_x, center_y - outer_height_mm / 2.0 + trace_width_mm / 2.0)
    raise ValueError(f"connector side must be 0..3 (actual={side})")


def _loop_strip_boxes(
    *,
    prefix: str,
    center_xy: tuple[float, float],
    z_center_mm: float,
    outer_width_mm: float,
    outer_height_mm: float,
    trace_width_mm: float,
    copper_thickness_mm: float,
) -> tuple[_BodyBox, _BodyBox, _BodyBox, _BodyBox]:
    center_x, center_y = center_xy
    return (
        _box(
            f"{prefix}_top",
            "copper",
            "copper",
            (center_x, center_y + outer_height_mm / 2.0 - trace_width_mm / 2.0, z_center_mm),
            (outer_width_mm, trace_width_mm, copper_thickness_mm),
            transparency=0.0,
        ),
        _box(
            f"{prefix}_bottom",
            "copper",
            "copper",
            (center_x, center_y - outer_height_mm / 2.0 + trace_width_mm / 2.0, z_center_mm),
            (outer_width_mm, trace_width_mm, copper_thickness_mm),
            transparency=0.0,
        ),
        _box(
            f"{prefix}_left",
            "copper",
            "copper",
            (center_x - outer_width_mm / 2.0 + trace_width_mm / 2.0, center_y, z_center_mm),
            (trace_width_mm, outer_height_mm, copper_thickness_mm),
            transparency=0.0,
        ),
        _box(
            f"{prefix}_right",
            "copper",
            "copper",
            (center_x + outer_width_mm / 2.0 - trace_width_mm / 2.0, center_y, z_center_mm),
            (trace_width_mm, outer_height_mm, copper_thickness_mm),
            transparency=0.0,
        ),
    )


def _coil_boxes(
    *,
    params: SswCoilParameters,
    fixed: FixedDimensions,
    center_xy: tuple[float, float],
) -> tuple[_BodyBox, ...]:
    width_mm = params.width_mm(fixed)
    height_mm = params.height_mm(fixed)
    if width_mm <= 0.0 or height_mm <= 0.0:
        raise ValueError(f"{params.role} resolved dimensions must be positive")
    void_scale = _void_scale(params)
    inner_width_mm = width_mm * void_scale
    inner_height_mm = height_mm * void_scale
    radial_width_mm = min(width_mm - inner_width_mm, height_mm - inner_height_mm) / 2.0
    if radial_width_mm <= 0.0:
        raise ValueError(f"{params.role} radial trace region must be positive")
    pitch_mm = radial_width_mm / params.turn_n_int
    trace_width_mm = pitch_mm * (1.0 - params.gap_ratio)
    if trace_width_mm <= 0.0:
        raise ValueError(f"{params.role} trace width must be positive")

    copper = fixed.copper_thickness_mm
    fr4 = fixed.fr4_thickness_mm
    lower_copper_z = copper / 2.0
    lower_fr4_z = copper + fr4 / 2.0
    upper_fr4_z = copper + fr4 + params.pcb_gap_mm + fr4 / 2.0
    upper_copper_z = copper + fr4 + params.pcb_gap_mm + fr4 + copper / 2.0
    connector_z_center = (lower_copper_z + upper_copper_z) / 2.0
    connector_z_size = upper_copper_z - lower_copper_z + copper

    boxes: list[_BodyBox] = [
        _box(
            f"{params.role}_lower_fr4",
            "fr4",
            "fr4",
            (center_xy[0], center_xy[1], lower_fr4_z),
            (width_mm, height_mm, fr4),
            transparency=0.65,
        ),
        _box(
            f"{params.role}_upper_fr4",
            "fr4",
            "fr4",
            (center_xy[0], center_xy[1], upper_fr4_z),
            (width_mm, height_mm, fr4),
            transparency=0.65,
        ),
    ]
    for index in range(params.turn_n_int):
        outer_width = width_mm - 2.0 * pitch_mm * index
        outer_height = height_mm - 2.0 * pitch_mm * index
        if outer_width <= trace_width_mm * 2.0 or outer_height <= trace_width_mm * 2.0:
            raise ValueError(f"{params.role} turn {index} dimensions collapsed")
        boxes.extend(
            _loop_strip_boxes(
                prefix=f"{params.role}_lower_turn_{index}",
                center_xy=center_xy,
                z_center_mm=lower_copper_z,
                outer_width_mm=outer_width,
                outer_height_mm=outer_height,
                trace_width_mm=trace_width_mm,
                copper_thickness_mm=copper,
            )
        )
        boxes.extend(
            _loop_strip_boxes(
                prefix=f"{params.role}_upper_turn_{index}",
                center_xy=center_xy,
                z_center_mm=upper_copper_z,
                outer_width_mm=outer_width,
                outer_height_mm=outer_height,
                trace_width_mm=trace_width_mm,
                copper_thickness_mm=copper,
            )
        )
        connector_side = (index * params.twist_factor) % 4
        connector_x, connector_y = _connector_center(
            coil_center_xy=center_xy,
            side=connector_side,
            outer_width_mm=outer_width,
            outer_height_mm=outer_height,
            trace_width_mm=trace_width_mm,
        )
        boxes.append(
            _box(
                f"{params.role}_ssw_connector_{index}",
                "copper",
                "copper",
                (connector_x, connector_y, connector_z_center),
                (trace_width_mm, trace_width_mm, connector_z_size),
                transparency=0.0,
            )
        )
    return tuple(boxes)


def _non_model_boxes(spec: SswFixedSpec) -> tuple[_BodyBox, ...]:
    resolved_non_model_objects = tuple(
        _resolved_non_model_box(spec, non_model)
        for non_model in spec.non_model_objects
    )
    return tuple(
        _box(
            resolved.object_id,
            "non_model",
            resolved.material,
            (
                resolved.origin_xyz[0] + resolved.size_xyz[0] / 2.0,
                resolved.origin_xyz[1] + resolved.size_xyz[1] / 2.0,
                resolved.origin_xyz[2] + resolved.size_xyz[2] / 2.0,
            ),
            resolved.size_xyz,
            transparency=resolved.transparency,
        )
        for resolved in resolved_non_model_objects
    )


def _mull_sheet_axis_bounds(
    *,
    outer_min_mm: float,
    coil_min_mm: float,
    thickness_mm: float,
    ratio: float,
    context: str,
) -> tuple[float, float]:
    available_mm = coil_min_mm - outer_min_mm
    travel_mm = available_mm - thickness_mm
    tolerance = 1e-9
    if travel_mm < -tolerance:
        raise ValueError(
            f"{context} MULL ferrite remaining interval must be >= sheet thickness "
            f"(remaining={available_mm}, thickness={thickness_mm})"
        )
    if travel_mm < 0.0:
        travel_mm = 0.0
    sheet_min_mm = outer_min_mm + travel_mm * ratio
    return sheet_min_mm, sheet_min_mm + thickness_mm


def _mull_ferrite_sheet_boxes(
    *,
    spec: SswFixedSpec,
    tx_boxes: tuple[_BodyBox, ...],
    rx_boxes: tuple[_BodyBox, ...],
) -> tuple[_BodyBox, ...]:
    tx_region_max_bounds = _body_bounds(_body_by_name(_non_model_boxes(spec), "tx_region_max"))
    rx_region_max_bounds = _body_bounds(_body_by_name(_non_model_boxes(spec), "rx_region_max"))
    tx_bounds = _combined_bounds(tx_boxes, "TX SSW bodies")
    rx_bounds = _combined_bounds(rx_boxes, "RX SSW bodies")
    thickness = spec.fixed.mull_ferrite_thickness_mm

    ferrite_boxes: list[_BodyBox] = []
    if spec.tx_under.is_under_coil_enabled and spec.ferrite.tx_mull_is_enabled:
        raise ValueError("ferrite.tx_mull_is_enabled must be 0 when tx_under_coil is enabled")
    if spec.ferrite.tx_mull_is_enabled:
        count = spec.ferrite.tx_mull_sheet_count
        # Stack `count` sheets downward (toward tx_region_max bottom), each separated
        # from the next by a gap equal to one sheet thickness. The whole stack spans
        # (2 * count - 1) * thickness and is positioned by tx_mull_position_ratio.
        stack_height = (2 * count - 1) * thickness
        _stack_zmin, stack_zmax = _mull_sheet_axis_bounds(
            outer_min_mm=tx_region_max_bounds.zmin,
            coil_min_mm=tx_bounds.zmin,
            thickness_mm=stack_height,
            ratio=spec.ferrite.tx_mull_position_ratio,
            context="TX",
        )
        for sheet_index in range(count):
            sheet_zmax = stack_zmax - sheet_index * 2.0 * thickness
            sheet_zmin = sheet_zmax - thickness
            sheet_name = "tx_mull_ferrite_sheet" if sheet_index == 0 else f"tx_mull_ferrite_sheet_{sheet_index}"
            ferrite_boxes.append(
                _box(
                    sheet_name,
                    "ferrite",
                    MULL_FERRITE_MATERIAL,
                    (tx_bounds.center_x, tx_bounds.center_y, (sheet_zmin + sheet_zmax) / 2.0),
                    (tx_bounds.size_x, tx_bounds.size_y, thickness),
                    transparency=MULL_FERRITE_TRANSPARENCY,
                )
            )
    if spec.ferrite.rx_mull_is_enabled:
        rx_xmin, rx_xmax = _mull_sheet_axis_bounds(
            outer_min_mm=rx_region_max_bounds.xmin,
            coil_min_mm=rx_bounds.xmin,
            thickness_mm=thickness,
            ratio=spec.ferrite.rx_mull_position_ratio,
            context="RX",
        )
        ferrite_boxes.append(
            _box(
                "rx_mull_ferrite_sheet",
                "ferrite",
                MULL_FERRITE_MATERIAL,
                ((rx_xmin + rx_xmax) / 2.0, rx_bounds.center_y, rx_bounds.center_z),
                (thickness, rx_bounds.size_y, rx_bounds.size_z),
                transparency=MULL_FERRITE_TRANSPARENCY,
            ),
        )
    return tuple(ferrite_boxes)


def _resolved_non_model_box(spec: SswFixedSpec, non_model: NonModelBox) -> NonModelBox:
    if non_model.object_id == "tx_region":
        return _resolved_tx_region_box(spec, non_model)
    if non_model.object_id == "tx_region_max":
        return _resolved_tx_region_max_box(spec, non_model)
    if non_model.object_id == "rx_region_max":
        return _resolved_rx_region_max_box(spec, non_model)
    return non_model


def _tv_box(spec: SswFixedSpec) -> NonModelBox:
    matches = tuple(box for box in spec.non_model_objects if box.object_id == "tv")
    if len(matches) != 1:
        raise ValueError(f"expected exactly one non-model tv box (count={len(matches)})")
    return matches[0]


def _resolved_tx_region_box(spec: SswFixedSpec, tx_region: NonModelBox) -> NonModelBox:
    tv = _tv_box(spec)
    tx_region_zmax = tv.origin_xyz[2] - spec.fixed.tx_rx_min_distance_mm
    tx_region_size_z = tx_region_zmax - tx_region.origin_xyz[2]
    if tx_region_size_z <= 0.0:
        raise ValueError(
            f"tx_region derived Z size must be positive "
            f"(origin_z={tx_region.origin_xyz[2]}, zmax={tx_region_zmax})"
        )
    return NonModelBox(
        object_id=tx_region.object_id,
        kind=tx_region.kind,
        material=tx_region.material,
        origin_xyz=tx_region.origin_xyz,
        size_xyz=(tx_region.size_xyz[0], tx_region.size_xyz[1], tx_region_size_z),
        transparency=tx_region.transparency,
    )


def _resolved_tx_region_max_box(spec: SswFixedSpec, tx_region_max: NonModelBox) -> NonModelBox:
    tv = _tv_box(spec)
    tx_region = _tx_region_box(spec)
    if tx_region_max.size_xyz[0] > tx_region.size_xyz[0]:
        raise ValueError(
            f"tx_region_max X size must fit inside tx_region "
            f"(max_x={tx_region_max.size_xyz[0]}, tx_region_x={tx_region.size_xyz[0]})"
        )
    if tx_region_max.size_xyz[1] > tx_region.size_xyz[1]:
        raise ValueError(
            f"tx_region_max Y size must fit inside tx_region "
            f"(max_y={tx_region_max.size_xyz[1]}, tx_region_y={tx_region.size_xyz[1]})"
        )
    if tx_region_max.size_xyz[2] > tx_region.size_xyz[2]:
        raise ValueError(
            f"tx_region_max Z size must fit inside tx_region "
            f"(max_z={tx_region_max.size_xyz[2]}, tx_region_z={tx_region.size_xyz[2]})"
        )
    tv_center_y = tv.origin_xyz[1] + tv.size_xyz[1] / 2.0
    tx_region_zmax = tx_region.origin_xyz[2] + tx_region.size_xyz[2]
    return NonModelBox(
        object_id=tx_region_max.object_id,
        kind=tx_region_max.kind,
        material=tx_region_max.material,
        origin_xyz=(
            tx_region.origin_xyz[0],
            tv_center_y - tx_region_max.size_xyz[1] / 2.0,
            tx_region_zmax - tx_region_max.size_xyz[2],
        ),
        size_xyz=tx_region_max.size_xyz,
        transparency=tx_region_max.transparency,
    )


def _resolved_rx_region_max_box(spec: SswFixedSpec, rx_region_max: NonModelBox) -> NonModelBox:
    tv = _tv_box(spec)
    if rx_region_max.size_xyz[0] > tv.size_xyz[0]:
        raise ValueError(
            f"rx_region_max X thickness must fit inside TV X thickness "
            f"(rx_region_max_x={rx_region_max.size_xyz[0]}, tv_x={tv.size_xyz[0]})"
        )
    return NonModelBox(
        object_id=rx_region_max.object_id,
        kind=rx_region_max.kind,
        material=rx_region_max.material,
        origin_xyz=(
            tv.origin_xyz[0] + tv.size_xyz[0] - rx_region_max.size_xyz[0],
            rx_region_max.origin_xyz[1],
            tv.origin_xyz[2],
        ),
        size_xyz=rx_region_max.size_xyz,
        transparency=rx_region_max.transparency,
    )


def _tx_region_box(spec: SswFixedSpec) -> NonModelBox:
    matches = tuple(box for box in spec.non_model_objects if box.object_id == "tx_region")
    if len(matches) != 1:
        raise ValueError(f"expected exactly one non-model tx_region box (count={len(matches)})")
    return _resolved_tx_region_box(spec, matches[0])


def _rx_region_max_box(spec: SswFixedSpec) -> NonModelBox:
    matches = tuple(box for box in spec.non_model_objects if box.object_id == "rx_region_max")
    if len(matches) != 1:
        raise ValueError(f"expected exactly one non-model rx_region_max box (count={len(matches)})")
    return _resolved_rx_region_max_box(spec, matches[0])


def _tx_region_max_box(spec: SswFixedSpec) -> NonModelBox:
    matches = tuple(box for box in spec.non_model_objects if box.object_id == "tx_region_max")
    if len(matches) != 1:
        raise ValueError(f"expected exactly one non-model tx_region_max box (count={len(matches)})")
    return _resolved_tx_region_max_box(spec, matches[0])


def _coilmaker_config(params: SswCoilParameters, fixed: FixedDimensions) -> coilmaker.RuntimeConfig:
    return coilmaker.RuntimeConfig(
        fixed=coilmaker.FixedDimensions(
            FR4_THICKNESS_MM=fixed.fr4_thickness_mm,
            COPPER_THICKNESS_MM=fixed.copper_thickness_mm,
            PORT_LENGTH_MM=fixed.port_length_mm,
            PORT_LANDING_PAD_MM=fixed.port_landing_pad_mm,
            PORT_LANDING_DROP_MM=fixed.port_landing_drop_mm,
            PORT_LANDING_OVERLAP_MM=fixed.port_landing_overlap_mm,
            WIDTH_MAX_MM=fixed.width_max_mm,
            HEIGHT_MAX_MM=fixed.height_max_mm,
        ),
        common=coilmaker.CommonCoilParameters(
            WIDTH_RATIO=params.width_ratio,
            HEIGHT_RATIO=params.height_ratio,
            IS_SSW_ENABLED=params.is_ssw_enabled,
            TURN_N_INT=params.turn_n_int,
            GAP_RATIO=params.gap_ratio,
            VOID_AREA_RATIO=params.void_area_ratio,
            VOID_PROFILE=params.void_profile,
            SERIAL_COIL_N=1,
            SERIAL_COIL_GAP_RATIO=0.0,
            SERIAL_COIL_AXIS=0,
        ),
        spiral=coilmaker.SpiralCoilParameters(
            NO_SSW_QTURN_START_INT=params.no_ssw_qturn_start_int,
            NO_SSW_QTURN_N_INT=params.no_ssw_qturn_n_int,
        ),
        ssw=coilmaker.SSWCoilParameters(
            PCB_GAP_MM=params.pcb_gap_mm,
            TWIST_FACTOR=params.twist_factor,
        ),
    )


def normal_spiral_trace_width_mm(*, params: SswCoilParameters, fixed: FixedDimensions) -> float:
    if params.is_ssw_enabled:
        raise ValueError(f"{params.role} normal/spiral trace width requires is_ssw_enabled=false")
    config = _coilmaker_config(params, fixed)
    frames = tuple(coilmaker.coil_slot_frames(config))
    if len(frames) != 1:
        raise ValueError(
            "0.3.8.0 normal/spiral trace width expects exactly one coil frame "
            f"(role={params.role}, count={len(frames)})"
        )
    return coilmaker._normal_coil_trace_width_mm(config, frames[0])


def ssw_trace_width_mm(*, params: SswCoilParameters, fixed: FixedDimensions) -> float:
    """SSW conductor trace width (mm) from the real coilmaker build path.

    == coilmaker._ssw_trace_context(config, frame).trace_width_mm
    """
    if not params.is_ssw_enabled:
        raise ValueError(f"{params.role} SSW trace width requires is_ssw_enabled=true")
    config = _coilmaker_config(params, fixed)
    frames = tuple(coilmaker.coil_slot_frames(config))
    if len(frames) != 1:
        raise ValueError(
            f"SSW trace width expects exactly one coil frame (role={params.role}, count={len(frames)})"
        )
    return coilmaker._ssw_trace_context(config, frames[0]).trace_width_mm


def _identity_location() -> cq.Location:
    return cq.Location(cq.Vector(0.0, 0.0, 0.0))


def _tx_xy_bottom_port_orientation() -> cq.Location:
    rotate_z = cq.Location(cq.Vector(0.0, 0.0, 0.0), cq.Vector(0.0, 0.0, 1.0), 90.0)
    flip_top_port_to_bottom = cq.Location(cq.Vector(0.0, 0.0, 0.0), cq.Vector(0.0, 1.0, 0.0), 180.0)
    return flip_top_port_to_bottom * rotate_z


def _rx_yz_back_port_orientation() -> cq.Location:
    rotate_y = cq.Location(cq.Vector(0.0, 0.0, 0.0), cq.Vector(0.0, 1.0, 0.0), 90.0)
    rotate_x = cq.Location(cq.Vector(0.0, 0.0, 0.0), cq.Vector(1.0, 0.0, 0.0), 90.0)
    return rotate_x * rotate_y


@log_call_duration
def _coilmaker_assembly(params: SswCoilParameters, fixed: FixedDimensions) -> cq.Assembly:
    return coilmaker.build_assembly(_coilmaker_config(params, fixed))


def _ssw_port_anchor_world_xyz_from_placement(
    *,
    spec: SswFixedSpec,
    params: SswCoilParameters,
    placement: cq.Location,
) -> Point3:
    if not params.is_ssw_enabled:
        raise ValueError(f"{params.role} does not have an SSW port anchor when is_ssw_enabled=false")
    config = _coilmaker_config(params, spec.fixed)
    frames = tuple(coilmaker.coil_slot_frames(config))
    if len(frames) != 1:
        raise ValueError(f"0.3.8.0 SSW scene expects exactly one coil frame per role (role={params.role}, count={len(frames)})")
    frame = frames[0]
    context = coilmaker._ssw_trace_context(config, frame)
    matching_sides = tuple(side for side in coilmaker.loop_side_specs(config, frame) if side.name == context.port_gap.side_name)
    if len(matching_sides) != 1:
        raise ValueError(f"SSW port gap side must resolve once (role={params.role}, side={context.port_gap.side_name})")
    matching_faces = tuple(face for face in coilmaker.ssw_active_faces(config, frame) if face.name == context.port_gap.face_name)
    if len(matching_faces) != 1:
        raise ValueError(f"SSW port gap face must resolve once (role={params.role}, face={context.port_gap.face_name})")
    side = matching_sides[0]
    face = matching_faces[0]
    board_trace_width_mm = coilmaker._board_trace_width_mm(config, frame)
    u_mid_mm = (context.port_gap.u_start_mm + context.port_gap.u_end_mm) / 2.0
    face_mid_mm = (face.start_mm + face.end_mm) / 2.0
    radial_mm = board_trace_width_mm / 2.0 - (face_mid_mm - face.start_mm)
    local_x_mm, local_y_mm = coilmaker._surface_point_on_side(config, frame, side, u_mid_mm, radial_mm)
    _, local_z_mm = coilmaker._top_copper_z_bounds(config)
    probe_half_mm = 0.003
    bbox = _located_bbox(
        cq.Workplane("XY").box(probe_half_mm * 2.0, probe_half_mm * 2.0, probe_half_mm * 2.0).translate(
            (local_x_mm, local_y_mm, local_z_mm)
        ),
        placement,
    )
    return (
        (bbox.xmin + bbox.xmax) / 2.0,
        (bbox.ymin + bbox.ymax) / 2.0,
        (bbox.zmin + bbox.zmax) / 2.0,
    )


def _ssw_port_anchor_world_xyz(
    *,
    spec: SswFixedSpec,
    params: SswCoilParameters,
) -> Point3:
    assembly = _coilmaker_assembly(params, spec.fixed)
    placement = _placement_for_role(spec, params, assembly)
    return _ssw_port_anchor_world_xyz_from_placement(spec=spec, params=params, placement=placement)


def _body_bounds(body: _BodyBox) -> _Bounds:
    half_x = body.size_xyz[0] / 2.0
    half_y = body.size_xyz[1] / 2.0
    half_z = body.size_xyz[2] / 2.0
    return _Bounds(
        xmin=body.center_xyz[0] - half_x,
        xmax=body.center_xyz[0] + half_x,
        ymin=body.center_xyz[1] - half_y,
        ymax=body.center_xyz[1] + half_y,
        zmin=body.center_xyz[2] - half_z,
        zmax=body.center_xyz[2] + half_z,
    )


def _combined_bounds(bodies: tuple[_BodyBox, ...], context: str) -> _Bounds:
    if len(bodies) == 0:
        raise ValueError(f"{context} must contain at least one body")
    bounds = tuple(_body_bounds(body) for body in bodies)
    return _Bounds(
        xmin=min(bound.xmin for bound in bounds),
        xmax=max(bound.xmax for bound in bounds),
        ymin=min(bound.ymin for bound in bounds),
        ymax=max(bound.ymax for bound in bounds),
        zmin=min(bound.zmin for bound in bounds),
        zmax=max(bound.zmax for bound in bounds),
    )


def _bodies_with_role(bodies: tuple[_BodyBox, ...], role: BodyRole, context: str) -> tuple[_BodyBox, ...]:
    matches = tuple(body for body in bodies if body.role == role)
    if len(matches) == 0:
        raise ValueError(f"{context} must contain at least one {role} body")
    return matches


def _coilmaker_child_bodies_from_assembly(
    *,
    params: SswCoilParameters,
    assembly: cq.Assembly,
    placement: cq.Location,
) -> tuple[_BodyBox, ...]:
    bodies: list[_BodyBox] = []
    for child in assembly.children:
        child_name = _child_name(child)
        name = f"{params.role}_{child_name}"
        role = _coilmaker_child_role(child_name)
        material = _coilmaker_child_material(child_name)
        loc = placement * _child_location(child)
        bodies.append(
            _body_from_bbox(
                name,
                role,
                material,
                _located_bbox(_child_workplane(child), loc),
                transparency=_transparency_for_coilmaker_child(child_name),
            )
        )
    return tuple(bodies)


def _placement_for_role(spec: SswFixedSpec, params: SswCoilParameters, assembly: cq.Assembly) -> cq.Location:
    tv = _tv_box(spec)
    tv_center_y = tv.origin_xyz[1] + tv.size_xyz[1] / 2.0
    if params.role == "tx_under_coil":
        tx_region_max = _tx_region_max_box(spec)
        orientation = _rx_yz_back_port_orientation()
        oriented_bodies = _coilmaker_child_bodies_from_assembly(params=params, assembly=assembly, placement=orientation)
        oriented_bounds = _combined_bounds(oriented_bodies, f"{params.role} oriented bodies")
        if oriented_bounds.size_x > tx_region_max.size_xyz[0]:
            raise ValueError(
                f"TX under-coil X span does not fit inside tx_region_max "
                f"(span={oriented_bounds.size_x}, tx_region_max_x_size={tx_region_max.size_xyz[0]})"
            )
        if oriented_bounds.size_y > tx_region_max.size_xyz[1]:
            raise ValueError(
                f"TX under-coil Y span does not fit inside tx_region_max "
                f"(span={oriented_bounds.size_y}, tx_region_max_y_size={tx_region_max.size_xyz[1]})"
            )
        if oriented_bounds.size_z > tx_region_max.size_xyz[2]:
            raise ValueError(
                f"TX under-coil Z span does not fit inside tx_region_max "
                f"(span={oriented_bounds.size_z}, tx_region_max_z_size={tx_region_max.size_xyz[2]})"
            )
        translate_x = tx_region_max.origin_xyz[0] - oriented_bounds.xmax
        translate_y = tv_center_y - oriented_bounds.center_y
        translate_z = tx_region_max.origin_xyz[2] - oriented_bounds.zmin
        return cq.Location(cq.Vector(translate_x, translate_y, translate_z)) * orientation

    if params.role == "rx_ssw_coil":
        rx_region_max = _rx_region_max_box(spec)
        rx_region_center_y = rx_region_max.origin_xyz[1] + rx_region_max.size_xyz[1] / 2.0
        orientation = _rx_yz_back_port_orientation()
        oriented_bodies = _coilmaker_child_bodies_from_assembly(params=params, assembly=assembly, placement=orientation)
        oriented_bounds = _combined_bounds(oriented_bodies, f"{params.role} oriented bodies")
        if oriented_bounds.size_x > rx_region_max.size_xyz[0]:
            raise ValueError(
                f"RX SSW stack does not fit inside rx_region_max X thickness "
                f"(stack={oriented_bounds.size_x}, rx_region_max_x_size={rx_region_max.size_xyz[0]})"
            )
        if oriented_bounds.size_y > rx_region_max.size_xyz[1]:
            raise ValueError(
                f"RX SSW Y span does not fit inside rx_region_max "
                f"(span={oriented_bounds.size_y}, rx_region_max_y_size={rx_region_max.size_xyz[1]})"
            )
        if oriented_bounds.size_z > rx_region_max.size_xyz[2]:
            raise ValueError(
                f"RX SSW Z span does not fit inside rx_region_max "
                f"(span={oriented_bounds.size_z}, rx_region_max_z_size={rx_region_max.size_xyz[2]})"
        )
        translate_x = rx_region_max.origin_xyz[0] + rx_region_max.size_xyz[0] - oriented_bounds.xmax
        translate_y = rx_region_center_y - oriented_bounds.center_y
        translate_z = rx_region_max.origin_xyz[2] - oriented_bounds.zmin
        return cq.Location(cq.Vector(translate_x, translate_y, translate_z)) * orientation

    tx_region = _tx_region_box(spec)
    orientation = _tx_xy_bottom_port_orientation()
    oriented_bodies = _coilmaker_child_bodies_from_assembly(params=params, assembly=assembly, placement=orientation)
    oriented_bounds = _combined_bounds(oriented_bodies, f"{params.role} oriented bodies")
    tx_region_zmax = tx_region.origin_xyz[2] + tx_region.size_xyz[2]
    translate_x = tx_region.origin_xyz[0] - oriented_bounds.xmin
    translate_y = tv_center_y - oriented_bounds.center_y
    translate_z = tx_region_zmax - oriented_bounds.zmax
    return cq.Location(cq.Vector(translate_x, translate_y, translate_z)) * orientation


def _child_name(child: object) -> str:
    assert hasattr(child, "name")
    name = cast(_ChildNameCarrier, child).name
    assert isinstance(name, str)
    return name


def _child_workplane(child: object) -> cq.Workplane:
    assert hasattr(child, "obj")
    obj = cast(_ChildObjectCarrier, child).obj
    assert isinstance(obj, cq.Workplane)
    return obj


def _child_location(child: object) -> cq.Location:
    assert hasattr(child, "loc")
    loc = cast(_ChildLocationCarrier, child).loc
    assert isinstance(loc, cq.Location)
    return loc


def _coilmaker_child_role(name: str) -> BodyRole:
    if name.endswith("_fr4"):
        return "fr4"
    return "copper"


def _coilmaker_child_material(name: str) -> str:
    if name.endswith("_fr4"):
        return "fr4"
    return "copper"


def _transparency_for_coilmaker_child(name: str) -> float:
    if name.endswith("_fr4"):
        return 0.65
    return 0.0


def _color_for_body(body: _BodyBox) -> cq.Color:
    alpha = 1.0 - body.transparency
    if body.material == "copper":
        return cq.Color(0.8, 0.45, 0.15, alpha)
    if body.material == "fr4":
        return cq.Color(0.1, 0.45, 0.1, alpha)
    if body.role == "ferrite" and body.material == MULL_FERRITE_MATERIAL:
        return cq.Color(0.12, 0.12, 0.12, alpha)
    if body.name == "tv":
        return cq.Color(0.6, 0.8, 1.0, alpha)
    if body.name == "tx_region":
        return cq.Color(0.5, 0.5, 0.5, alpha)
    if body.role == "non_model" and body.material == "vacuum":
        return cq.Color(0.35, 0.55, 0.75, alpha)
    raise ValueError(f"unsupported material/body color assignment for {body.name!r} ({body.material!r})")


def _located_bbox(obj: cq.Workplane, loc: cq.Location) -> cq.BoundBox:
    raw_shape = obj.val()
    assert isinstance(raw_shape, cq.Shape)
    shape = raw_shape
    return shape.located(loc).BoundingBox()


def _body_from_bbox(
    name: str,
    role: BodyRole,
    material: str,
    bbox: cq.BoundBox,
    *,
    transparency: float,
) -> _BodyBox:
    return _BodyBox(
        name=name,
        role=role,
        material=material,
        center_xyz=(
            (bbox.xmin + bbox.xmax) / 2.0,
            (bbox.ymin + bbox.ymax) / 2.0,
            (bbox.zmin + bbox.zmax) / 2.0,
        ),
        size_xyz=(
            bbox.xmax - bbox.xmin,
            bbox.ymax - bbox.ymin,
            bbox.zmax - bbox.zmin,
        ),
        transparency=transparency,
    )


def _coilmaker_child_bodies(
    *,
    spec: SswFixedSpec,
    params: SswCoilParameters,
) -> tuple[_BodyBox, ...]:
    assembly = _coilmaker_assembly(params, spec.fixed)
    placement = _placement_for_role(spec, params, assembly)
    return _coilmaker_child_bodies_from_assembly(params=params, assembly=assembly, placement=placement)


def _coil_scene_part(*, spec: SswFixedSpec, params: SswCoilParameters) -> _CoilScenePart:
    assembly = _coilmaker_assembly(params, spec.fixed)
    placement = _placement_for_role(spec, params, assembly)
    bodies = _coilmaker_child_bodies_from_assembly(params=params, assembly=assembly, placement=placement)
    return _CoilScenePart(params=params, assembly=assembly, placement=placement, bodies=bodies)


def _coil_scene_parts(spec: SswFixedSpec) -> tuple[_CoilScenePart, ...]:
    role_params: tuple[SswCoilParameters, ...] = (
        (spec.tx, spec.tx_under, spec.rx) if spec.tx_under.is_under_coil_enabled else (spec.tx, spec.rx)
    )
    return tuple(_coil_scene_part(spec=spec, params=params) for params in role_params)


def _scene_part_by_role(*, parts: tuple[_CoilScenePart, ...], role: Role) -> _CoilScenePart:
    matches = tuple(part for part in parts if part.params.role == role)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one SSW scene part for {role!r} (count={len(matches)})")
    return matches[0]


def _bodies_with_prefix(bodies: tuple[_BodyBox, ...], prefix: str) -> tuple[_BodyBox, ...]:
    matches = tuple(body for body in bodies if body.name.startswith(prefix))
    if len(matches) == 0:
        raise ValueError(f"expected at least one body with prefix {prefix!r}")
    return matches


def _body_by_name(bodies: tuple[_BodyBox, ...], name: str) -> _BodyBox:
    matches = tuple(body for body in bodies if body.name == name)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one body named {name!r} (count={len(matches)})")
    return matches[0]


def _assert_inside_bounds(*, inner: _Bounds, outer: _Bounds, context: str) -> None:
    _assert_inside_bounds_with_tolerance(inner=inner, outer=outer, context=context, tolerance=1e-6)


def _assert_inside_bounds_with_tolerance(*, inner: _Bounds, outer: _Bounds, context: str, tolerance: float) -> None:
    if inner.xmin < outer.xmin - tolerance or inner.xmax > outer.xmax + tolerance:
        raise ValueError(f"{context} X bounds must be inside TV")
    if inner.ymin < outer.ymin - tolerance or inner.ymax > outer.ymax + tolerance:
        raise ValueError(f"{context} Y bounds must be inside TV")
    if inner.zmin < outer.zmin - tolerance or inner.zmax > outer.zmax + tolerance:
        raise ValueError(f"{context} Z bounds must be inside TV")


def _validate_scene_contract(
    *,
    spec: SswFixedSpec,
    bodies: tuple[_BodyBox, ...],
    parts: tuple[_CoilScenePart, ...],
) -> None:
    tolerance = 1e-6
    tv_bounds = _body_bounds(_body_by_name(bodies, "tv"))
    tx_region_bounds = _body_bounds(_body_by_name(bodies, "tx_region"))
    tx_region_max_bounds = _body_bounds(_body_by_name(bodies, "tx_region_max"))
    rx_region_max_bounds = _body_bounds(_body_by_name(bodies, "rx_region_max"))
    tx_bounds = _combined_bounds(_bodies_with_prefix(bodies, "tx_ssw_coil_"), "TX SSW bodies")
    rx_bounds = _combined_bounds(_bodies_with_prefix(bodies, "rx_ssw_coil_"), "RX SSW bodies")
    tx_ferrite_bodies = tuple(body for body in bodies if body.name.startswith("tx_mull_ferrite_sheet"))
    rx_ferrite_bodies = tuple(body for body in bodies if body.name == "rx_mull_ferrite_sheet")
    rx_fr4_bounds = _combined_bounds(
        _bodies_with_role(_bodies_with_prefix(bodies, "rx_ssw_coil_"), "fr4", "RX SSW bodies"),
        "RX SSW FR4 bodies",
    )
    tx_under_bodies = tuple(body for body in bodies if body.name.startswith("tx_under_coil_"))
    if spec.tx_under.is_under_coil_enabled:
        if len(tx_under_bodies) == 0:
            raise ValueError("tx_under_coil enabled but no under-coil bodies were generated")
        if len(tx_ferrite_bodies) != 0:
            raise ValueError("TX MULL ferrite sheet must not exist when tx_under_coil is enabled")
    elif len(tx_under_bodies) != 0:
        raise ValueError("tx_under_coil disabled but under-coil bodies were generated")
    if (
        spec.ferrite.tx_mull_is_enabled
        and not spec.tx_under.is_under_coil_enabled
        and len(tx_ferrite_bodies) != spec.ferrite.tx_mull_sheet_count
    ):
        raise ValueError(
            f"ferrite.tx_mull_is_enabled requires exactly {spec.ferrite.tx_mull_sheet_count} "
            f"TX MULL ferrite sheet(s) (actual={len(tx_ferrite_bodies)})"
        )
    if not spec.ferrite.tx_mull_is_enabled and len(tx_ferrite_bodies) != 0:
        raise ValueError("ferrite.tx_mull_is_enabled is disabled but TX MULL ferrite sheet was generated")
    if spec.ferrite.rx_mull_is_enabled and len(rx_ferrite_bodies) != 1:
        raise ValueError("ferrite.rx_mull_is_enabled requires exactly one RX MULL ferrite sheet")
    if not spec.ferrite.rx_mull_is_enabled and len(rx_ferrite_bodies) != 0:
        raise ValueError("ferrite.rx_mull_is_enabled is disabled but RX MULL ferrite sheet was generated")

    if abs(tx_region_bounds.zmax - (tv_bounds.zmin - spec.fixed.tx_rx_min_distance_mm)) > tolerance:
        raise ValueError("tx_region top must equal TV bottom minus fixed_dimensions.tx_rx_min_distance_mm")
    _assert_inside_bounds(inner=tx_bounds, outer=tx_region_bounds, context="TX SSW")
    if (
        tx_region_bounds.size_x <= tx_bounds.size_x
        or tx_region_bounds.size_y <= tx_bounds.size_y
        or tx_region_bounds.size_z <= tx_bounds.size_z
    ):
        raise ValueError("tx_region must be a maximum TX placement envelope, not a coil-tight box")

    copper_tolerance = spec.fixed.copper_thickness_mm + tolerance
    if abs(rx_region_max_bounds.xmax - tv_bounds.xmax) > tolerance:
        raise ValueError(
            f"rx_region_max X max must align to TV X max "
            f"(rx_region_max_xmax={rx_region_max_bounds.xmax}, tv_xmax={tv_bounds.xmax})"
        )
    if (
        rx_region_max_bounds.ymin < tv_bounds.ymin - tolerance
        or rx_region_max_bounds.ymax > tv_bounds.ymax + tolerance
    ):
        raise ValueError("rx_region_max Y bounds must stay inside TV bounds")
    if (
        rx_region_max_bounds.zmin < tv_bounds.zmin - copper_tolerance
        or rx_region_max_bounds.zmax > tv_bounds.zmax + tolerance
    ):
        raise ValueError("rx_region_max Z bounds must stay inside TV bounds with copper-thickness bottom tolerance")
    _assert_inside_bounds(inner=rx_bounds, outer=rx_region_max_bounds, context="RX SSW")
    if abs(rx_bounds.xmax - rx_region_max_bounds.xmax) > tolerance:
        raise ValueError(
            f"RX SSW X max must align to rx_region_max X max "
            f"(rx_xmax={rx_bounds.xmax}, rx_region_max_xmax={rx_region_max_bounds.xmax})"
        )
    _assert_inside_bounds(inner=rx_fr4_bounds, outer=tv_bounds, context="RX SSW FR4")
    _assert_inside_bounds_with_tolerance(
        inner=rx_bounds,
        outer=tv_bounds,
        context="RX SSW copper",
        tolerance=copper_tolerance,
    )
    if abs(rx_bounds.zmin - tv_bounds.zmin) > tolerance:
        raise ValueError(
            f"RX SSW bottom must align to TV bottom "
            f"(rx_zmin={rx_bounds.zmin}, tv_zmin={tv_bounds.zmin})"
        )

    if abs(tx_bounds.zmax - tx_region_bounds.zmax) > tolerance:
        raise ValueError(
            f"TX SSW top must align to tx_region top "
            f"(tx_zmax={tx_bounds.zmax}, tx_region_zmax={tx_region_bounds.zmax})"
        )
    tx_part = _scene_part_by_role(parts=parts, role="tx_ssw_coil")
    tx_port_anchor = _ssw_port_anchor_world_xyz_from_placement(
        spec=spec,
        params=spec.tx,
        placement=tx_part.placement,
    )
    if abs(tx_port_anchor[2] - tx_bounds.zmin) > tolerance:
        raise ValueError(
            f"TX SSW port anchor must be on the lower face "
            f"(port_z={tx_port_anchor[2]}, tx_zmin={tx_bounds.zmin})"
        )
    if spec.rx.is_ssw_enabled:
        rx_part = _scene_part_by_role(parts=parts, role="rx_ssw_coil")
        rx_port_anchor = _ssw_port_anchor_world_xyz_from_placement(
            spec=spec,
            params=spec.rx,
            placement=rx_part.placement,
        )
        if abs(rx_port_anchor[0] - rx_bounds.xmax) > tolerance:
            raise ValueError(
                f"RX SSW port anchor must be on the RX X-max copper face "
                f"(port_x={rx_port_anchor[0]}, rx_xmax={rx_bounds.xmax})"
            )
    if tx_bounds.size_z >= tx_bounds.size_x or tx_bounds.size_z >= tx_bounds.size_y:
        raise ValueError(
            f"TX SSW must remain an XY-plane object with thin Z stack "
            f"(size_x={tx_bounds.size_x}, size_y={tx_bounds.size_y}, size_z={tx_bounds.size_z})"
        )
    if rx_bounds.size_x >= rx_bounds.size_y or rx_bounds.size_x >= rx_bounds.size_z:
        raise ValueError(
            f"RX SSW must remain a YZ-plane object with thin X stack "
            f"(size_x={rx_bounds.size_x}, size_y={rx_bounds.size_y}, size_z={rx_bounds.size_z})"
        )

    thickness = spec.fixed.mull_ferrite_thickness_mm
    if spec.ferrite.rx_mull_is_enabled:
        rx_ferrite_bounds = _body_bounds(_body_by_name(bodies, "rx_mull_ferrite_sheet"))
        if abs(rx_ferrite_bounds.size_x - thickness) > tolerance:
            raise ValueError("RX MULL ferrite sheet thickness must match fixed_dimensions.mull_ferrite_thickness_mm")
        if (
            abs(rx_ferrite_bounds.size_y - rx_bounds.size_y) > tolerance
            or abs(rx_ferrite_bounds.size_z - rx_bounds.size_z) > tolerance
            or abs(rx_ferrite_bounds.center_y - rx_bounds.center_y) > tolerance
            or abs(rx_ferrite_bounds.center_z - rx_bounds.center_z) > tolerance
        ):
            raise ValueError("RX MULL ferrite sheet must match RX coil YZ footprint")
        if (
            rx_ferrite_bounds.xmin < rx_region_max_bounds.xmin - tolerance
            or rx_ferrite_bounds.xmax > rx_bounds.xmin + tolerance
        ):
            raise ValueError("RX MULL ferrite sheet must stay between rx_region_max X min and RX coil X min")

    if spec.tx_under.is_under_coil_enabled:
        tx_under_bounds = _combined_bounds(tx_under_bodies, "TX under-coil bodies")
        if (
            tx_under_bounds.ymin < tx_region_max_bounds.ymin - tolerance
            or tx_under_bounds.ymax > tx_region_max_bounds.ymax + tolerance
            or tx_under_bounds.zmin < tx_region_max_bounds.zmin - tolerance
            or tx_under_bounds.zmax > tx_region_max_bounds.zmax + tolerance
        ):
            raise ValueError("TX under-coil YZ footprint must stay inside tx_region_max")
        if abs(tx_under_bounds.xmax - tx_region_max_bounds.xmin) > tolerance:
            raise ValueError(
                f"TX under-coil X max must align to tx_region_max X min "
                f"(under_xmax={tx_under_bounds.xmax}, tx_region_max_xmin={tx_region_max_bounds.xmin})"
            )
        if tx_under_bounds.size_x >= tx_under_bounds.size_y or tx_under_bounds.size_x >= tx_under_bounds.size_z:
            raise ValueError(
                f"TX under-coil must remain a YZ-plane normal spiral object "
                f"(size_x={tx_under_bounds.size_x}, size_y={tx_under_bounds.size_y}, size_z={tx_under_bounds.size_z})"
            )
        if tx_under_bounds.size_y <= tx_under_bounds.size_z:
            raise ValueError(
                f"TX under-coil Y footprint must exceed Z footprint "
                f"(size_y={tx_under_bounds.size_y}, size_z={tx_under_bounds.size_z})"
            )

    if spec.ferrite.tx_mull_is_enabled:
        for tx_ferrite_body in tx_ferrite_bodies:
            tx_ferrite_bounds = _body_bounds(tx_ferrite_body)
            if abs(tx_ferrite_bounds.size_z - thickness) > tolerance:
                raise ValueError("TX MULL ferrite sheet thickness must match fixed_dimensions.mull_ferrite_thickness_mm")
            if (
                abs(tx_ferrite_bounds.size_x - tx_bounds.size_x) > tolerance
                or abs(tx_ferrite_bounds.size_y - tx_bounds.size_y) > tolerance
                or abs(tx_ferrite_bounds.center_x - tx_bounds.center_x) > tolerance
                or abs(tx_ferrite_bounds.center_y - tx_bounds.center_y) > tolerance
            ):
                raise ValueError("TX MULL ferrite sheet must match TX coil XY footprint")
            if (
                tx_ferrite_bounds.zmin < tx_region_max_bounds.zmin - tolerance
                or tx_ferrite_bounds.zmax > tx_bounds.zmin + tolerance
            ):
                raise ValueError("TX MULL ferrite sheet must stay between tx_region_max Z min and TX coil Z min")


def _action_value_to_jsonable(value: coilmaker.ActionValue) -> object:
    if isinstance(value, tuple):
        return [_action_value_to_jsonable(component) for component in value]
    if isinstance(value, (str, int, float, bool, _NONE_TYPE)):
        return value
    raise TypeError(f"Unsupported action value for TOML export: {value!r}")


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_string_array(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def _action_value_type(value: coilmaker.ActionValue) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, str):
        return "str"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, _NONE_TYPE):
        return "none"
    if isinstance(value, tuple):
        return "tuple"
    raise TypeError(f"Unsupported action value for TOML export: {value!r}")


def _namespace_ref(role: Role, ref: str) -> str:
    return f"{role}.{ref}"


def _namespaced_action_token(*, role: Role, index: int, token: coilmaker.ActionToken) -> coilmaker.ActionToken:
    return coilmaker.ActionToken(
        index=index,
        op=token.op,
        target=_namespace_ref(role, token.target),
        inputs=tuple(_namespace_ref(role, input_ref) for input_ref in token.inputs),
        params=(("coil_role", role), *token.params),
    )


def _action_token(
    *,
    index: int,
    op: str,
    target: str,
    inputs: tuple[str, ...],
    params: tuple[coilmaker.ActionParam, ...],
) -> coilmaker.ActionToken:
    return coilmaker.ActionToken(index=index, op=op, target=target, inputs=inputs, params=params)


def _placement_action_token(
    *,
    index: int,
    role: Role,
    coil_mode: str,
    plane: str,
    bounds: _Bounds,
    port_face: str,
    port_anchor_world_xyz: Point3,
    no_ssw_qturn_start_int: int,
    no_ssw_qturn_n_int: int,
) -> coilmaker.ActionToken:
    if role == "tx_ssw_coil":
        placement_input = "non_model.tx_region"
    elif role == "tx_under_coil":
        placement_input = "non_model.tx_region_max"
    elif role == "rx_ssw_coil":
        placement_input = "non_model.tv"
    else:
        raise ValueError(f"unsupported placement role {role!r}")
    return _action_token(
        index=index,
        op="PLACE_COIL_IN_SCENE",
        target=f"scene.{role}.placement",
        inputs=(
            _namespace_ref(role, "assembly.pcb_stack"),
            placement_input,
        ),
        params=(
            ("coil_role", role),
            ("coil_mode", coil_mode),
            ("plane", plane),
            ("bounds_min_xyz_mm", (bounds.xmin, bounds.ymin, bounds.zmin)),
            ("bounds_max_xyz_mm", (bounds.xmax, bounds.ymax, bounds.zmax)),
            ("port_face", port_face),
            ("port_anchor_world_xyz_mm", port_anchor_world_xyz),
            ("no_ssw_qturn_start_int", no_ssw_qturn_start_int),
            ("no_ssw_qturn_n_int", no_ssw_qturn_n_int),
        ),
    )


def _non_model_action_token(*, index: int, body: _BodyBox) -> coilmaker.ActionToken:
    bounds = _body_bounds(body)
    return _action_token(
        index=index,
        op="CREATE_NON_MODEL_BOX",
        target=f"non_model.{body.name}",
        inputs=(),
        params=(
            ("material", body.material),
            ("transparency", body.transparency),
            ("bounds_min_xyz_mm", (bounds.xmin, bounds.ymin, bounds.zmin)),
            ("bounds_max_xyz_mm", (bounds.xmax, bounds.ymax, bounds.zmax)),
        ),
    )


def _mull_ferrite_action_token(
    *,
    index: int,
    body: _BodyBox,
    spec: SswFixedSpec,
) -> coilmaker.ActionToken:
    bounds = _body_bounds(body)
    if body.name.startswith("tx_mull_ferrite_sheet"):
        coil_role = "tx_ssw_coil"
        plane = "XY"
        inputs = ("scene.tx_ssw_coil.placement", "non_model.tx_region")
        ratio_param = "tx_mull_position_ratio"
        ratio_value = spec.ferrite.tx_mull_position_ratio
    elif body.name == "rx_mull_ferrite_sheet":
        coil_role = "rx_ssw_coil"
        plane = "YZ"
        inputs = ("scene.rx_ssw_coil.placement", "non_model.rx_region_max")
        ratio_param = "rx_mull_position_ratio"
        ratio_value = spec.ferrite.rx_mull_position_ratio
    else:
        raise ValueError(f"unsupported MULL ferrite sheet body {body.name!r}")
    return _action_token(
        index=index,
        op="CREATE_MULL_FERRITE_SHEET",
        target=f"ferrite.{body.name}",
        inputs=inputs,
        params=(
            ("coil_role", coil_role),
            ("material", body.material),
            ("transparency", body.transparency),
            ("plane", plane),
            ("thickness_mm", spec.fixed.mull_ferrite_thickness_mm),
            (ratio_param, ratio_value),
            ("bounds_min_xyz_mm", (bounds.xmin, bounds.ymin, bounds.zmin)),
            ("bounds_max_xyz_mm", (bounds.xmax, bounds.ymax, bounds.zmax)),
        ),
    )


@log_call_duration
def _scene_action_trace(
    *,
    spec: SswFixedSpec,
    scene_step_path: Path,
    token_toml_path: Path,
    bodies: tuple[_BodyBox, ...],
    parts: tuple[_CoilScenePart, ...],
    seed: int,
) -> tuple[coilmaker.ActionToken, ...]:
    actions: list[coilmaker.ActionToken] = [
        _action_token(
            index=0,
            op="BEGIN_SSW_SCENE",
            target="scene.0.3.x_fixed",
            inputs=(),
            params=(
                ("source_toml_path", spec.source_toml_path),
                ("schema_id", SCHEMA_ID),
                ("spec_version", SPEC_VERSION),
                ("seed", seed),
                ("units", spec.units),
            ),
        )
    ]
    non_model_bodies = _non_model_boxes(spec)
    for body in non_model_bodies:
        actions.append(_non_model_action_token(index=len(actions), body=body))
    role_params: list[tuple[Role, SswCoilParameters]] = [("tx_ssw_coil", spec.tx), ("rx_ssw_coil", spec.rx)]
    if spec.tx_under.is_under_coil_enabled:
        role_params.insert(1, ("tx_under_coil", spec.tx_under))
    for role, params in role_params:
        trace = coilmaker.assert_transformer_ready_action_trace(
            coilmaker.materialize_action_trace(_coilmaker_config(params, spec.fixed))
        )
        for token in trace:
            actions.append(_namespaced_action_token(role=role, index=len(actions), token=token))

    tx_bounds = _combined_bounds(_bodies_with_prefix(bodies, "tx_ssw_coil_"), "TX SSW bodies")
    rx_bounds = _combined_bounds(_bodies_with_prefix(bodies, "rx_ssw_coil_"), "RX SSW bodies")
    if spec.tx_under.is_under_coil_enabled:
        tx_under_bounds = _combined_bounds(_bodies_with_prefix(bodies, "tx_under_coil_"), "TX under-coil bodies")
    ferrite_bodies = tuple(body for body in bodies if body.role == "ferrite")
    rx_port_face = "rx_x_max" if spec.rx.is_ssw_enabled else "normal_spiral_landing"
    tx_part = _scene_part_by_role(parts=parts, role="tx_ssw_coil")
    rx_part = _scene_part_by_role(parts=parts, role="rx_ssw_coil")
    rx_port_anchor = (
        _ssw_port_anchor_world_xyz_from_placement(spec=spec, params=spec.rx, placement=rx_part.placement)
        if spec.rx.is_ssw_enabled
        else (rx_bounds.xmin, rx_bounds.center_y, rx_bounds.center_z)
    )
    actions.append(
        _placement_action_token(
            index=len(actions),
            role="tx_ssw_coil",
            coil_mode="ssw",
            plane="XY",
            bounds=tx_bounds,
            port_face="lower_z",
            port_anchor_world_xyz=_ssw_port_anchor_world_xyz_from_placement(
                spec=spec,
                params=spec.tx,
                placement=tx_part.placement,
            ),
            no_ssw_qturn_start_int=spec.tx.no_ssw_qturn_start_int,
            no_ssw_qturn_n_int=spec.tx.no_ssw_qturn_n_int,
        )
    )
    if spec.tx_under.is_under_coil_enabled:
        actions.append(
            _placement_action_token(
                index=len(actions),
                role="tx_under_coil",
                coil_mode="normal_spiral",
                plane="YZ",
                bounds=tx_under_bounds,
                port_face="none",
                port_anchor_world_xyz=(tx_under_bounds.xmin, tx_under_bounds.center_y, tx_under_bounds.center_z),
                no_ssw_qturn_start_int=spec.tx_under.no_ssw_qturn_start_int,
                no_ssw_qturn_n_int=spec.tx_under.no_ssw_qturn_n_int,
            )
        )
    actions.append(
        _placement_action_token(
            index=len(actions),
            role="rx_ssw_coil",
            coil_mode="ssw" if spec.rx.is_ssw_enabled else "normal_spiral",
            plane="YZ",
            bounds=rx_bounds,
            port_face=rx_port_face,
            port_anchor_world_xyz=rx_port_anchor,
            no_ssw_qturn_start_int=spec.rx.no_ssw_qturn_start_int,
            no_ssw_qturn_n_int=spec.rx.no_ssw_qturn_n_int,
        )
    )
    for body in ferrite_bodies:
        actions.append(_mull_ferrite_action_token(index=len(actions), body=body, spec=spec))
    actions.append(
        _action_token(
            index=len(actions),
            op="EXPORT_STEP",
            target="output.ssw_scene.step",
            inputs=(
                *(f"non_model.{body.name}" for body in non_model_bodies),
                "scene.tx_ssw_coil.placement",
                *(("scene.tx_under_coil.placement",) if spec.tx_under.is_under_coil_enabled else ()),
                "scene.rx_ssw_coil.placement",
                *(f"ferrite.{body.name}" for body in ferrite_bodies),
            ),
            params=(
                ("scene_step_name", scene_step_path.name),
                ("token_toml_name", token_toml_path.name),
                ("output_token_toml", token_toml_path.name),
            ),
        )
    )
    return coilmaker.assert_transformer_ready_action_trace(tuple(actions))


def _action_param_toml_lines(param: coilmaker.ActionParam) -> tuple[str, ...]:
    key, value = param
    return (
        "[[actions.params]]",
        f"key = {_toml_string(key)}",
        f"value_type = {_toml_string(_action_value_type(value))}",
        "value_json = "
        + _toml_string(
            json.dumps(
                _action_value_to_jsonable(value),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        ),
    )


def _action_token_toml_lines(token: coilmaker.ActionToken) -> tuple[str, ...]:
    header = (
        "[[actions]]",
        f"index = {token.index}",
        f"op = {_toml_string(token.op)}",
        f"target = {_toml_string(token.target)}",
        f"inputs = {_toml_string_array(token.inputs)}",
    )
    param_lines: list[str] = []
    for param in token.params:
        param_lines.extend(_action_param_toml_lines(param))
    return (*header, *param_lines)


def action_trace_to_toml(
    *,
    trace: tuple[coilmaker.ActionToken, ...],
    source_toml_path: Path,
    seed: int,
) -> str:
    validated = coilmaker.assert_transformer_ready_action_trace(trace)
    lines: list[str] = [
        "[metadata]",
        'format = "peetsfea_ssw_scene_action_tokens_v1"',
        f"action_count = {len(validated)}",
        f"seed = {seed}",
        f"source_toml_path = {_toml_string(str(source_toml_path))}",
        f"schema_id = {_toml_string(SCHEMA_ID)}",
        f"spec_version = {_toml_string(SPEC_VERSION)}",
        "",
    ]
    for token in validated:
        lines.extend(_action_token_toml_lines(token))
        lines.append("")
    return "\n".join(lines)


@log_call_duration
def write_coil_making_token_toml(
    *,
    token_toml_path: Path,
    trace: tuple[coilmaker.ActionToken, ...],
    source_toml_path: Path,
    seed: int,
) -> None:
    token_toml_path.parent.mkdir(parents=True, exist_ok=True)
    token_toml_path.write_text(
        action_trace_to_toml(trace=trace, source_toml_path=source_toml_path, seed=seed),
        encoding="utf-8",
    )
    parsed = tomllib.loads(token_toml_path.read_text(encoding="utf-8"))
    _require_table(parsed, str(token_toml_path))


@log_call_duration
def _build_ssw_scene(spec: SswFixedSpec) -> _SswSceneBuild:
    parts = _coil_scene_parts(spec)
    tx_boxes = _scene_part_by_role(parts=parts, role="tx_ssw_coil").bodies
    tx_under_boxes = (
        _scene_part_by_role(parts=parts, role="tx_under_coil").bodies if spec.tx_under.is_under_coil_enabled else ()
    )
    rx_boxes = _scene_part_by_role(parts=parts, role="rx_ssw_coil").bodies
    ferrite_boxes = _mull_ferrite_sheet_boxes(spec=spec, tx_boxes=tx_boxes, rx_boxes=rx_boxes)
    bodies = (*_non_model_boxes(spec), *tx_boxes, *tx_under_boxes, *rx_boxes, *ferrite_boxes)
    names = tuple(body.name for body in bodies)
    if len(names) != len(set(names)):
        raise ValueError(f"SSW body names must be unique (body_names={names!r})")
    _validate_scene_contract(spec=spec, bodies=bodies, parts=parts)
    assembly = _build_scene_assembly_from_parts(bodies=bodies, parts=parts)
    return _SswSceneBuild(spec=spec, bodies=bodies, assembly=assembly, parts=parts)


def _workplane_from_box(body: _BodyBox) -> cq.Workplane:
    return cq.Workplane("XY").box(*body.size_xyz).translate(body.center_xyz)


def _build_scene_assembly_from_parts(
    *,
    bodies: tuple[_BodyBox, ...],
    parts: tuple[_CoilScenePart, ...],
) -> cq.Assembly:
    assembly = cq.Assembly(name="ssw_0_3_0_fixed")
    for body in tuple(body for body in bodies if body.role in ("non_model", "ferrite")):
        assembly.add(_workplane_from_box(body), name=body.name, color=_color_for_body(body))
    for part in parts:
        for child in part.assembly.children:
            child_name = _child_name(child)
            material = _coilmaker_child_material(child_name)
            body_for_color = _BodyBox(
                name=f"{part.params.role}_{child_name}",
                role=_coilmaker_child_role(child_name),
                material=material,
                center_xyz=(0.0, 0.0, 0.0),
                size_xyz=(1.0, 1.0, 1.0),
                transparency=_transparency_for_coilmaker_child(child_name),
            )
            assembly.add(
                _child_workplane(child),
                name=f"{part.params.role}_{child_name}",
                loc=part.placement * _child_location(child),
                color=_color_for_body(body_for_color),
            )
    return assembly


@log_call_duration
def build_ssw_body_boxes(spec: SswFixedSpec) -> tuple[_BodyBox, ...]:
    return _build_ssw_scene(spec).bodies


@log_call_duration
def build_ssw_assembly(spec: SswFixedSpec) -> cq.Assembly:
    return _build_ssw_scene(spec).assembly


def _body_entry(body: _BodyBox) -> BodyLedgerEntry:
    return {
        "object_id": body.name,
        "role": body.role,
        "material": body.material,
        "transparency": body.transparency,
        "center_xyz": [body.center_xyz[0], body.center_xyz[1], body.center_xyz[2]],
        "size_xyz": [body.size_xyz[0], body.size_xyz[1], body.size_xyz[2]],
    }


@log_call_duration
def _build_ledger(
    *,
    spec: SswFixedSpec,
    scene_step_path: Path,
    token_toml_path: Path,
    seed: int,
    bodies: tuple[_BodyBox, ...],
) -> SswStepLedger:
    return {
        "source_toml_path": spec.source_toml_path,
        "scene_step_path": str(scene_step_path),
        "token_toml_path": str(token_toml_path),
        "seed": seed,
        "units": spec.units,
        "body_names": [body.name for body in bodies],
        "copper_body_names": [body.name for body in bodies if body.role == "copper"],
        "fr4_body_names": [body.name for body in bodies if body.role == "fr4"],
        "non_model_body_names": [body.name for body in bodies if body.role == "non_model"],
        "ferrite_body_names": [body.name for body in bodies if body.role == "ferrite"],
        "bodies": [_body_entry(body) for body in bodies],
    }


@log_call_duration
def write_ssw_step_ledger(*, ledger_path: Path, ledger: SswStepLedger) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_ssw_step_ledger(ledger_path: Path) -> SswStepLedger:
    raw_ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if not isinstance(raw_ledger, dict):
        raise TypeError(f"SSW STEP ledger must be a JSON object: {ledger_path}")
    for key in (
        "source_toml_path",
        "scene_step_path",
        "token_toml_path",
        "seed",
        "units",
        "body_names",
        "copper_body_names",
        "fr4_body_names",
        "non_model_body_names",
        "ferrite_body_names",
        "bodies",
    ):
        if key not in raw_ledger:
            raise ValueError(f"SSW STEP ledger is missing required key {key!r}: {ledger_path}")
    return cast(SswStepLedger, raw_ledger)


@log_call_duration
def _save_ssw_scene_step(*, assembly: cq.Assembly, scene_step_path: Path) -> None:
    assembly.save(str(scene_step_path), exportType="STEP")


@log_call_duration
def export_ssw_step_artifacts(
    *,
    source_toml_path: Path = DEFAULT_SOURCE_TOML_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    seed: int = 0,
) -> SswStepArtifacts:
    spec = load_ssw_fixed_spec(source_toml_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    scene_step_path = output_dir / DEFAULT_SCENE_STEP_NAME
    ledger_path = output_dir / DEFAULT_LEDGER_NAME
    token_toml_path = output_dir / DEFAULT_TOKEN_TOML_NAME
    scene = _build_ssw_scene(spec)
    token_trace = _scene_action_trace(
        spec=spec,
        scene_step_path=scene_step_path,
        token_toml_path=token_toml_path,
        bodies=scene.bodies,
        parts=scene.parts,
        seed=seed,
    )
    write_coil_making_token_toml(
        token_toml_path=token_toml_path,
        trace=token_trace,
        source_toml_path=source_toml_path,
        seed=seed,
    )
    _save_ssw_scene_step(assembly=scene.assembly, scene_step_path=scene_step_path)
    if not scene_step_path.is_file() or scene_step_path.stat().st_size <= 0:
        raise RuntimeError(f"CadQuery STEP export failed for SSW scene: {scene_step_path}")
    ledger = _build_ledger(
        spec=spec,
        scene_step_path=scene_step_path,
        token_toml_path=token_toml_path,
        seed=seed,
        bodies=scene.bodies,
    )
    write_ssw_step_ledger(ledger_path=ledger_path, ledger=ledger)
    return {
        "source_toml_path": spec.source_toml_path,
        "scene_step_path": str(scene_step_path),
        "ledger_path": str(ledger_path),
        "token_toml_path": str(token_toml_path),
        "seed": seed,
        "body_names": ledger["body_names"],
    }


__all__ = [
    "DEFAULT_LEDGER_NAME",
    "DEFAULT_OUTPUT_DIR",
    "DEFAULT_SCENE_STEP_NAME",
    "DEFAULT_SOURCE_TOML_PATH",
    "DEFAULT_TOKEN_TOML_NAME",
    "SCHEMA_ID",
    "SPEC_VERSION",
    "FixedDimensions",
    "SswCoilParameters",
    "SswFixedSpec",
    "SswStepArtifacts",
    "SswStepLedger",
    "action_trace_to_toml",
    "build_ssw_assembly",
    "build_ssw_body_boxes",
    "export_ssw_step_artifacts",
    "load_ssw_fixed_spec",
    "load_ssw_step_ledger",
    "normal_spiral_trace_width_mm",
    "ssw_trace_width_mm",
    "write_coil_making_token_toml",
    "write_ssw_step_ledger",
]
