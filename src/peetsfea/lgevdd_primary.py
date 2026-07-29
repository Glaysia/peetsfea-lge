from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import build123d as bd
from build123d.topology import Solid

from peetsfea.lgevdd_planar import (
    Point2,
    axis_aligned_trace_footprint,
    canonical_rectangular_spiral_centerline,
    extrude_planar_footprint,
)
from peetsfea.lgevdd_spec import LgeEvddFr4Spec, LgeEvddPrimaryPlanarSpec


@dataclass(frozen=True)
class LgeEvddPrimaryGeometry:
    top_turns: int
    bottom_turns: int
    top_centerline_xy: tuple[Point2, ...]
    bottom_centerline_xy: tuple[Point2, ...]
    connector_center_xy: Point2
    connector_radius_mm: float
    top_z_min_mm: float
    top_z_max_mm: float
    bottom_z_min_mm: float
    bottom_z_max_mm: float
    shape: Solid


def _canonical_layer_centerline(
    spec: LgeEvddPrimaryPlanarSpec,
    *,
    turns: int,
    mirror_y: bool,
) -> tuple[Point2, ...]:
    if turns < 1:
        raise ValueError(f"canonical layer requires at least one turn (actual={turns})")

    return canonical_rectangular_spiral_centerline(
        center_xy=(spec.center_xyz[0], spec.center_xyz[1]),
        center_keepout_width_x_mm=spec.center_keepout_width_x_mm,
        center_keepout_height_y_mm=spec.center_keepout_height_y_mm,
        lead_extension_x_mm=spec.lead_extension_x_mm,
        trace_width_mm=spec.trace_width_mm,
        inner_clearance_x_mm=spec.inner_clearance_x_mm,
        inner_clearance_y_mm=spec.inner_clearance_y_mm,
        turn_gap_x_mm=spec.turn_gap_x_mm,
        turn_gap_y_mm=spec.turn_gap_y_mm,
        turns=turns,
        lead_side="positive_x",
        mirror_y=mirror_y,
    )


def build_lgevdd_primary_planar(
    primary: LgeEvddPrimaryPlanarSpec,
    *,
    fr4: LgeEvddFr4Spec,
) -> LgeEvddPrimaryGeometry:
    if primary.layer_count != 2:
        raise ValueError(
            f"primary planar builder requires exactly two layers "
            f"(actual={primary.layer_count})"
        )
    top_turns = (primary.turns + 1) // 2
    bottom_turns = primary.turns // 2
    if bottom_turns < 1:
        raise ValueError(
            f"primary planar builder requires at least one turn on each layer "
            f"(total_turns={primary.turns})"
        )

    top_points = _canonical_layer_centerline(
        primary,
        turns=top_turns,
        mirror_y=False,
    )
    bottom_points = _canonical_layer_centerline(
        primary,
        turns=bottom_turns,
        mirror_y=True,
    )
    top_footprint = axis_aligned_trace_footprint(
        points=top_points,
        trace_width_mm=primary.trace_width_mm,
        context="primary.top",
    )
    bottom_footprint = axis_aligned_trace_footprint(
        points=bottom_points,
        trace_width_mm=primary.trace_width_mm,
        context="primary.bottom",
    )

    fr4_z_min = fr4.center_xyz[2] - fr4.thickness_mm / 2.0
    fr4_z_max = fr4.center_xyz[2] + fr4.thickness_mm / 2.0
    top_z_min = fr4_z_max
    top_z_max = top_z_min + primary.copper_thickness_mm
    bottom_z_max = fr4_z_min
    bottom_z_min = bottom_z_max - primary.copper_thickness_mm
    top_shape = extrude_planar_footprint(
        footprint=top_footprint,
        z_min_mm=top_z_min,
        thickness_mm=primary.copper_thickness_mm,
        context="primary.top",
    )
    bottom_shape = extrude_planar_footprint(
        footprint=bottom_footprint,
        z_min_mm=bottom_z_min,
        thickness_mm=primary.copper_thickness_mm,
        context="primary.bottom",
    )

    connector_center = top_points[-1]
    if connector_center != bottom_points[-1]:
        raise RuntimeError(
            f"top and bottom canonical spirals must share one connector center "
            f"(top={connector_center}, bottom={bottom_points[-1]})"
        )
    connector_radius = (
        primary.trace_width_mm
        * primary.connector_diameter_ratio_to_trace_width
        / 2.0
    )
    connector_face = bd.RegularPolygon(
        connector_radius,
        primary.connector_circle_segments,
    ).moved(
        bd.Location(
            (
                connector_center[0],
                connector_center[1],
                bottom_z_min,
            )
        )
    )
    connector = bd.extrude(
        connector_face,
        amount=top_z_max - bottom_z_min,
    )
    connector_solids = tuple(connector.solids())
    if len(connector_solids) != 1:
        raise RuntimeError(
            f"primary connector must contain exactly one solid "
            f"(solid_count={len(connector_solids)})"
        )

    fused = top_shape.fuse(bottom_shape, connector)
    fused_solids = tuple(fused.solids())
    if len(fused_solids) != 1:
        raise RuntimeError(
            f"primary top, bottom, and connector must fuse into one solid "
            f"(solid_count={len(fused_solids)})"
        )
    primary_shape = cast(Solid, fused_solids[0])
    assert hasattr(primary_shape, "is_valid")
    primary_is_valid = primary_shape.is_valid
    assert isinstance(primary_is_valid, bool)
    if primary_is_valid is not True:
        raise RuntimeError("fused primary planar copper is not a valid solid")
    primary_shape.label = primary.object_id
    return LgeEvddPrimaryGeometry(
        top_turns=top_turns,
        bottom_turns=bottom_turns,
        top_centerline_xy=top_points,
        bottom_centerline_xy=bottom_points,
        connector_center_xy=connector_center,
        connector_radius_mm=connector_radius,
        top_z_min_mm=top_z_min,
        top_z_max_mm=top_z_max,
        bottom_z_min_mm=bottom_z_min,
        bottom_z_max_mm=bottom_z_max,
        shape=primary_shape,
    )


__all__ = [
    "LgeEvddPrimaryGeometry",
    "Point2",
    "build_lgevdd_primary_planar",
]
