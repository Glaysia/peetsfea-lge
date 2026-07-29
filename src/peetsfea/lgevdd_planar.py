from __future__ import annotations

from math import isclose
from typing import Literal, cast

import build123d as bd
from build123d.topology import Face, Solid

Point2 = tuple[float, float]
LeadSide = Literal["negative_x", "positive_x"]


def canonical_rectangular_spiral_centerline(
    *,
    center_xy: Point2,
    center_keepout_width_x_mm: float,
    center_keepout_height_y_mm: float,
    lead_extension_x_mm: float,
    trace_width_mm: float,
    inner_clearance_x_mm: float,
    inner_clearance_y_mm: float,
    turn_gap_x_mm: float,
    turn_gap_y_mm: float,
    turns: int,
    lead_side: LeadSide,
    mirror_y: bool,
) -> tuple[Point2, ...]:
    if turns < 1:
        raise ValueError(f"rectangular spiral requires at least one turn (actual={turns})")

    half_keepout_x = center_keepout_width_x_mm / 2.0
    half_keepout_y = center_keepout_height_y_mm / 2.0
    half_trace = trace_width_mm / 2.0
    inner_x = half_keepout_x + inner_clearance_x_mm + half_trace
    inner_y = half_keepout_y + inner_clearance_y_mm + half_trace
    pitch_x = trace_width_mm + turn_gap_x_mm
    pitch_y = trace_width_mm + turn_gap_y_mm
    outer_index = turns - 1
    outer_y = inner_y + outer_index * pitch_y
    lead_end_x = half_keepout_x + lead_extension_x_mm

    local_points: list[Point2] = [(lead_end_x, -outer_y)]
    for turn_index in range(outer_index, -1, -1):
        turn_x = inner_x + turn_index * pitch_x
        turn_y = inner_y + turn_index * pitch_y
        local_points.extend(
            (
                (-turn_x, -turn_y),
                (-turn_x, turn_y),
                (turn_x, turn_y),
            )
        )
        if turn_index == 0:
            local_points.append((turn_x, 0.0))
        else:
            next_inner_y = inner_y + (turn_index - 1) * pitch_y
            local_points.append((turn_x, -next_inner_y))

    x_direction = 1.0 if lead_side == "positive_x" else -1.0
    y_direction = -1.0 if mirror_y else 1.0
    transformed = tuple(
        (
            center_xy[0] + x_direction * point_x,
            center_xy[1] + y_direction * point_y,
        )
        for point_x, point_y in local_points
    )
    if len(transformed) < 4:
        raise RuntimeError(
            f"rectangular spiral centerline must contain at least four points "
            f"(turns={turns}, point_count={len(transformed)})"
        )
    return transformed


def single_turn_rectangular_loop_centerline(
    *,
    center_xy: Point2,
    center_keepout_width_x_mm: float,
    center_keepout_height_y_mm: float,
    lead_extension_x_mm: float,
    trace_width_mm: float,
    inner_clearance_x_mm: float,
    inner_clearance_y_mm: float,
    lead_side: LeadSide,
) -> tuple[Point2, ...]:
    half_keepout_x = center_keepout_width_x_mm / 2.0
    half_keepout_y = center_keepout_height_y_mm / 2.0
    half_trace = trace_width_mm / 2.0
    turn_x = half_keepout_x + inner_clearance_x_mm + half_trace
    turn_y = half_keepout_y + inner_clearance_y_mm + half_trace
    lead_end_x = half_keepout_x + lead_extension_x_mm
    local_points: tuple[Point2, ...] = (
        (lead_end_x, -turn_y),
        (turn_x, -turn_y),
        (-turn_x, -turn_y),
        (-turn_x, turn_y),
        (turn_x, turn_y),
        (lead_end_x, turn_y),
    )
    x_direction = 1.0 if lead_side == "positive_x" else -1.0
    return tuple(
        (
            center_xy[0] + x_direction * point_x,
            center_xy[1] + point_y,
        )
        for point_x, point_y in local_points
    )


def _segment_face(
    *,
    start: Point2,
    end: Point2,
    trace_width_mm: float,
    context: str,
) -> Face:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    horizontal = isclose(dy, 0.0, rel_tol=0.0, abs_tol=1.0e-12)
    vertical = isclose(dx, 0.0, rel_tol=0.0, abs_tol=1.0e-12)
    if horizontal == vertical:
        raise ValueError(
            f"{context} must be one non-zero axis-aligned segment "
            f"(start={start}, end={end})"
        )
    if horizontal:
        length = abs(dx)
        face = bd.Rectangle(length, trace_width_mm).moved(
            bd.Location(((start[0] + end[0]) / 2.0, start[1], 0.0))
        )
    else:
        length = abs(dy)
        face = bd.Rectangle(trace_width_mm, length).moved(
            bd.Location((start[0], (start[1] + end[1]) / 2.0, 0.0))
        )
    if length <= 0.0:
        raise ValueError(f"{context} length must be positive (actual={length})")
    return cast(Face, face)


def axis_aligned_trace_footprint(
    *,
    points: tuple[Point2, ...],
    trace_width_mm: float,
    context: str,
) -> Face:
    segment_faces = tuple(
        _segment_face(
            start=start,
            end=end,
            trace_width_mm=trace_width_mm,
            context=f"{context}.segment[{index}]",
        )
        for index, (start, end) in enumerate(zip(points, points[1:]))
    )
    if len(segment_faces) == 0:
        raise RuntimeError(f"{context} did not generate any 2D trace segments")
    corner_faces = tuple(
        cast(
            Face,
            bd.Rectangle(trace_width_mm, trace_width_mm).moved(
                bd.Location((corner_x, corner_y, 0.0))
            ),
        )
        for corner_x, corner_y in points[1:-1]
    )
    trace_faces = segment_faces + corner_faces
    fused = trace_faces[0].fuse(*trace_faces[1:])
    faces = tuple(fused.faces())
    if len(faces) != 1:
        raise RuntimeError(
            f"{context} footprint must fuse into exactly one face "
            f"(face_count={len(faces)})"
        )
    footprint = cast(Face, faces[0])
    assert hasattr(footprint, "is_valid")
    footprint_is_valid = footprint.is_valid
    assert isinstance(footprint_is_valid, bool)
    if footprint_is_valid is not True:
        raise RuntimeError(f"{context} footprint is not a valid face")
    return footprint


def extrude_planar_footprint(
    *,
    footprint: Face,
    z_min_mm: float,
    thickness_mm: float,
    context: str,
) -> Solid:
    extruded = bd.extrude(footprint, amount=thickness_mm).moved(
        bd.Location((0.0, 0.0, z_min_mm))
    )
    solids = tuple(extruded.solids())
    if len(solids) != 1:
        raise RuntimeError(
            f"{context} must extrude into exactly one solid "
            f"(solid_count={len(solids)})"
        )
    layer = cast(Solid, solids[0])
    assert hasattr(layer, "is_valid")
    layer_is_valid = layer.is_valid
    assert isinstance(layer_is_valid, bool)
    if layer_is_valid is not True:
        raise RuntimeError(f"{context} is not a valid extruded solid")
    return layer


__all__ = [
    "LeadSide",
    "Point2",
    "axis_aligned_trace_footprint",
    "canonical_rectangular_spiral_centerline",
    "extrude_planar_footprint",
    "single_turn_rectangular_loop_centerline",
]
