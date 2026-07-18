from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
import tomllib

SPEC_VERSION = "0.3.0"
SCHEMA_ID = "peetsfea.minimal_step_two_port.v1"
SUPPORTED_UNITS = "mm"
FORBIDDEN_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {
        "backend",
        "coordinate_system",
        "constraints",
        "modeled_objects",
        "outputs",
        "simulation",
    }
)

Point3 = tuple[float, float, float]
Plane = Literal["XY", "YZ", "ZX"]


@dataclass(frozen=True)
class MinimalNonModelBox:
    object_id: str
    kind: str
    material: str
    plane: Plane
    origin_xyz: Point3
    size_xyz: Point3


@dataclass(frozen=True)
class MinimalSpec:
    source_toml_path: str
    units: Literal["mm"]
    non_model_objects: tuple[MinimalNonModelBox, ...]


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


def _require_true(table: dict[str, object], key: str, context: str) -> Literal[True]:
    raw_value = _require_key(table, key, context)
    if raw_value is not True:
        raise ValueError(f"{context}.{key} must be true")
    return True


def _require_plane(table: dict[str, object], key: str, context: str) -> Plane:
    raw_plane = _require_non_empty_str(table, key, context)
    if raw_plane == "XY":
        return "XY"
    if raw_plane == "YZ":
        return "YZ"
    if raw_plane == "ZX":
        return "ZX"
    raise ValueError(f"{context}.{key} must be one of ['XY', 'YZ', 'ZX'] (actual={raw_plane!r})")


def _require_point3(table: dict[str, object], key: str, context: str, *, positive: bool) -> Point3:
    raw_value = _require_key(table, key, context)
    if isinstance(raw_value, (str, bytes)) or not isinstance(raw_value, list):
        raise TypeError(f"{context}.{key} must be a list of three numbers")
    if len(raw_value) != 3:
        raise ValueError(f"{context}.{key} must contain exactly three entries")
    parsed: list[float] = []
    for index, raw_component in enumerate(raw_value):
        if isinstance(raw_component, bool) or not isinstance(raw_component, (int, float)):
            raise TypeError(f"{context}.{key}[{index}] must be numeric")
        component = float(raw_component)
        if positive and component <= 0.0:
            raise ValueError(f"{context}.{key}[{index}] must be > 0")
        parsed.append(component)
    return (parsed[0], parsed[1], parsed[2])


def _reject_forbidden_top_level_keys(root: dict[str, object], *, context: str) -> None:
    forbidden = sorted(FORBIDDEN_TOP_LEVEL_KEYS.intersection(root.keys()))
    if forbidden:
        raise ValueError(
            f"{context} contains sections removed from the 0.3.0 minimal contract "
            f"(forbidden={forbidden})"
        )


def _parse_non_model_object(
    raw_object: object,
    *,
    index: int,
    seen_object_ids: set[str],
    context: str,
) -> MinimalNonModelBox:
    table = _require_table(raw_object, context)
    object_id = _require_non_empty_str(table, "id", context)
    if object_id in seen_object_ids:
        raise ValueError(f"{context}.id must be unique (duplicate={object_id!r})")
    seen_object_ids.add(object_id)
    primitive = _require_non_empty_str(table, "primitive", context)
    if primitive != "box":
        raise ValueError(f"{context}.primitive must be 'box' for minimal 0.3.0 (actual={primitive!r})")
    _require_true(table, "present", context)
    _require_true(table, "non_model", context)
    return MinimalNonModelBox(
        object_id=object_id,
        kind=_require_non_empty_str(table, "kind", context),
        material=_require_non_empty_str(table, "material", context),
        plane=_require_plane(table, "plane", context),
        origin_xyz=_require_point3(table, "origin_xyz", context, positive=False),
        size_xyz=_require_point3(table, "size_xyz", context, positive=True),
    )


def load_minimal_spec(toml_path: Path) -> MinimalSpec:
    raw_text = toml_path.read_text(encoding="utf-8")
    raw_spec = tomllib.loads(raw_text)
    root = _require_table(raw_spec, toml_path.name)
    _reject_forbidden_top_level_keys(root, context=toml_path.name)

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

    raw_non_model_objects = _require_key(root, "non_model_objects", toml_path.name)
    if isinstance(raw_non_model_objects, (str, bytes)) or not isinstance(raw_non_model_objects, list):
        raise TypeError("non_model_objects must be an array of tables")
    if len(raw_non_model_objects) == 0:
        raise ValueError("non_model_objects must not be empty")

    seen_object_ids: set[str] = set()
    parsed_objects = tuple(
        _parse_non_model_object(
            raw_object,
            index=index,
            seen_object_ids=seen_object_ids,
            context=f"{toml_path.name}.non_model_objects[{index}]",
        )
        for index, raw_object in enumerate(raw_non_model_objects)
    )
    return MinimalSpec(
        source_toml_path=str(toml_path),
        units="mm",
        non_model_objects=parsed_objects,
    )


__all__ = [
    "MinimalNonModelBox",
    "MinimalSpec",
    "Plane",
    "Point3",
    "SCHEMA_ID",
    "SPEC_VERSION",
    "load_minimal_spec",
]
