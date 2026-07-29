from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from typing import cast

import build123d as bd
from build123d.topology import Shape, Solid

from peetsfea.lgevdd_planar import (
    Point2,
    axis_aligned_trace_footprint,
    canonical_rectangular_spiral_centerline,
    extrude_planar_footprint,
    single_turn_rectangular_loop_centerline,
)
from peetsfea.lgevdd_primary import LgeEvddPrimaryGeometry
from peetsfea.lgevdd_spec import (
    LgeEvddFr4Spec,
    LgeEvddPrimaryPlanarSpec,
    LgeEvddSecondaryPlanarSpec,
)

Point3 = tuple[float, float, float]


@dataclass(frozen=True)
class LgeEvddSecondaryLayerGeometry:
    turns: int
    centerline_xy: tuple[Point2, ...]
    z_min_mm: float
    z_max_mm: float


@dataclass(frozen=True)
class LgeEvddSecondaryBodyGeometry:
    object_id: str
    layers: tuple[LgeEvddSecondaryLayerGeometry, ...]
    bridge_required: bool
    bridge_center_xy: Point2
    terminal_start_xyz: Point3
    terminal_end_xyz: Point3
    shape: Solid


@dataclass(frozen=True)
class LgeEvddSecondaryGeometry:
    first_layer_turns: int
    second_layer_turns: int
    bodies: tuple[LgeEvddSecondaryBodyGeometry, LgeEvddSecondaryBodyGeometry]


@dataclass(frozen=True)
class _LayerPlacement:
    turns: int
    centerline_xy: tuple[Point2, ...]
    z_min_mm: float


def _spiral_centerline(
    *,
    secondary: LgeEvddSecondaryPlanarSpec,
    primary: LgeEvddPrimaryPlanarSpec,
    turns: int,
    mirror_y: bool,
) -> tuple[Point2, ...]:
    return canonical_rectangular_spiral_centerline(
        center_xy=(primary.center_xyz[0], primary.center_xyz[1]),
        center_keepout_width_x_mm=primary.center_keepout_width_x_mm,
        center_keepout_height_y_mm=primary.center_keepout_height_y_mm,
        lead_extension_x_mm=secondary.lead_extension_x_mm,
        trace_width_mm=secondary.trace_width_mm,
        inner_clearance_x_mm=secondary.inner_clearance_x_mm,
        inner_clearance_y_mm=secondary.inner_clearance_y_mm,
        turn_gap_x_mm=secondary.turn_gap_x_mm,
        turn_gap_y_mm=secondary.turn_gap_y_mm,
        turns=turns,
        lead_side="negative_x",
        mirror_y=mirror_y,
    )


def _single_turn_centerline(
    *,
    secondary: LgeEvddSecondaryPlanarSpec,
    primary: LgeEvddPrimaryPlanarSpec,
) -> tuple[Point2, ...]:
    return single_turn_rectangular_loop_centerline(
        center_xy=(primary.center_xyz[0], primary.center_xyz[1]),
        center_keepout_width_x_mm=primary.center_keepout_width_x_mm,
        center_keepout_height_y_mm=primary.center_keepout_height_y_mm,
        lead_extension_x_mm=secondary.lead_extension_x_mm,
        trace_width_mm=secondary.trace_width_mm,
        inner_clearance_x_mm=secondary.inner_clearance_x_mm,
        inner_clearance_y_mm=secondary.inner_clearance_y_mm,
        lead_side="negative_x",
    )


def _require_one_valid_solid(shape: Shape, *, context: str) -> Solid:
    solids = tuple(shape.solids())
    if len(solids) != 1:
        raise RuntimeError(
            f"{context} must contain exactly one connected solid "
            f"(solid_count={len(solids)})"
        )
    solid = cast(Solid, solids[0])
    assert hasattr(solid, "is_valid")
    solid_is_valid = solid.is_valid
    assert isinstance(solid_is_valid, bool)
    if solid_is_valid is not True:
        raise RuntimeError(f"{context} is not a valid solid")
    return solid


def _build_secondary_body(
    *,
    object_id: str,
    placements: tuple[_LayerPlacement, ...],
    trace_width_mm: float,
    copper_thickness_mm: float,
) -> LgeEvddSecondaryBodyGeometry:
    if len(placements) not in (1, 2):
        raise ValueError(
            f"{object_id} requires one or two populated layers "
            f"(actual={len(placements)})"
        )
    layer_shapes: list[Solid] = []
    layer_geometries: list[LgeEvddSecondaryLayerGeometry] = []
    for index, placement in enumerate(placements):
        context = f"{object_id}.layer[{index}]"
        footprint = axis_aligned_trace_footprint(
            points=placement.centerline_xy,
            trace_width_mm=trace_width_mm,
            context=context,
        )
        layer_shape = extrude_planar_footprint(
            footprint=footprint,
            z_min_mm=placement.z_min_mm,
            thickness_mm=copper_thickness_mm,
            context=context,
        )
        layer_shapes.append(layer_shape)
        layer_geometries.append(
            LgeEvddSecondaryLayerGeometry(
                turns=placement.turns,
                centerline_xy=placement.centerline_xy,
                z_min_mm=placement.z_min_mm,
                z_max_mm=placement.z_min_mm + copper_thickness_mm,
            )
        )

    bridge_required = len(placements) == 2
    bridge_center = placements[0].centerline_xy[-1]
    if bridge_required:
        if placements[1].centerline_xy[-1] != bridge_center:
            raise RuntimeError(
                f"{object_id} populated layers must share one bridge center "
                f"(first={bridge_center}, second={placements[1].centerline_xy[-1]})"
            )
        bridge_z_min = min(placement.z_min_mm for placement in placements)
        bridge_z_max = max(
            placement.z_min_mm + copper_thickness_mm
            for placement in placements
        )
        bridge = bd.Box(
            trace_width_mm,
            copper_thickness_mm,
            bridge_z_max - bridge_z_min,
            align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.CENTER),
        ).moved(
            bd.Location(
                (
                    bridge_center[0],
                    bridge_center[1],
                    (bridge_z_min + bridge_z_max) / 2.0,
                )
            )
        )
        fused = layer_shapes[0].fuse(layer_shapes[1], bridge)
        body_shape = _require_one_valid_solid(fused, context=object_id)
        terminal_end_xy = placements[1].centerline_xy[0]
        terminal_end_z = placements[1].z_min_mm + copper_thickness_mm / 2.0
    else:
        body_shape = _require_one_valid_solid(layer_shapes[0], context=object_id)
        terminal_end_xy = placements[0].centerline_xy[-1]
        terminal_end_z = placements[0].z_min_mm + copper_thickness_mm / 2.0

    terminal_start_xy = placements[0].centerline_xy[0]
    terminal_start_z = placements[0].z_min_mm + copper_thickness_mm / 2.0
    body_shape.label = object_id
    return LgeEvddSecondaryBodyGeometry(
        object_id=object_id,
        layers=tuple(layer_geometries),
        bridge_required=bridge_required,
        bridge_center_xy=bridge_center,
        terminal_start_xyz=(
            terminal_start_xy[0],
            terminal_start_xy[1],
            terminal_start_z,
        ),
        terminal_end_xyz=(
            terminal_end_xy[0],
            terminal_end_xy[1],
            terminal_end_z,
        ),
        shape=body_shape,
    )


def _require_xy_within_fr4(
    *,
    body: LgeEvddSecondaryBodyGeometry,
    fr4: LgeEvddFr4Spec,
) -> None:
    fr4_min_x = fr4.center_xyz[0] - fr4.size_x_mm / 2.0
    fr4_max_x = fr4.center_xyz[0] + fr4.size_x_mm / 2.0
    fr4_min_y = fr4.center_xyz[1] - fr4.size_y_mm / 2.0
    fr4_max_y = fr4.center_xyz[1] + fr4.size_y_mm / 2.0
    bounds = body.shape.bounding_box()
    if not (
        fr4_min_x <= bounds.min.X
        and bounds.max.X <= fr4_max_x
        and fr4_min_y <= bounds.min.Y
        and bounds.max.Y <= fr4_max_y
    ):
        raise ValueError(
            f"{body.object_id} XY bounds must remain within the FR4 outline "
            f"(fr4={(fr4_min_x, fr4_min_y, fr4_max_x, fr4_max_y)}, "
            f"secondary={(bounds.min.X, bounds.min.Y, bounds.max.X, bounds.max.Y)})"
        )


def _require_positive_clearance(
    *,
    first: Solid,
    second: Solid,
    context: str,
) -> None:
    clearance = first.distance_to(second)
    if clearance <= 1.0e-9:
        raise RuntimeError(
            f"{context} requires positive geometric clearance "
            f"(actual={clearance})"
        )


def _require_symmetric_bodies(
    *,
    upper: LgeEvddSecondaryBodyGeometry,
    lower: LgeEvddSecondaryBodyGeometry,
    symmetry_z_mm: float,
) -> None:
    upper_bounds = upper.shape.bounding_box()
    lower_bounds = lower.shape.bounding_box()
    paired_values = (
        (upper_bounds.min.X, lower_bounds.min.X, "min_x"),
        (upper_bounds.max.X, lower_bounds.max.X, "max_x"),
        (upper_bounds.min.Y, lower_bounds.min.Y, "min_y"),
        (upper_bounds.max.Y, lower_bounds.max.Y, "max_y"),
        (
            upper_bounds.min.Z - symmetry_z_mm,
            symmetry_z_mm - lower_bounds.max.Z,
            "inner_z",
        ),
        (
            upper_bounds.max.Z - symmetry_z_mm,
            symmetry_z_mm - lower_bounds.min.Z,
            "outer_z",
        ),
    )
    for upper_value, lower_value, coordinate in paired_values:
        if not isclose(
            upper_value,
            lower_value,
            rel_tol=0.0,
            abs_tol=1.0e-9,
        ):
            raise RuntimeError(
                f"secondary bodies must be symmetric at {coordinate} "
                f"(upper={upper_value}, lower={lower_value})"
            )


def build_lgevdd_secondary_planar(
    secondary: LgeEvddSecondaryPlanarSpec,
    *,
    primary: LgeEvddPrimaryPlanarSpec,
    fr4: LgeEvddFr4Spec,
    primary_geometry: LgeEvddPrimaryGeometry,
) -> LgeEvddSecondaryGeometry:
    if secondary.body_count != 2:
        raise ValueError(
            f"secondary builder requires exactly two half-winding bodies "
            f"(actual={secondary.body_count})"
        )
    if secondary.layer_count != 2:
        raise ValueError(
            f"secondary builder requires exactly two available layers "
            f"(actual={secondary.layer_count})"
        )
    if secondary.turns < 1:
        raise ValueError(
            f"secondary builder requires at least one turn "
            f"(actual={secondary.turns})"
        )

    first_turns = (secondary.turns + 1) // 2
    second_turns = secondary.turns // 2
    thickness = secondary.copper_thickness_mm
    preg = secondary.secondary_preg_mm

    if second_turns == 0:
        first_points = _single_turn_centerline(
            secondary=secondary,
            primary=primary,
        )
        upper_placements = (
            _LayerPlacement(
                turns=first_turns,
                centerline_xy=first_points,
                z_min_mm=primary_geometry.top_z_max_mm + preg,
            ),
        )
        lower_placements = (
            _LayerPlacement(
                turns=first_turns,
                centerline_xy=first_points,
                z_min_mm=primary_geometry.bottom_z_min_mm - preg - thickness,
            ),
        )
    else:
        first_points = _spiral_centerline(
            secondary=secondary,
            primary=primary,
            turns=first_turns,
            mirror_y=False,
        )
        second_points = _spiral_centerline(
            secondary=secondary,
            primary=primary,
            turns=second_turns,
            mirror_y=True,
        )
        upper_near_z_min = primary_geometry.top_z_max_mm + preg
        upper_far_z_min = upper_near_z_min + thickness + preg
        lower_near_z_min = primary_geometry.bottom_z_min_mm - preg - thickness
        lower_far_z_min = lower_near_z_min - preg - thickness
        upper_placements = (
            _LayerPlacement(
                turns=first_turns,
                centerline_xy=first_points,
                z_min_mm=upper_far_z_min,
            ),
            _LayerPlacement(
                turns=second_turns,
                centerline_xy=second_points,
                z_min_mm=upper_near_z_min,
            ),
        )
        lower_placements = (
            _LayerPlacement(
                turns=first_turns,
                centerline_xy=first_points,
                z_min_mm=lower_near_z_min,
            ),
            _LayerPlacement(
                turns=second_turns,
                centerline_xy=second_points,
                z_min_mm=lower_far_z_min,
            ),
        )

    upper = _build_secondary_body(
        object_id=secondary.body_ids[0],
        placements=upper_placements,
        trace_width_mm=secondary.trace_width_mm,
        copper_thickness_mm=thickness,
    )
    lower = _build_secondary_body(
        object_id=secondary.body_ids[1],
        placements=lower_placements,
        trace_width_mm=secondary.trace_width_mm,
        copper_thickness_mm=thickness,
    )
    _require_xy_within_fr4(body=upper, fr4=fr4)
    _require_xy_within_fr4(body=lower, fr4=fr4)
    _require_positive_clearance(
        first=primary_geometry.shape,
        second=upper.shape,
        context="primary-to-upper-secondary",
    )
    _require_positive_clearance(
        first=primary_geometry.shape,
        second=lower.shape,
        context="primary-to-lower-secondary",
    )
    _require_positive_clearance(
        first=upper.shape,
        second=lower.shape,
        context="upper-to-lower-secondary",
    )
    _require_symmetric_bodies(
        upper=upper,
        lower=lower,
        symmetry_z_mm=fr4.center_xyz[2],
    )
    return LgeEvddSecondaryGeometry(
        first_layer_turns=first_turns,
        second_layer_turns=second_turns,
        bodies=(upper, lower),
    )


__all__ = [
    "LgeEvddSecondaryBodyGeometry",
    "LgeEvddSecondaryGeometry",
    "LgeEvddSecondaryLayerGeometry",
    "Point3",
    "build_lgevdd_secondary_planar",
]
