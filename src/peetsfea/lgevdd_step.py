from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from pathlib import Path
from typing import cast

import build123d as bd
from build123d.topology import Shape, Solid

from peetsfea.lgevdd_fr4 import build_lgevdd_fr4
from peetsfea.lgevdd_primary import (
    LgeEvddPrimaryGeometry,
    build_lgevdd_primary_planar,
)
from peetsfea.lgevdd_secondary import (
    LgeEvddSecondaryGeometry,
    build_lgevdd_secondary_planar,
)
from peetsfea.lgevdd_spec import (
    DEFAULT_SOURCE_TOML_PATH,
    LgeEvddPcbSpec,
    load_lgevdd_pcb_spec,
)

DEFAULT_BOTH_STEP_NAME = "lgevdd_both.step"
DEFAULT_SECONDARY_STEP_NAME = "lgevdd_secondary.step"
DEFAULT_STEP_NAME = "lgevdd_pcb.step"


@dataclass(frozen=True)
class LgeEvddPcbArtifacts:
    spec: LgeEvddPcbSpec
    primary_geometry: LgeEvddPrimaryGeometry
    fr4_shape: Solid
    primary_shape: Solid
    scene_shape: Shape
    step_path: Path


@dataclass(frozen=True)
class LgeEvddSecondaryArtifacts:
    spec: LgeEvddPcbSpec
    primary_geometry: LgeEvddPrimaryGeometry
    secondary_geometry: LgeEvddSecondaryGeometry
    secondary_shapes: tuple[Solid, Solid]
    scene_shape: Shape
    step_path: Path


@dataclass(frozen=True)
class LgeEvddBothArtifacts:
    spec: LgeEvddPcbSpec
    primary_geometry: LgeEvddPrimaryGeometry
    secondary_geometry: LgeEvddSecondaryGeometry
    fr4_shape: Solid
    primary_shape: Solid
    secondary_shapes: tuple[Solid, Solid]
    scene_shape: Shape
    step_path: Path


def _require_one_valid_solid(shape: Shape, *, context: str) -> Solid:
    solids = tuple(shape.solids())
    if len(solids) != 1:
        raise RuntimeError(
            f"{context} must contain exactly one solid "
            f"(solid_count={len(solids)})"
        )
    solid = cast(Solid, solids[0])
    assert hasattr(solid, "is_valid")
    is_valid = solid.is_valid
    assert isinstance(is_valid, bool)
    if is_valid is not True:
        raise RuntimeError(f"{context} is not a valid solid")
    return solid


def _shape_label(shape: Shape, *, context: str) -> str:
    assert hasattr(shape, "label")
    raw_label = shape.label
    assert isinstance(raw_label, str)
    if raw_label == "":
        raise RuntimeError(f"{context} must have a non-empty STEP label")
    return raw_label


def _require_bbox_round_trip(
    *,
    authored: Solid,
    imported: Solid,
    context: str,
) -> None:
    authored_bbox = authored.bounding_box()
    imported_bbox = imported.bounding_box()
    authored_bounds = (
        authored_bbox.min.X,
        authored_bbox.min.Y,
        authored_bbox.min.Z,
        authored_bbox.max.X,
        authored_bbox.max.Y,
        authored_bbox.max.Z,
    )
    imported_bounds = (
        imported_bbox.min.X,
        imported_bbox.min.Y,
        imported_bbox.min.Z,
        imported_bbox.max.X,
        imported_bbox.max.Y,
        imported_bbox.max.Z,
    )
    if not all(
        isclose(actual, expected, rel_tol=0.0, abs_tol=1.0e-6)
        for actual, expected in zip(imported_bounds, authored_bounds, strict=True)
    ):
        raise RuntimeError(
            f"{context} bbox changed during STEP round trip "
            f"(authored={authored_bounds}, imported={imported_bounds})"
        )
    if not isclose(
        imported.volume,
        authored.volume,
        rel_tol=1.0e-8,
        abs_tol=1.0e-8,
    ):
        raise RuntimeError(
            f"{context} volume changed during STEP round trip "
            f"(authored={authored.volume}, imported={imported.volume})"
        )


def _imported_bodies_by_label(
    imported_scene: Shape,
    *,
    expected_labels: frozenset[str],
) -> dict[str, Solid]:
    assert hasattr(imported_scene, "children")
    raw_children = imported_scene.children
    assert isinstance(raw_children, tuple)
    imported_children = raw_children
    if len(imported_children) != len(expected_labels):
        raise RuntimeError(
            f"LGE_EVDD PCB STEP re-import body count mismatch "
            f"(expected={len(expected_labels)}, actual={len(imported_children)})"
        )
    bodies: dict[str, Solid] = {}
    for index, raw_child in enumerate(imported_children):
        if not isinstance(raw_child, Shape):
            raise TypeError(
                f"imported_scene.children[{index}] must be build123d Shape "
                f"(actual={type(raw_child).__name__})"
            )
        solid = _require_one_valid_solid(
            raw_child,
            context=f"imported_scene.children[{index}]",
        )
        label = _shape_label(raw_child, context=f"imported_scene.children[{index}]")
        if label in bodies:
            raise RuntimeError(f"LGE_EVDD PCB STEP contains duplicate body label {label!r}")
        solid.label = label
        bodies[label] = solid
    if frozenset(bodies.keys()) != expected_labels:
        raise RuntimeError(
            f"LGE_EVDD PCB STEP labels changed during re-import "
            f"(expected={sorted(expected_labels)}, actual={sorted(bodies.keys())})"
        )
    return bodies


def export_lgevdd_pcb_step(
    *,
    source_toml_path: Path = DEFAULT_SOURCE_TOML_PATH,
    step_path: Path,
) -> LgeEvddPcbArtifacts:
    spec = load_lgevdd_pcb_spec(source_toml_path)
    primary_geometry = build_lgevdd_primary_planar(spec.primary, fr4=spec.fr4)
    authored_primary = _require_one_valid_solid(
        primary_geometry.shape,
        context=spec.primary.object_id,
    )
    authored_fr4 = _require_one_valid_solid(
        build_lgevdd_fr4(
            spec.fr4,
            center_hole_center_xy=(
                spec.primary.center_xyz[0],
                spec.primary.center_xyz[1],
            ),
            center_hole_size_x_mm=spec.primary.center_keepout_width_x_mm,
            center_hole_size_y_mm=spec.primary.center_keepout_height_y_mm,
            connector_center_xy=primary_geometry.connector_center_xy,
            connector_radius_mm=primary_geometry.connector_radius_mm,
            connector_circle_segments=spec.primary.connector_circle_segments,
        ),
        context=spec.fr4.object_id,
    )

    authored_fr4.label = spec.fr4.object_id
    authored_primary.label = spec.primary.object_id
    scene = bd.Compound(
        children=(authored_fr4, authored_primary),
        label="lgevdd_primary_planar_pcb",
    )
    scene_solids = tuple(scene.solids())
    if len(scene_solids) != 2:
        raise RuntimeError(
            f"LGE_EVDD PCB scene must contain FR4 and primary copper as two solids "
            f"(solid_count={len(scene_solids)})"
        )

    step_path.parent.mkdir(parents=True, exist_ok=True)
    export_ok = bd.export_step(scene, step_path)
    if export_ok is not True:
        raise RuntimeError(f"build123d export_step returned False for LGE_EVDD PCB: {step_path}")
    if not step_path.is_file():
        raise FileNotFoundError(f"LGE_EVDD PCB STEP export did not create a file: {step_path}")
    if step_path.stat().st_size <= 0:
        raise RuntimeError(f"LGE_EVDD PCB STEP export created an empty file: {step_path}")

    imported_scene = bd.import_step(step_path)
    imported_by_label = _imported_bodies_by_label(
        imported_scene,
        expected_labels=frozenset({spec.fr4.object_id, spec.primary.object_id}),
    )
    assert spec.fr4.object_id in imported_by_label
    imported_fr4 = imported_by_label[spec.fr4.object_id]
    assert spec.primary.object_id in imported_by_label
    imported_primary = imported_by_label[spec.primary.object_id]
    _require_bbox_round_trip(
        authored=authored_fr4,
        imported=imported_fr4,
        context=spec.fr4.object_id,
    )
    _require_bbox_round_trip(
        authored=authored_primary,
        imported=imported_primary,
        context=spec.primary.object_id,
    )
    return LgeEvddPcbArtifacts(
        spec=spec,
        primary_geometry=primary_geometry,
        fr4_shape=imported_fr4,
        primary_shape=imported_primary,
        scene_shape=imported_scene,
        step_path=step_path.resolve(),
    )


def export_lgevdd_secondary_step(
    *,
    source_toml_path: Path = DEFAULT_SOURCE_TOML_PATH,
    step_path: Path,
) -> LgeEvddSecondaryArtifacts:
    spec = load_lgevdd_pcb_spec(source_toml_path)
    primary_geometry = build_lgevdd_primary_planar(spec.primary, fr4=spec.fr4)
    secondary_geometry = build_lgevdd_secondary_planar(
        spec.secondary,
        primary=spec.primary,
        fr4=spec.fr4,
        primary_geometry=primary_geometry,
    )
    authored_secondary = tuple(
        _require_one_valid_solid(
            body.shape,
            context=body.object_id,
        )
        for body in secondary_geometry.bodies
    )
    for body, shape in zip(
        secondary_geometry.bodies,
        authored_secondary,
        strict=True,
    ):
        shape.label = body.object_id
    scene = bd.Compound(
        children=authored_secondary,
        label="lgevdd_secondary_planar",
    )
    scene_solids = tuple(scene.solids())
    if len(scene_solids) != spec.secondary.body_count:
        raise RuntimeError(
            f"LGE_EVDD secondary scene solid count mismatch "
            f"(expected={spec.secondary.body_count}, actual={len(scene_solids)})"
        )

    step_path.parent.mkdir(parents=True, exist_ok=True)
    export_ok = bd.export_step(scene, step_path)
    if export_ok is not True:
        raise RuntimeError(
            f"build123d export_step returned False for LGE_EVDD secondary: {step_path}"
        )
    if not step_path.is_file():
        raise FileNotFoundError(
            f"LGE_EVDD secondary STEP export did not create a file: {step_path}"
        )
    if step_path.stat().st_size <= 0:
        raise RuntimeError(
            f"LGE_EVDD secondary STEP export created an empty file: {step_path}"
        )

    imported_scene = bd.import_step(step_path)
    imported_by_label = _imported_bodies_by_label(
        imported_scene,
        expected_labels=frozenset(spec.secondary.body_ids),
    )
    imported_secondary: list[Solid] = []
    for body_id, authored in zip(
        spec.secondary.body_ids,
        authored_secondary,
        strict=True,
    ):
        assert body_id in imported_by_label
        imported = imported_by_label[body_id]
        _require_bbox_round_trip(
            authored=authored,
            imported=imported,
            context=body_id,
        )
        imported_secondary.append(imported)
    if len(imported_secondary) != 2:
        raise RuntimeError(
            f"LGE_EVDD secondary STEP must re-import exactly two bodies "
            f"(actual={len(imported_secondary)})"
        )
    return LgeEvddSecondaryArtifacts(
        spec=spec,
        primary_geometry=primary_geometry,
        secondary_geometry=secondary_geometry,
        secondary_shapes=(imported_secondary[0], imported_secondary[1]),
        scene_shape=imported_scene,
        step_path=step_path.resolve(),
    )


def export_lgevdd_both_step(
    *,
    source_toml_path: Path = DEFAULT_SOURCE_TOML_PATH,
    step_path: Path,
) -> LgeEvddBothArtifacts:
    spec = load_lgevdd_pcb_spec(source_toml_path)
    primary_geometry = build_lgevdd_primary_planar(spec.primary, fr4=spec.fr4)
    secondary_geometry = build_lgevdd_secondary_planar(
        spec.secondary,
        primary=spec.primary,
        fr4=spec.fr4,
        primary_geometry=primary_geometry,
    )
    authored_fr4 = _require_one_valid_solid(
        build_lgevdd_fr4(
            spec.fr4,
            center_hole_center_xy=(
                spec.primary.center_xyz[0],
                spec.primary.center_xyz[1],
            ),
            center_hole_size_x_mm=spec.primary.center_keepout_width_x_mm,
            center_hole_size_y_mm=spec.primary.center_keepout_height_y_mm,
            connector_center_xy=primary_geometry.connector_center_xy,
            connector_radius_mm=primary_geometry.connector_radius_mm,
            connector_circle_segments=spec.primary.connector_circle_segments,
        ),
        context=spec.fr4.object_id,
    )
    authored_primary = _require_one_valid_solid(
        primary_geometry.shape,
        context=spec.primary.object_id,
    )
    authored_secondary = tuple(
        _require_one_valid_solid(
            body.shape,
            context=body.object_id,
        )
        for body in secondary_geometry.bodies
    )
    authored_fr4.label = spec.fr4.object_id
    authored_primary.label = spec.primary.object_id
    for body, shape in zip(
        secondary_geometry.bodies,
        authored_secondary,
        strict=True,
    ):
        shape.label = body.object_id

    authored_by_label = {
        spec.fr4.object_id: authored_fr4,
        spec.primary.object_id: authored_primary,
        spec.secondary.body_ids[0]: authored_secondary[0],
        spec.secondary.body_ids[1]: authored_secondary[1],
    }
    scene = bd.Compound(
        children=(
            authored_fr4,
            authored_primary,
            authored_secondary[0],
            authored_secondary[1],
        ),
        label="lgevdd_primary_secondary_planar",
    )
    scene_solids = tuple(scene.solids())
    if len(scene_solids) != 4:
        raise RuntimeError(
            f"LGE_EVDD both scene must contain FR4, primary, and two secondary solids "
            f"(solid_count={len(scene_solids)})"
        )

    step_path.parent.mkdir(parents=True, exist_ok=True)
    export_ok = bd.export_step(scene, step_path)
    if export_ok is not True:
        raise RuntimeError(
            f"build123d export_step returned False for LGE_EVDD both scene: {step_path}"
        )
    if not step_path.is_file():
        raise FileNotFoundError(
            f"LGE_EVDD both STEP export did not create a file: {step_path}"
        )
    if step_path.stat().st_size <= 0:
        raise RuntimeError(
            f"LGE_EVDD both STEP export created an empty file: {step_path}"
        )

    imported_scene = bd.import_step(step_path)
    imported_by_label = _imported_bodies_by_label(
        imported_scene,
        expected_labels=frozenset(authored_by_label.keys()),
    )
    for label, authored in authored_by_label.items():
        assert label in imported_by_label
        _require_bbox_round_trip(
            authored=authored,
            imported=imported_by_label[label],
            context=label,
        )
    return LgeEvddBothArtifacts(
        spec=spec,
        primary_geometry=primary_geometry,
        secondary_geometry=secondary_geometry,
        fr4_shape=imported_by_label[spec.fr4.object_id],
        primary_shape=imported_by_label[spec.primary.object_id],
        secondary_shapes=(
            imported_by_label[spec.secondary.body_ids[0]],
            imported_by_label[spec.secondary.body_ids[1]],
        ),
        scene_shape=imported_scene,
        step_path=step_path.resolve(),
    )


__all__ = [
    "DEFAULT_BOTH_STEP_NAME",
    "DEFAULT_SECONDARY_STEP_NAME",
    "DEFAULT_STEP_NAME",
    "LgeEvddBothArtifacts",
    "LgeEvddPcbArtifacts",
    "LgeEvddSecondaryArtifacts",
    "export_lgevdd_both_step",
    "export_lgevdd_pcb_step",
    "export_lgevdd_secondary_step",
]
