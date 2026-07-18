from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict, cast

import build123d as bd
from build123d.topology import Shape

from peetsfea.minimal_spec import MinimalNonModelBox, MinimalSpec, Point3, load_minimal_spec

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "run" / "minimal"
DEFAULT_SCENE_STEP_NAME = "minimal_scene.step"
DEFAULT_LEDGER_NAME = "minimal_step_ledger.json"

TX_CENTER_X_MM = -25.0
RX_CENTER_X_MM = 25.0
PORT_CELL_CENTER_Y_MM = 0.0
PORT_CELL_Z_MIN_MM = 0.0
PAD_X_MM = 20.0
PAD_Y_MM = 10.0
PAD_THICKNESS_MM = 0.035
PORT_GAP_Y_MM = 1.0

BodyRole = Literal["non_model", "tx_signal", "tx_reference", "tx_port_sheet", "rx_signal", "rx_reference", "rx_port_sheet"]


class CanonicalCoordinates(TypedDict):
    outer_bounds_min_xyz: list[float]
    outer_bounds_max_xyz: list[float]
    outer_bounds_size_xyz: list[float]


class MinimalBodyLedgerEntry(TypedDict):
    object_id: str
    role: BodyRole
    material: str
    model_state: bool
    canonical_coordinates: CanonicalCoordinates


class MinimalPortCellLedgerEntry(TypedDict):
    role: Literal["tx", "rx"]
    signal_pad_name: str
    reference_pad_name: str
    port_sheet_name: str
    port_sheet_vertices_xyz: list[list[float]]
    signal_edge_vertices_xyz: list[list[float]]
    reference_edge_vertices_xyz: list[list[float]]


class MinimalStepLedger(TypedDict):
    source_toml_path: str
    scene_step_path: str
    seed: int
    units: Literal["mm"]
    body_names: list[str]
    copper_body_names: list[str]
    port_sheet_names: list[str]
    non_model_body_names: list[str]
    bodies: list[MinimalBodyLedgerEntry]
    port_cells: list[MinimalPortCellLedgerEntry]


class MinimalStepArtifacts(TypedDict):
    source_toml_path: str
    scene_step_path: str
    ledger_path: str
    seed: int
    body_names: list[str]


@dataclass(frozen=True)
class _BodyShape:
    name: str
    role: BodyRole
    material: str
    model_state: bool
    shape: Shape


def _canonical_from_bounds(*, min_xyz: Point3, size_xyz: Point3) -> CanonicalCoordinates:
    return {
        "outer_bounds_min_xyz": [min_xyz[0], min_xyz[1], min_xyz[2]],
        "outer_bounds_max_xyz": [min_xyz[0] + size_xyz[0], min_xyz[1] + size_xyz[1], min_xyz[2] + size_xyz[2]],
        "outer_bounds_size_xyz": [size_xyz[0], size_xyz[1], size_xyz[2]],
    }


def _canonical_from_shape(shape: Shape) -> CanonicalCoordinates:
    bbox = shape.bounding_box()
    return {
        "outer_bounds_min_xyz": [bbox.min.X, bbox.min.Y, bbox.min.Z],
        "outer_bounds_max_xyz": [bbox.max.X, bbox.max.Y, bbox.max.Z],
        "outer_bounds_size_xyz": [bbox.max.X - bbox.min.X, bbox.max.Y - bbox.min.Y, bbox.max.Z - bbox.min.Z],
    }


def _build_box_shape(*, name: str, origin_xyz: Point3, size_xyz: Point3) -> Shape:
    if size_xyz[0] <= 0.0 or size_xyz[1] <= 0.0 or size_xyz[2] <= 0.0:
        raise ValueError(f"{name} box size must be positive (size_xyz={size_xyz})")
    shape = bd.Box(*size_xyz, align=(bd.Align.MIN, bd.Align.MIN, bd.Align.MIN)).moved(
        bd.Location(origin_xyz)
    )
    solids = tuple(shape.solids())
    if len(solids) != 1:
        raise RuntimeError(f"{name} must generate exactly one STEP solid (solid_count={len(solids)})")
    solid = cast(Shape, solids[0])
    solid.label = name
    return solid


def _build_sheet_shape(*, name: str, center_xyz: Point3, size_x_mm: float, size_y_mm: float) -> Shape:
    if size_x_mm <= 0.0 or size_y_mm <= 0.0:
        raise ValueError(f"{name} sheet dimensions must be positive (size_x={size_x_mm}, size_y={size_y_mm})")
    sheet = bd.Rectangle(size_x_mm, size_y_mm).moved(bd.Location(center_xyz))
    faces = tuple(sheet.faces())
    if len(faces) != 1:
        raise RuntimeError(f"{name} must generate exactly one STEP face (face_count={len(faces)})")
    face = cast(Shape, faces[0])
    face.label = name
    return face


def _body_entry(*, body: _BodyShape) -> MinimalBodyLedgerEntry:
    return {
        "object_id": body.name,
        "role": body.role,
        "material": body.material,
        "model_state": body.model_state,
        "canonical_coordinates": _canonical_from_shape(body.shape),
    }


def _non_model_body(spec: MinimalNonModelBox) -> _BodyShape:
    return _BodyShape(
        name=spec.object_id,
        role="non_model",
        material=spec.material,
        model_state=False,
        shape=_build_box_shape(name=spec.object_id, origin_xyz=spec.origin_xyz, size_xyz=spec.size_xyz),
    )


def _port_sheet_vertices(*, center_x_mm: float) -> tuple[Point3, Point3, Point3, Point3]:
    half_x = PAD_X_MM / 2.0
    half_gap = PORT_GAP_Y_MM / 2.0
    z_top = PORT_CELL_Z_MIN_MM + PAD_THICKNESS_MM
    return (
        (center_x_mm - half_x, -half_gap, z_top),
        (center_x_mm + half_x, -half_gap, z_top),
        (center_x_mm + half_x, half_gap, z_top),
        (center_x_mm - half_x, half_gap, z_top),
    )


def _port_cell_bodies(*, role: Literal["tx", "rx"], center_x_mm: float) -> tuple[_BodyShape, _BodyShape, _BodyShape, MinimalPortCellLedgerEntry]:
    half_x = PAD_X_MM / 2.0
    half_y = PAD_Y_MM / 2.0
    half_gap = PORT_GAP_Y_MM / 2.0
    half_pad_y = (PAD_Y_MM - PORT_GAP_Y_MM) / 2.0
    if half_pad_y <= 0.0:
        raise ValueError("minimal port cell requires pad Y to be larger than port gap")

    signal_name = f"{role}_signal_pad"
    reference_name = f"{role}_reference_pad"
    sheet_name = f"{role}_port_sheet"
    signal_origin = (center_x_mm - half_x, -half_y, PORT_CELL_Z_MIN_MM)
    reference_origin = (center_x_mm - half_x, half_gap, PORT_CELL_Z_MIN_MM)
    pad_size = (PAD_X_MM, half_pad_y, PAD_THICKNESS_MM)
    signal_body = _BodyShape(
        name=signal_name,
        role=cast(BodyRole, f"{role}_signal"),
        material="copper",
        model_state=True,
        shape=_build_box_shape(name=signal_name, origin_xyz=signal_origin, size_xyz=pad_size),
    )
    reference_body = _BodyShape(
        name=reference_name,
        role=cast(BodyRole, f"{role}_reference"),
        material="copper",
        model_state=True,
        shape=_build_box_shape(name=reference_name, origin_xyz=reference_origin, size_xyz=pad_size),
    )
    sheet_vertices = _port_sheet_vertices(center_x_mm=center_x_mm)
    sheet_body = _BodyShape(
        name=sheet_name,
        role=cast(BodyRole, f"{role}_port_sheet"),
        material="vacuum",
        model_state=True,
        shape=_build_sheet_shape(
            name=sheet_name,
            center_xyz=(center_x_mm, PORT_CELL_CENTER_Y_MM, PORT_CELL_Z_MIN_MM + PAD_THICKNESS_MM),
            size_x_mm=PAD_X_MM,
            size_y_mm=PORT_GAP_Y_MM,
        ),
    )
    port_cell: MinimalPortCellLedgerEntry = {
        "role": role,
        "signal_pad_name": signal_name,
        "reference_pad_name": reference_name,
        "port_sheet_name": sheet_name,
        "port_sheet_vertices_xyz": [[x, y, z] for x, y, z in sheet_vertices],
        "signal_edge_vertices_xyz": [[sheet_vertices[0][0], sheet_vertices[0][1], sheet_vertices[0][2]], [sheet_vertices[1][0], sheet_vertices[1][1], sheet_vertices[1][2]]],
        "reference_edge_vertices_xyz": [[sheet_vertices[3][0], sheet_vertices[3][1], sheet_vertices[3][2]], [sheet_vertices[2][0], sheet_vertices[2][1], sheet_vertices[2][2]]],
    }
    return signal_body, reference_body, sheet_body, port_cell


def _build_scene_bodies(spec: MinimalSpec) -> tuple[tuple[_BodyShape, ...], tuple[MinimalPortCellLedgerEntry, ...]]:
    non_model_bodies = tuple(_non_model_body(non_model_spec) for non_model_spec in spec.non_model_objects)
    tx_signal, tx_reference, tx_sheet, tx_cell = _port_cell_bodies(role="tx", center_x_mm=TX_CENTER_X_MM)
    rx_signal, rx_reference, rx_sheet, rx_cell = _port_cell_bodies(role="rx", center_x_mm=RX_CENTER_X_MM)
    bodies = (*non_model_bodies, tx_signal, tx_reference, tx_sheet, rx_signal, rx_reference, rx_sheet)
    body_names = tuple(body.name for body in bodies)
    if len(body_names) != len(set(body_names)):
        raise ValueError(f"minimal STEP body names must be unique (body_names={body_names})")
    return bodies, (tx_cell, rx_cell)


def _build_ledger(
    *,
    spec: MinimalSpec,
    scene_step_path: Path,
    seed: int,
    bodies: tuple[_BodyShape, ...],
    port_cells: tuple[MinimalPortCellLedgerEntry, ...],
) -> MinimalStepLedger:
    body_entries = [_body_entry(body=body) for body in bodies]
    return {
        "source_toml_path": spec.source_toml_path,
        "scene_step_path": str(scene_step_path),
        "seed": seed,
        "units": spec.units,
        "body_names": [body.name for body in bodies],
        "copper_body_names": [body.name for body in bodies if body.material == "copper"],
        "port_sheet_names": [cell["port_sheet_name"] for cell in port_cells],
        "non_model_body_names": [body.name for body in bodies if body.role == "non_model"],
        "bodies": body_entries,
        "port_cells": list(port_cells),
    }


def write_minimal_step_ledger(*, ledger_path: Path, ledger: MinimalStepLedger) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_minimal_step_ledger(ledger_path: Path) -> MinimalStepLedger:
    raw_text = ledger_path.read_text(encoding="utf-8")
    raw_ledger = json.loads(raw_text)
    if not isinstance(raw_ledger, dict):
        raise TypeError(f"minimal STEP ledger must be a JSON object: {ledger_path}")
    for key in (
        "source_toml_path",
        "scene_step_path",
        "seed",
        "units",
        "body_names",
        "copper_body_names",
        "port_sheet_names",
        "non_model_body_names",
        "bodies",
        "port_cells",
    ):
        if key not in raw_ledger:
            raise ValueError(f"minimal STEP ledger is missing required key {key!r}: {ledger_path}")
    return cast(MinimalStepLedger, raw_ledger)


def export_minimal_step_artifacts(
    *,
    source_toml_path: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    seed: int = 0,
    scene_step_path: Path | str = "",
    ledger_path: Path | str = "",
) -> MinimalStepArtifacts:
    spec = load_minimal_spec(source_toml_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    resolved_scene_step_path = output_dir / DEFAULT_SCENE_STEP_NAME if scene_step_path == "" else Path(scene_step_path)
    resolved_ledger_path = output_dir / DEFAULT_LEDGER_NAME if ledger_path == "" else Path(ledger_path)
    bodies, port_cells = _build_scene_bodies(spec)
    scene = bd.Compound(children=tuple(body.shape for body in bodies), label="minimal_scene")
    export_ok = bd.export_step(scene, resolved_scene_step_path)
    if export_ok is not True:
        raise RuntimeError(f"build123d export_step returned False for minimal STEP: {resolved_scene_step_path}")
    ledger = _build_ledger(
        spec=spec,
        scene_step_path=resolved_scene_step_path,
        seed=seed,
        bodies=bodies,
        port_cells=port_cells,
    )
    write_minimal_step_ledger(ledger_path=resolved_ledger_path, ledger=ledger)
    return {
        "source_toml_path": spec.source_toml_path,
        "scene_step_path": str(resolved_scene_step_path),
        "ledger_path": str(resolved_ledger_path),
        "seed": seed,
        "body_names": ledger["body_names"],
    }


__all__ = [
    "DEFAULT_LEDGER_NAME",
    "DEFAULT_OUTPUT_DIR",
    "DEFAULT_SCENE_STEP_NAME",
    "MinimalBodyLedgerEntry",
    "MinimalPortCellLedgerEntry",
    "MinimalStepArtifacts",
    "MinimalStepLedger",
    "export_minimal_step_artifacts",
    "load_minimal_step_ledger",
    "write_minimal_step_ledger",
]
