from __future__ import annotations

from typing import cast

import build123d as bd
from build123d.topology import Solid

from peetsfea.lgevdd_spec import LgeEvddFr4Spec

Point2 = tuple[float, float]


def build_lgevdd_fr4(
    spec: LgeEvddFr4Spec,
    *,
    center_hole_center_xy: Point2,
    center_hole_size_x_mm: float,
    center_hole_size_y_mm: float,
    connector_center_xy: Point2,
    connector_radius_mm: float,
    connector_circle_segments: int,
) -> Solid:
    if center_hole_size_x_mm <= 0.0 or center_hole_size_y_mm <= 0.0:
        raise ValueError(
            f"FR4 center hole dimensions must be positive "
            f"(size_x={center_hole_size_x_mm}, size_y={center_hole_size_y_mm})"
        )
    board_min_x = spec.center_xyz[0] - spec.size_x_mm / 2.0
    board_max_x = spec.center_xyz[0] + spec.size_x_mm / 2.0
    board_min_y = spec.center_xyz[1] - spec.size_y_mm / 2.0
    board_max_y = spec.center_xyz[1] + spec.size_y_mm / 2.0
    hole_min_x = center_hole_center_xy[0] - center_hole_size_x_mm / 2.0
    hole_max_x = center_hole_center_xy[0] + center_hole_size_x_mm / 2.0
    hole_min_y = center_hole_center_xy[1] - center_hole_size_y_mm / 2.0
    hole_max_y = center_hole_center_xy[1] + center_hole_size_y_mm / 2.0
    if not (
        board_min_x < hole_min_x
        and hole_max_x < board_max_x
        and board_min_y < hole_min_y
        and hole_max_y < board_max_y
    ):
        raise ValueError(
            f"FR4 center hole must remain strictly inside the board "
            f"(board_bounds={(board_min_x, board_min_y, board_max_x, board_max_y)}, "
            f"hole_bounds={(hole_min_x, hole_min_y, hole_max_x, hole_max_y)})"
        )
    if connector_radius_mm <= 0.0:
        raise ValueError(
            f"FR4 connector hole radius must be positive (actual={connector_radius_mm})"
        )
    board = bd.Box(
        spec.size_x_mm,
        spec.size_y_mm,
        spec.thickness_mm,
        align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.CENTER),
    ).moved(bd.Location(spec.center_xyz))
    center_hole = bd.Box(
        center_hole_size_x_mm,
        center_hole_size_y_mm,
        spec.thickness_mm * 2.0,
        align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.CENTER),
    ).moved(
        bd.Location(
            (
                center_hole_center_xy[0],
                center_hole_center_xy[1],
                spec.center_xyz[2],
            )
        )
    )
    if connector_circle_segments < 3:
        raise ValueError(
            f"FR4 connector hole requires at least three segments "
            f"(actual={connector_circle_segments})"
        )
    hole_face = bd.RegularPolygon(
        connector_radius_mm,
        connector_circle_segments,
    ).moved(
        bd.Location(
            (
                connector_center_xy[0],
                connector_center_xy[1],
                spec.center_xyz[2] - spec.thickness_mm,
            )
        )
    )
    hole = bd.extrude(
        hole_face,
        amount=spec.thickness_mm * 2.0,
    )
    cut_board = board.cut(center_hole, hole)
    solids = tuple(cut_board.solids())
    if len(solids) != 1:
        raise RuntimeError(
            f"{spec.object_id} with center and connector holes must contain exactly one solid "
            f"(solid_count={len(solids)})"
        )
    fr4 = cast(Solid, solids[0])
    assert hasattr(fr4, "is_valid")
    is_valid = fr4.is_valid
    assert isinstance(is_valid, bool)
    if is_valid is not True:
        raise RuntimeError(
            f"{spec.object_id} is not a valid solid after center and connector hole cuts"
        )
    fr4.label = spec.object_id
    return fr4


__all__ = ["Point2", "build_lgevdd_fr4"]
