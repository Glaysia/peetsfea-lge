from __future__ import annotations

import json
from dataclasses import dataclass
from functools import reduce
from itertools import chain, pairwise, starmap
from math import ceil, floor, gcd, sqrt
from pathlib import Path
from typing import Iterable, Iterator, Never, TypeAlias, TypeVar, cast

import cadquery as cq
from ocp_vscode import Camera, show


Point2D: TypeAlias = tuple[float, float]
Point3D: TypeAlias = tuple[float, float, float]
Vector3D: TypeAlias = tuple[float, float, float]
ActionValue: TypeAlias = str | int | float | bool | None | tuple["ActionValue", ...]
ActionParam: TypeAlias = tuple[str, ActionValue]

T = TypeVar("T")


@dataclass(frozen=True)
class FixedDimensions:
    FR4_THICKNESS_MM: float = 0.24          # [false, 0.24, 0.24, 1]    [is_integer, min, max, count]
    COPPER_THICKNESS_MM: float = 0.07       # [false, 0.07, 0.07, 1]
    PORT_LENGTH_MM: float = 2.0             # [false, 2.0, 2.0, 1]
    PORT_LANDING_PAD_MM: float = 5.5        # [false, 5.5, 5.5, 1]
    PORT_LANDING_DROP_MM: float = 0.24      # [false, 0.24, 0.24, 1]
    PORT_LANDING_OVERLAP_MM: float = 0.01   # [false, 0.01, 0.01, 1]
    WIDTH_MAX_MM: float = 120 * 4           # [false, 480, 480, 1]
    HEIGHT_MAX_MM: float = 60 * 4           # [false, 240, 240, 1]


@dataclass(frozen=True)
class CommonCoilParameters:
    WIDTH_RATIO: float = 0.6                # [false, 0.0555556, 1.0, 500]
    HEIGHT_RATIO: float = 0.6               # [false, 0.0555556, 1.0, 500]
    IS_SSW_ENABLED: bool = True             # [true, 1, 1, 1]    deprecated
    TURN_N_INT: int = 3                     # [true, 1, 10, 10]  
    GAP_RATIO: float = 0.24                 # [false, 0.1, 0.9, 50]  
    VOID_AREA_RATIO: float = 0.5            # [false, 0.1, 0.9, 50]
    VOID_PROFILE: int = 1                   # [true, 0, 1, 2]   [0: rectangular void, 1: scaled void]
    SERIAL_COIL_N: int = 2                  # [false, 1, 1, 1] deprecated
    SERIAL_COIL_GAP_RATIO: float = 0.5      # [false, 0, 0, 0] deprecated
    SERIAL_COIL_AXIS: int = 0               # [true, 0, 0, 1]  deprecated

    def width_mm(self, fixed: FixedDimensions) -> float:
        return fixed.WIDTH_MAX_MM * self.WIDTH_RATIO

    def height_mm(self, fixed: FixedDimensions) -> float:
        return fixed.HEIGHT_MAX_MM * self.HEIGHT_RATIO

    @property
    def pcb_n(self) -> int:
        return 2 if self.IS_SSW_ENABLED else 1


@dataclass(frozen=True)
class SpiralCoilParameters: # deprecated
    NO_SSW_QTURN_START_INT: int = 0
    NO_SSW_QTURN_N_INT: int = 0


@dataclass(frozen=True)
class SSWCoilParameters:
    PCB_GAP_MM: float = 3.0     # [false, 1.0, 10.0, 50]
    TWIST_FACTOR: int = 2       # [true, 1, 10, 10] 

    def turn(self, common: CommonCoilParameters) -> int:
        return common.TURN_N_INT if common.IS_SSW_ENABLED else 0

    def active_twist_factor(self, common: CommonCoilParameters) -> int:
        return self.TWIST_FACTOR if common.IS_SSW_ENABLED else 0

    def gap_ratio(self, common: CommonCoilParameters) -> float:
        return common.GAP_RATIO if common.IS_SSW_ENABLED else 0.0


@dataclass(frozen=True)
class CoilFrame:
    width_mm: float
    height_mm: float
    origin_xy_mm: Point2D = (0.0, 0.0)


@dataclass(frozen=True)
class SideSpec:
    name: str
    u_start_mm: float
    length_mm: float
    origin_xy_mm: Point2D
    tangent_xy: Point2D
    normal_xy: Point2D


@dataclass(frozen=True)
class FaceSpec:
    name: str
    start_mm: float
    end_mm: float


@dataclass(frozen=True)
class ColorSpec:
    red: float
    green: float
    blue: float
    alpha: float


@dataclass(frozen=True)
class RuntimeConfig:
    fixed: FixedDimensions
    common: CommonCoilParameters
    spiral: SpiralCoilParameters
    ssw: SSWCoilParameters
    output_step: str = "pcb_stack.step"
    output_token_toml: str = "coil_making_token.toml"


@dataclass(frozen=True)
class BoxToken:
    name: str
    center_xy_mm: Point2D
    width_mm: float
    height_mm: float
    z_min_mm: float
    z_max_mm: float
    role: str


@dataclass(frozen=True)
class RingToken:
    name: str
    outer_width_mm: float
    outer_height_mm: float
    inner_width_mm: float
    inner_height_mm: float
    thickness_mm: float
    z_center_mm: float
    origin_xy_mm: Point2D
    role: str


@dataclass(frozen=True)
class PathTraceToken:
    name: str
    start_xy_mm: Point2D
    end_xy_mm: Point2D
    trace_width_mm: float
    z_min_mm: float
    z_max_mm: float
    role: str


@dataclass(frozen=True)
class PolygonExtrudeToken:
    name: str
    points_mm: tuple[Point3D, ...]
    extrusion_vector_mm: Vector3D
    role: str


@dataclass(frozen=True)
class UvPolygonToken:
    name: str
    config: RuntimeConfig
    frame: CoilFrame
    side: SideSpec
    face: FaceSpec
    polygon_uv_mm: tuple[Point2D, ...]
    role: str


@dataclass(frozen=True)
class SidewallConnectorToken:
    name: str
    config: RuntimeConfig
    frame: CoilFrame
    side: SideSpec
    boundary_name: str
    u_min_mm: float
    u_max_mm: float
    role: str


@dataclass(frozen=True)
class UnionToken:
    name: str
    children: Iterable[BodyToken]
    role: str


@dataclass(frozen=True)
class CutToken:
    name: str
    base: BodyToken
    cutters: Iterable[BodyToken]
    role: str


@dataclass(frozen=True)
class PartToken:
    name: str
    body: BodyToken
    color: ColorSpec
    material: str


@dataclass(frozen=True)
class AssemblyToken:
    name: str
    parts: Iterable[PartToken]
    expected_part_count: int


@dataclass(frozen=True)
class RenderedPart:
    name: str
    body: cq.Workplane
    color: cq.Color
    material: str


@dataclass(frozen=True)
class LandingGeometry:
    pieces: Iterable[BodyToken]
    clearance: BodyToken


@dataclass(frozen=True)
class SswPortGap:
    side_name: str
    face_name: str
    trace_index: int
    wrap_index: int
    u_start_mm: float
    u_end_mm: float


@dataclass(frozen=True)
class SswTraceContext:
    turn: int
    period_mm: float
    pitch_mm: float
    trace_width_mm: float
    slope: float
    port_gap: SswPortGap


@dataclass(frozen=True)
class RawActionToken:
    op: str
    target: str
    inputs: tuple[str, ...]
    params: tuple[ActionParam, ...]


@dataclass(frozen=True)
class ActionToken:
    index: int
    op: str
    target: str
    inputs: tuple[str, ...]
    params: tuple[ActionParam, ...]


BodyToken: TypeAlias = (
    BoxToken
    | RingToken
    | PathTraceToken
    | PolygonExtrudeToken
    | UvPolygonToken
    | SidewallConnectorToken
    | UnionToken
    | CutToken
)


FR4_COLOR = ColorSpec(0.02, 0.35, 0.14, 0.75)
COPPER_COLOR = ColorSpec(0.72, 0.32, 0.10, 1.0)


def default_config() -> RuntimeConfig:
    return RuntimeConfig(
        fixed=FixedDimensions(),
        common=CommonCoilParameters(),
        spiral=SpiralCoilParameters(),
        ssw=SSWCoilParameters(),
    )


def _compact(values: Iterable[T | None]) -> Iterator[T]:
    return cast(Iterator[T], filter(lambda value: value is not None, values))


def _singleton(value: T) -> Iterator[T]:
    return iter((value,))


def _empty() -> Iterator[Never]:
    return iter(())


def _prepend(value: T | None, values: Iterable[T]) -> Iterator[T]:
    return chain(_empty() if value is None else _singleton(value), values)


def _width_mm(config: RuntimeConfig, frame: CoilFrame | None = None) -> float:
    return frame.width_mm if frame is not None else config.common.width_mm(config.fixed)


def _height_mm(config: RuntimeConfig, frame: CoilFrame | None = None) -> float:
    return (
        frame.height_mm
        if frame is not None
        else config.common.height_mm(config.fixed)
    )


def validate_config(config: RuntimeConfig) -> RuntimeConfig:
    common = config.common
    spiral = config.spiral
    ssw = config.ssw

    if common.TURN_N_INT <= 0:
        raise ValueError("TURN_N_INT must be positive")
    if not 0 < common.GAP_RATIO < 1:
        raise ValueError("GAP_RATIO must be greater than 0 and less than 1")
    if common.SERIAL_COIL_N <= 0:
        raise ValueError("SERIAL_COIL_N must be positive")
    if not 0 <= common.SERIAL_COIL_GAP_RATIO < 1:
        raise ValueError(
            "SERIAL_COIL_GAP_RATIO must be greater than or equal to 0 "
            "and less than 1"
        )
    if common.SERIAL_COIL_AXIS not in (0, 1):
        raise ValueError("SERIAL_COIL_AXIS must be 0 (WIDTH) or 1 (HEIGHT)")
    if ssw.active_twist_factor(common) < 0:
        raise ValueError("SSW_TWIST_FACTOR must be greater than or equal to 0")
    if common.IS_SSW_ENABLED:
        component_count = gcd(common.TURN_N_INT, ssw.active_twist_factor(common))
        if component_count != 1:
            raise ValueError(
                "SSW TURN_N_INT and TWIST_FACTOR must be coprime for one conductor "
                f"(TURN_N_INT={common.TURN_N_INT}, TWIST_FACTOR={ssw.TWIST_FACTOR}, "
                f"component_count={component_count})"
            )
    if not common.IS_SSW_ENABLED:
        if spiral.NO_SSW_QTURN_START_INT not in range(8):
            raise ValueError("NO_SSW_QTURN_START_INT must be between 0 and 7")
        if spiral.NO_SSW_QTURN_N_INT not in range(4):
            raise ValueError("NO_SSW_QTURN_N_INT must be between 0 and 3")

    return config


def coil_slot_frames(config: RuntimeConfig) -> Iterator[CoilFrame]:
    validate_config(config)
    common = config.common
    total_width_mm = _width_mm(config)
    total_height_mm = _height_mm(config)
    coil_count = common.SERIAL_COIL_N

    if coil_count == 1:
        return _singleton(CoilFrame(total_width_mm, total_height_mm))

    selected_total_mm = (
        total_width_mm if common.SERIAL_COIL_AXIS == 0 else total_height_mm
    )
    denominator = coil_count + (coil_count - 1) * common.SERIAL_COIL_GAP_RATIO
    slot_length_mm = selected_total_mm / denominator
    gap_length_mm = slot_length_mm * common.SERIAL_COIL_GAP_RATIO

    def build_frame(index: int) -> CoilFrame:
        center_offset_mm = (
            -selected_total_mm / 2
            + slot_length_mm / 2
            + index * (slot_length_mm + gap_length_mm)
        )
        return (
            CoilFrame(
                width_mm=slot_length_mm,
                height_mm=total_height_mm,
                origin_xy_mm=(center_offset_mm, 0.0),
            )
            if common.SERIAL_COIL_AXIS == 0
            else CoilFrame(
                width_mm=total_width_mm,
                height_mm=slot_length_mm,
                origin_xy_mm=(0.0, center_offset_mm),
            )
        )

    return map(build_frame, range(coil_count))


def _void_size(config: RuntimeConfig, frame: CoilFrame | None = None) -> Point2D:
    common = config.common
    width_mm = _width_mm(config, frame)
    height_mm = _height_mm(config, frame)

    if not 0 <= common.VOID_AREA_RATIO < 1:
        raise ValueError(
            "VOID_AREA_RATIO must be greater than or equal to 0 and less than 1"
        )
    if common.VOID_PROFILE not in (0, 1):
        raise ValueError("VOID_PROFILE must be 0 or 1")

    if common.VOID_PROFILE == 1:
        remaining_area_mm2 = width_mm * height_mm * (1 - common.VOID_AREA_RATIO)
        edge_sum_mm = width_mm + height_mm
        discriminant = edge_sum_mm**2 - 4 * remaining_area_mm2
        copper_width_mm = (edge_sum_mm - sqrt(discriminant)) / 4
        return width_mm - 2 * copper_width_mm, height_mm - 2 * copper_width_mm

    scale = sqrt(common.VOID_AREA_RATIO)
    return width_mm * scale, height_mm * scale


def _pcb_pitch_mm(config: RuntimeConfig) -> float:
    return (
        config.fixed.FR4_THICKNESS_MM
        + config.fixed.COPPER_THICKNESS_MM
        + config.ssw.PCB_GAP_MM
    )


def _pcb_base_z_mm(config: RuntimeConfig, index: int) -> float:
    return index * _pcb_pitch_mm(config)


def _top_copper_z_bounds(config: RuntimeConfig) -> Point2D:
    top_base_z_mm = _pcb_base_z_mm(config, config.common.pcb_n - 1)
    z_min_mm = top_base_z_mm + config.fixed.FR4_THICKNESS_MM
    return z_min_mm, z_min_mm + config.fixed.COPPER_THICKNESS_MM


def _lower_copper_z_bounds(config: RuntimeConfig) -> Point2D:
    if config.common.IS_SSW_ENABLED:
        z_min_mm = _pcb_base_z_mm(config, 0)
        return z_min_mm, z_min_mm + config.fixed.COPPER_THICKNESS_MM

    z_min_mm = _pcb_base_z_mm(config, 0) + config.fixed.FR4_THICKNESS_MM
    return z_min_mm, z_min_mm + config.fixed.COPPER_THICKNESS_MM


def _fr4_z_center_mm(config: RuntimeConfig, index: int) -> float:
    base_z_mm = _pcb_base_z_mm(config, index)
    if config.common.IS_SSW_ENABLED and index == 0:
        return (
            base_z_mm
            + config.fixed.COPPER_THICKNESS_MM
            + config.fixed.FR4_THICKNESS_MM / 2
        )

    return base_z_mm + config.fixed.FR4_THICKNESS_MM / 2


def _coil_z_bounds(config: RuntimeConfig) -> Point2D:
    bottom_z_min_mm, _ = _lower_copper_z_bounds(config)
    _, top_z_max_mm = _top_copper_z_bounds(config)
    return bottom_z_min_mm, top_z_max_mm


def _board_trace_width_mm(
    config: RuntimeConfig,
    frame: CoilFrame | None = None,
) -> float:
    void_width_mm, void_height_mm = _void_size(config, frame)
    trace_width_x_mm = (_width_mm(config, frame) - void_width_mm) / 2
    trace_width_y_mm = (_height_mm(config, frame) - void_height_mm) / 2
    if abs(trace_width_x_mm - trace_width_y_mm) > 1e-6:
        raise ValueError("Trace-first coil generation requires equal trace width")

    return trace_width_x_mm


def loop_side_specs(config: RuntimeConfig, frame: CoilFrame) -> tuple[SideSpec, ...]:
    void_width_mm, void_height_mm = _void_size(config, frame)
    mid_width_mm = (_width_mm(config, frame) + void_width_mm) / 2
    mid_height_mm = (_height_mm(config, frame) + void_height_mm) / 2
    half_width_mm = mid_width_mm / 2
    half_height_mm = mid_height_mm / 2
    origin_x_mm, origin_y_mm = frame.origin_xy_mm
    side_data = (
        (
            "right",
            0.0,
            mid_height_mm,
            (origin_x_mm + half_width_mm, origin_y_mm - half_height_mm),
            (0.0, 1.0),
            (1.0, 0.0),
        ),
        (
            "top",
            mid_height_mm,
            mid_width_mm,
            (origin_x_mm + half_width_mm, origin_y_mm + half_height_mm),
            (-1.0, 0.0),
            (0.0, 1.0),
        ),
        (
            "left",
            mid_height_mm + mid_width_mm,
            mid_height_mm,
            (origin_x_mm - half_width_mm, origin_y_mm + half_height_mm),
            (0.0, -1.0),
            (-1.0, 0.0),
        ),
        (
            "bottom",
            2 * mid_height_mm + mid_width_mm,
            mid_width_mm,
            (origin_x_mm - half_width_mm, origin_y_mm - half_height_mm),
            (1.0, 0.0),
            (0.0, -1.0),
        ),
    )
    return tuple(starmap(SideSpec, side_data))


def loop_length(config: RuntimeConfig, frame: CoilFrame) -> float:
    return reduce(
        lambda total, side: total + side.length_mm,
        loop_side_specs(config, frame),
        0.0,
    )


def cross_section_faces(
    config: RuntimeConfig,
    frame: CoilFrame,
) -> tuple[FaceSpec, ...]:
    board_trace_width_mm = _board_trace_width_mm(config, frame)
    wall_z_min_mm, wall_z_max_mm = _coil_z_bounds(config)
    wall_height_mm = wall_z_max_mm - wall_z_min_mm
    face_data = (
        ("top", 0.0, board_trace_width_mm),
        (
            "inner",
            board_trace_width_mm,
            board_trace_width_mm + wall_height_mm,
        ),
        (
            "bottom",
            board_trace_width_mm + wall_height_mm,
            2 * board_trace_width_mm + wall_height_mm,
        ),
        (
            "outer",
            2 * board_trace_width_mm + wall_height_mm,
            2 * (board_trace_width_mm + wall_height_mm),
        ),
    )
    return tuple(starmap(FaceSpec, face_data))


def tube_cross_section_perimeter(config: RuntimeConfig, frame: CoilFrame) -> float:
    return cross_section_faces(config, frame)[-1].end_mm


def ssw_active_faces(
    config: RuntimeConfig,
    frame: CoilFrame,
) -> tuple[FaceSpec, ...]:
    board_trace_width_mm = _board_trace_width_mm(config, frame)
    return tuple(
        starmap(
            FaceSpec,
            (
                ("top", 0.0, board_trace_width_mm),
                ("bottom", board_trace_width_mm, 2 * board_trace_width_mm),
            ),
        )
    )


def ssw_active_surface_perimeter(
    config: RuntimeConfig,
    frame: CoilFrame,
) -> float:
    return 2 * _board_trace_width_mm(config, frame)


def _active_twist_factor(config: RuntimeConfig) -> int:
    return config.ssw.active_twist_factor(config.common)


def _polygon_area(polygon: tuple[Point2D, ...]) -> float:
    if len(polygon) < 3:
        return 0.0

    def add_cross(total: float, index: int) -> float:
        point = polygon[index]
        next_point = polygon[(index + 1) % len(polygon)]
        return total + point[0] * next_point[1] - next_point[0] * point[1]

    return abs(reduce(add_cross, range(len(polygon)), 0.0)) / 2


def _points_close(a: Point3D, b: Point3D) -> bool:
    return (
        abs(a[0] - b[0]) < 1e-8
        and abs(a[1] - b[1]) < 1e-8
        and abs(a[2] - b[2]) < 1e-8
    )


def _clean_points(points: Iterable[Point3D]) -> tuple[Point3D, ...]:
    def append_if_distinct(
        cleaned: tuple[Point3D, ...],
        point: Point3D,
    ) -> tuple[Point3D, ...]:
        return cleaned if cleaned and _points_close(cleaned[-1], point) else (
            *cleaned,
            point,
        )

    cleaned = reduce(append_if_distinct, points, ())
    return (
        cleaned[:-1]
        if len(cleaned) > 1 and _points_close(cleaned[0], cleaned[-1])
        else cleaned
    )


def _clip_polygon_boundary(
    polygon: tuple[Point2D, ...],
    axis: int,
    value: float,
    keep_greater: bool,
) -> tuple[Point2D, ...]:
    if not polygon:
        return ()

    def inside(point: Point2D) -> bool:
        return point[axis] >= value if keep_greater else point[axis] <= value

    def intersect(a: Point2D, b: Point2D) -> Point2D:
        denominator = b[axis] - a[axis]
        if abs(denominator) < 1e-12:
            return a
        ratio = (value - a[axis]) / denominator
        return (
            a[0] + ratio * (b[0] - a[0]),
            a[1] + ratio * (b[1] - a[1]),
        )

    def clip_step(
        state: tuple[tuple[Point2D, ...], Point2D, bool],
        current: Point2D,
    ) -> tuple[tuple[Point2D, ...], Point2D, bool]:
        output, previous, previous_inside = state
        current_inside = inside(current)
        additions = (
            (intersect(previous, current), current)
            if current_inside and not previous_inside
            else (current,)
            if current_inside
            else (intersect(previous, current),)
            if previous_inside
            else ()
        )
        return (*output, *additions), current, current_inside

    previous = polygon[-1]
    output, _, _ = reduce(clip_step, polygon, ((), previous, inside(previous)))
    return output


def _clip_polygon_to_rect(
    polygon: tuple[Point2D, ...],
    u_min_mm: float,
    u_max_mm: float,
    v_min_mm: float,
    v_max_mm: float,
) -> tuple[Point2D, ...]:
    clipped = _clip_polygon_boundary(polygon, 0, u_min_mm, True)
    clipped = _clip_polygon_boundary(clipped, 0, u_max_mm, False)
    clipped = _clip_polygon_boundary(clipped, 1, v_min_mm, True)
    return _clip_polygon_boundary(clipped, 1, v_max_mm, False)


def _surface_point_on_side(
    config: RuntimeConfig,
    frame: CoilFrame,
    side: SideSpec,
    u_local_mm: float,
    radial_mm: float,
) -> Point2D:
    sides = loop_side_specs(config, frame)
    side_index = next(
        index for index, item in enumerate(sides) if item.name == side.name
    )
    previous_side = sides[side_index - 1]
    next_side = sides[(side_index + 1) % len(sides)]
    ratio = u_local_mm / side.length_mm if side.length_mm else 0.0
    corner_x = (1 - ratio) * previous_side.normal_xy[0] + ratio * next_side.normal_xy[0]
    corner_y = (1 - ratio) * previous_side.normal_xy[1] + ratio * next_side.normal_xy[1]
    return (
        side.origin_xy_mm[0]
        + side.tangent_xy[0] * u_local_mm
        + (side.normal_xy[0] + corner_x) * radial_mm,
        side.origin_xy_mm[1]
        + side.tangent_xy[1] * u_local_mm
        + (side.normal_xy[1] + corner_y) * radial_mm,
    )


def _normal_coil_pitch_mm(config: RuntimeConfig, frame: CoilFrame) -> float:
    return _board_trace_width_mm(config, frame) / (
        config.common.TURN_N_INT + 1 - config.common.GAP_RATIO
    )


def _normal_coil_trace_width_mm(config: RuntimeConfig, frame: CoilFrame) -> float:
    return _normal_coil_pitch_mm(config, frame) * (1 - config.common.GAP_RATIO)


def _normal_coil_corner_point(
    config: RuntimeConfig,
    frame: CoilFrame,
    corner_index: int,
    offset_mm: float,
) -> Point2D:
    origin_x_mm, origin_y_mm = frame.origin_xy_mm
    right_mm = origin_x_mm + _width_mm(config, frame) / 2
    left_mm = origin_x_mm - _width_mm(config, frame) / 2
    top_mm = origin_y_mm + _height_mm(config, frame) / 2
    bottom_mm = origin_y_mm - _height_mm(config, frame) / 2
    corner = corner_index % 4
    return (
        (right_mm - offset_mm, bottom_mm + offset_mm)
        if corner == 0
        else (right_mm - offset_mm, top_mm - offset_mm)
        if corner == 1
        else (left_mm + offset_mm, top_mm - offset_mm)
        if corner == 2
        else (left_mm + offset_mm, bottom_mm + offset_mm)
    )


def _normal_coil_centerline_points(
    config: RuntimeConfig,
    frame: CoilFrame,
) -> tuple[Point2D, ...]:
    validate_config(config)
    common = config.common
    spiral = config.spiral
    pitch_mm = _normal_coil_pitch_mm(config, frame)
    trace_width_mm = pitch_mm * (1 - common.GAP_RATIO)
    outer_offset_mm = trace_width_mm / 2
    inner_offset_mm = outer_offset_mm + common.TURN_N_INT * pitch_mm
    total_qturn_count = 4 * common.TURN_N_INT - spiral.NO_SSW_QTURN_N_INT
    start_corner = spiral.NO_SSW_QTURN_START_INT % 4
    starts_from_outer = spiral.NO_SSW_QTURN_START_INT < 4

    def centerline_point(qturn_index: int) -> Point2D:
        full_turn_progress = qturn_index / 4
        offset_mm = (
            outer_offset_mm + full_turn_progress * pitch_mm
            if starts_from_outer
            else inner_offset_mm - full_turn_progress * pitch_mm
        )
        return _normal_coil_corner_point(
            config,
            frame,
            (start_corner + qturn_index) % 4,
            offset_mm,
        )

    return tuple(map(centerline_point, range(total_qturn_count + 1)))


def _normal_port_landing_pad_mm(
    config: RuntimeConfig,
    trace_width_mm: float,
) -> float:
    return trace_width_mm


def _normal_port_landing_z_bounds(config: RuntimeConfig) -> Point2D:
    fr4_bottom_z_mm = _pcb_base_z_mm(config, 0)
    z_max_mm = fr4_bottom_z_mm - config.fixed.PORT_LANDING_DROP_MM
    return z_max_mm - config.fixed.COPPER_THICKNESS_MM, z_max_mm


def _normal_port_landing_post_z_bounds(config: RuntimeConfig) -> Point2D:
    f_copper_z_min_mm, _ = _lower_copper_z_bounds(config)
    landing_z_min_mm, _ = _normal_port_landing_z_bounds(config)
    return landing_z_min_mm, f_copper_z_min_mm + config.fixed.PORT_LANDING_OVERLAP_MM


def _normal_terminal_outer_score(
    config: RuntimeConfig,
    frame: CoilFrame,
    point: Point2D,
) -> float:
    origin_x_mm, origin_y_mm = frame.origin_xy_mm
    return max(
        abs(point[0] - origin_x_mm) / (_width_mm(config, frame) / 2),
        abs(point[1] - origin_y_mm) / (_height_mm(config, frame) / 2),
    )


def _normal_outer_inner_terminals(
    config: RuntimeConfig,
    frame: CoilFrame,
    centerline_points: tuple[Point2D, ...],
) -> tuple[Point2D, Point2D]:
    start_terminal = centerline_points[0]
    end_terminal = centerline_points[-1]
    return (
        (start_terminal, end_terminal)
        if _normal_terminal_outer_score(config, frame, start_terminal)
        >= _normal_terminal_outer_score(config, frame, end_terminal)
        else (end_terminal, start_terminal)
    )


def _unit_xy_vector(
    start: Point2D,
    end: Point2D,
    context: str,
) -> Point2D:
    dx_mm = end[0] - start[0]
    dy_mm = end[1] - start[1]
    length_mm = sqrt(dx_mm**2 + dy_mm**2)
    if length_mm <= 1e-8:
        raise ValueError(f"{context} vector must be nonzero")
    return dx_mm / length_mm, dy_mm / length_mm


def _normal_outer_terminal_adjacent_point(
    centerline_points: tuple[Point2D, ...],
    outer_terminal: Point2D,
) -> Point2D:
    if len(centerline_points) < 2:
        raise ValueError("normal port landing requires at least two centerline points")
    if outer_terminal == centerline_points[0]:
        return centerline_points[1]
    if outer_terminal == centerline_points[-1]:
        return centerline_points[-2]
    raise ValueError("normal outer terminal must be the first or last centerline point")


def _normal_port_landing_direction(
    centerline_points: tuple[Point2D, ...],
    outer_terminal: Point2D,
    inner_terminal: Point2D,
) -> Point2D:
    adjacent_point = _normal_outer_terminal_adjacent_point(centerline_points, outer_terminal)
    trace_dx_mm = adjacent_point[0] - outer_terminal[0]
    trace_dy_mm = adjacent_point[1] - outer_terminal[1]
    if sqrt(trace_dx_mm**2 + trace_dy_mm**2) <= 1e-8:
        raise ValueError("normal outer-terminal trace vector must be nonzero")
    if abs(abs(trace_dx_mm) - abs(trace_dy_mm)) <= 1e-8:
        raise ValueError("normal outer-terminal trace direction is ambiguous")
    candidate_normal = (
        (0.0, 1.0)
        if abs(trace_dx_mm) > abs(trace_dy_mm)
        else (1.0, 0.0)
    )
    toward_inner = (
        inner_terminal[0] - outer_terminal[0],
        inner_terminal[1] - outer_terminal[1],
    )
    score = candidate_normal[0] * toward_inner[0] + candidate_normal[1] * toward_inner[1]
    if abs(score) <= 1e-8:
        raise ValueError(
            "normal port landing direction is ambiguous for the outer-terminal trace"
        )
    return candidate_normal if score > 0 else (-candidate_normal[0], -candidate_normal[1])


def _normal_inner_landing_center(
    config: RuntimeConfig,
    centerline_points: tuple[Point2D, ...],
    outer_terminal: Point2D,
    inner_terminal: Point2D,
    pad_mm: float,
) -> Point2D:
    direction_x, direction_y = _normal_port_landing_direction(
        centerline_points,
        outer_terminal,
        inner_terminal,
    )
    offset_mm = pad_mm + config.fixed.PORT_LENGTH_MM
    return (
        outer_terminal[0] + direction_x * offset_mm,
        outer_terminal[1] + direction_y * offset_mm,
    )


def _box_at_z_bounds_token(
    name: str,
    center_xy_mm: Point2D,
    width_mm: float,
    height_mm: float,
    z_min_mm: float,
    z_max_mm: float,
    role: str,
) -> BoxToken:
    return BoxToken(
        name=name,
        center_xy_mm=center_xy_mm,
        width_mm=width_mm,
        height_mm=height_mm,
        z_min_mm=z_min_mm,
        z_max_mm=z_max_mm,
        role=role,
    )


def _normal_corner_pad_token(
    config: RuntimeConfig,
    point: Point2D,
    trace_width_mm: float,
) -> BoxToken:
    z_min_mm, z_max_mm = _lower_copper_z_bounds(config)
    return _box_at_z_bounds_token(
        "normal_corner_pad",
        point,
        trace_width_mm,
        trace_width_mm,
        z_min_mm,
        z_max_mm,
        "copper",
    )


def _normal_segment_token(
    config: RuntimeConfig,
    start: Point2D,
    end: Point2D,
    trace_width_mm: float,
) -> PathTraceToken | None:
    dx_mm = end[0] - start[0]
    dy_mm = end[1] - start[1]
    if sqrt(dx_mm**2 + dy_mm**2) <= 1e-8:
        return None

    z_min_mm, z_max_mm = _lower_copper_z_bounds(config)
    return PathTraceToken(
        name="normal_segment",
        start_xy_mm=start,
        end_xy_mm=end,
        trace_width_mm=trace_width_mm,
        z_min_mm=z_min_mm,
        z_max_mm=z_max_mm,
        role="copper",
    )


def _normal_port_clearance_token(
    config: RuntimeConfig,
    outer_terminal: Point2D,
    inner_landing: Point2D,
    pad_mm: float,
) -> PolygonExtrudeToken:
    landing_z_min_mm, landing_z_max_mm = _normal_port_landing_z_bounds(config)
    direction_x, direction_y = _unit_xy_vector(
        outer_terminal,
        inner_landing,
        "normal_port_clearance",
    )
    half_pad_mm = pad_mm / 2
    clearance_start = (
        outer_terminal[0] + direction_x * half_pad_mm,
        outer_terminal[1] + direction_y * half_pad_mm,
    )
    clearance_end = (
        inner_landing[0] - direction_x * half_pad_mm,
        inner_landing[1] - direction_y * half_pad_mm,
    )
    return _xy_path_rectangle_token(
        "normal_port_clearance",
        clearance_start,
        clearance_end,
        pad_mm,
        landing_z_min_mm,
        landing_z_max_mm,
        "clearance",
    )


def _xy_path_rectangle_token(
    name: str,
    start: Point2D,
    end: Point2D,
    width_mm: float,
    z_min_mm: float,
    z_max_mm: float,
    role: str,
) -> PolygonExtrudeToken:
    tangent_x, tangent_y = _unit_xy_vector(start, end, name)
    normal_x = -tangent_y
    normal_y = tangent_x
    half_width_mm = width_mm / 2
    return PolygonExtrudeToken(
        name=name,
        points_mm=(
            (
                start[0] + normal_x * half_width_mm,
                start[1] + normal_y * half_width_mm,
                z_min_mm,
            ),
            (
                end[0] + normal_x * half_width_mm,
                end[1] + normal_y * half_width_mm,
                z_min_mm,
            ),
            (
                end[0] - normal_x * half_width_mm,
                end[1] - normal_y * half_width_mm,
                z_min_mm,
            ),
            (
                start[0] - normal_x * half_width_mm,
                start[1] - normal_y * half_width_mm,
                z_min_mm,
            ),
        ),
        extrusion_vector_mm=(0.0, 0.0, z_max_mm - z_min_mm),
        role=role,
    )


def _normal_port_bridge_token(
    config: RuntimeConfig,
    start: Point2D,
    end: Point2D,
    pad_mm: float,
) -> PolygonExtrudeToken | None:
    if start == end:
        return None

    z_min_mm, z_max_mm = _normal_port_landing_z_bounds(config)
    return _xy_path_rectangle_token(
        "normal_port_bridge",
        start,
        end,
        pad_mm,
        z_min_mm,
        z_max_mm,
        "copper",
    )


def _normal_port_landing_geometry(
    config: RuntimeConfig,
    frame: CoilFrame,
    centerline_points: tuple[Point2D, ...],
    trace_width_mm: float,
) -> LandingGeometry:
    pad_mm = _normal_port_landing_pad_mm(config, trace_width_mm)
    outer_terminal, inner_terminal = _normal_outer_inner_terminals(
        config,
        frame,
        centerline_points,
    )
    inner_landing = _normal_inner_landing_center(
        config,
        centerline_points,
        outer_terminal,
        inner_terminal,
        pad_mm,
    )
    landing_z_min_mm, landing_z_max_mm = _normal_port_landing_z_bounds(config)
    post_z_min_mm, post_z_max_mm = _normal_port_landing_post_z_bounds(config)
    base_pieces: tuple[BodyToken, ...] = (
        _box_at_z_bounds_token(
            "normal_outer_terminal",
            outer_terminal,
            pad_mm,
            pad_mm,
            post_z_min_mm,
            post_z_max_mm,
            "copper",
        ),
        _box_at_z_bounds_token(
            "normal_inner_terminal",
            inner_terminal,
            pad_mm,
            pad_mm,
            post_z_min_mm,
            post_z_max_mm,
            "copper",
        ),
        _box_at_z_bounds_token(
            "normal_inner_landing",
            inner_landing,
            pad_mm,
            pad_mm,
            landing_z_min_mm,
            landing_z_max_mm,
            "copper",
        ),
    )
    bridge = _normal_port_bridge_token(config, inner_terminal, inner_landing, pad_mm)
    return LandingGeometry(
        pieces=_prepend(bridge, iter(base_pieces)),
        clearance=_normal_port_clearance_token(
            config,
            outer_terminal,
            inner_landing,
            pad_mm,
        ),
    )


def _normal_port_landing_tokens(
    config: RuntimeConfig,
    frame: CoilFrame,
    centerline_points: tuple[Point2D, ...],
    trace_width_mm: float,
) -> Iterable[BodyToken]:
    return _normal_port_landing_geometry(
        config,
        frame,
        centerline_points,
        trace_width_mm,
    ).pieces


def _normal_port_bridge_for_frame(
    config: RuntimeConfig,
    frame: CoilFrame,
    centerline_points: tuple[Point2D, ...],
    trace_width_mm: float,
) -> PolygonExtrudeToken | None:
    pad_mm = _normal_port_landing_pad_mm(config, trace_width_mm)
    outer_terminal, inner_terminal = _normal_outer_inner_terminals(
        config,
        frame,
        centerline_points,
    )
    inner_landing = _normal_inner_landing_center(
        config,
        centerline_points,
        outer_terminal,
        inner_terminal,
        pad_mm,
    )
    return _normal_port_bridge_token(config, inner_terminal, inner_landing, pad_mm)


def _normal_port_landing_cutters(
    config: RuntimeConfig,
    frame: CoilFrame,
) -> Iterable[BodyToken]:
    trace_width_mm = _normal_coil_trace_width_mm(config, frame)
    centerline_points = _normal_coil_centerline_points(config, frame)
    return _normal_port_landing_tokens(
        config,
        frame,
        centerline_points,
        trace_width_mm,
    )


def _normal_coil_token(config: RuntimeConfig, frame: CoilFrame) -> UnionToken:
    trace_width_mm = _normal_coil_trace_width_mm(config, frame)
    centerline_points = _normal_coil_centerline_points(config, frame)
    corner_tokens = map(
        lambda point: _normal_corner_pad_token(config, point, trace_width_mm),
        centerline_points,
    )
    segment_tokens = _compact(
        map(
            lambda edge: _normal_segment_token(
                config,
                edge[0],
                edge[1],
                trace_width_mm,
            ),
            pairwise(centerline_points),
        )
    )
    return UnionToken(
        name="coil_copper_frame",
        children=chain(
            corner_tokens,
            segment_tokens,
            _normal_port_landing_tokens(
                config,
                frame,
                centerline_points,
                trace_width_mm,
            ),
        ),
        role="copper",
    )


def _merge_intervals(
    intervals: Iterable[Point2D],
    tolerance_mm: float = 1e-8,
) -> tuple[Point2D, ...]:
    def merge_step(merged: tuple[Point2D, ...], interval: Point2D) -> tuple[Point2D, ...]:
        start_mm, end_mm = interval
        if end_mm - start_mm <= tolerance_mm:
            return merged
        if not merged or start_mm > merged[-1][1] + tolerance_mm:
            return (*merged, interval)

        previous_start_mm, previous_end_mm = merged[-1]
        return (*merged[:-1], (previous_start_mm, max(previous_end_mm, end_mm)))

    return reduce(merge_step, sorted(intervals), ())


def _intersect_intervals(
    left: tuple[Point2D, ...],
    right: tuple[Point2D, ...],
) -> tuple[Point2D, ...]:
    left_count = len(left)
    right_count = len(right)

    def intersect_step(
        state: tuple[int, int, tuple[Point2D, ...]],
        _: None,
    ) -> tuple[int, int, tuple[Point2D, ...]]:
        left_index, right_index, intersections = state
        if left_index >= left_count or right_index >= right_count:
            return state

        start_mm = max(left[left_index][0], right[right_index][0])
        end_mm = min(left[left_index][1], right[right_index][1])
        next_intersections = (
            (*intersections, (start_mm, end_mm))
            if end_mm - start_mm > 1e-8
            else intersections
        )
        return (
            (left_index + 1, right_index, next_intersections)
            if left[left_index][1] < right[right_index][1]
            else (left_index, right_index + 1, next_intersections)
        )

    max_steps = left_count + right_count
    _, _, intersections = reduce(
        intersect_step,
        (None for _ in range(max_steps)),
        (0, 0, ()),
    )
    return intersections


def _trace_polygon_for_face(
    config: RuntimeConfig,
    frame: CoilFrame,
    side: SideSpec,
    face: FaceSpec,
    trace_index: int,
    wrap_index: int,
    pitch_mm: float,
    trace_width_mm: float,
    period_mm: float,
) -> tuple[Point2D, ...]:
    slope = _active_twist_factor(config) * pitch_mm / loop_length(config, frame)
    center_start_mm = (
        trace_index * pitch_mm
        + slope * side.u_start_mm
        + wrap_index * period_mm
    )
    center_end_mm = center_start_mm + slope * side.length_mm
    raw_polygon = (
        (0.0, center_start_mm - trace_width_mm / 2),
        (side.length_mm, center_end_mm - trace_width_mm / 2),
        (side.length_mm, center_end_mm + trace_width_mm / 2),
        (0.0, center_start_mm + trace_width_mm / 2),
    )
    return _clip_polygon_to_rect(
        raw_polygon,
        0.0,
        side.length_mm,
        face.start_mm,
        face.end_mm,
    )


def _split_polygon_around_ssw_port_gap(
    side: SideSpec,
    face: FaceSpec,
    trace_index: int,
    wrap_index: int,
    polygon: tuple[Point2D, ...],
    port_gap: SswPortGap,
) -> Iterator[tuple[Point2D, ...]]:
    if (
        side.name != port_gap.side_name
        or face.name != port_gap.face_name
        or trace_index != port_gap.trace_index
        or wrap_index != port_gap.wrap_index
    ):
        return _singleton(polygon)

    split_polygons = (
        _clip_polygon_to_rect(
            polygon,
            0.0,
            port_gap.u_start_mm,
            face.start_mm,
            face.end_mm,
        ),
        _clip_polygon_to_rect(
            polygon,
            port_gap.u_end_mm,
            side.length_mm,
            face.start_mm,
            face.end_mm,
        ),
    )
    return filter(lambda split_polygon: _polygon_area(split_polygon) > 1e-8, split_polygons)


def _trace_boundary_intervals(
    config: RuntimeConfig,
    frame: CoilFrame,
    side: SideSpec,
    trace_index: int,
    pitch_mm: float,
    trace_width_mm: float,
    period_mm: float,
    boundary_v_mm: float,
) -> tuple[Point2D, ...]:
    slope = _active_twist_factor(config) * pitch_mm / loop_length(config, frame)
    center_start_mm = trace_index * pitch_mm + slope * side.u_start_mm
    center_end_mm = center_start_mm + slope * side.length_mm
    center_min_mm = min(center_start_mm, center_end_mm)
    center_max_mm = max(center_start_mm, center_end_mm)
    half_trace_width_mm = trace_width_mm / 2
    boundary_min_mm = boundary_v_mm - half_trace_width_mm
    boundary_max_mm = boundary_v_mm + half_trace_width_mm
    min_wrap = floor((boundary_min_mm - center_max_mm) / period_mm) - 1
    max_wrap = ceil((boundary_max_mm - center_min_mm) / period_mm) + 1

    def flat_interval(wrap_index: int) -> Point2D | None:
        center_mm = center_start_mm + wrap_index * period_mm
        return (
            (0.0, side.length_mm)
            if boundary_min_mm <= center_mm <= boundary_max_mm
            else None
        )

    def sloped_interval(wrap_index: int) -> Point2D | None:
        wrapped_center_start_mm = center_start_mm + wrap_index * period_mm
        u_a_mm = (boundary_min_mm - wrapped_center_start_mm) / slope
        u_b_mm = (boundary_max_mm - wrapped_center_start_mm) / slope
        u_min_mm = max(0.0, min(u_a_mm, u_b_mm))
        u_max_mm = min(side.length_mm, max(u_a_mm, u_b_mm))
        return (u_min_mm, u_max_mm) if u_max_mm - u_min_mm > 1e-8 else None

    interval_factory = flat_interval if abs(slope) <= 1e-12 else sloped_interval
    return _merge_intervals(_compact(map(interval_factory, range(min_wrap, max_wrap + 1))))


def _ssw_port_gap_wrap_candidate(
    config: RuntimeConfig,
    frame: CoilFrame,
    side: SideSpec,
    face: FaceSpec,
    trace_index: int,
    wrap_index: int,
    pitch_mm: float,
    trace_width_mm: float,
    period_mm: float,
) -> SswPortGap | None:
    gap_start_u_mm = config.fixed.PORT_LENGTH_MM
    gap_end_u_mm = gap_start_u_mm + config.fixed.PORT_LENGTH_MM
    half_trace_width_mm = trace_width_mm / 2
    slope = _active_twist_factor(config) * pitch_mm / loop_length(config, frame)
    center_start_mm = trace_index * pitch_mm + slope * side.u_start_mm
    center_min_mm = center_start_mm + slope * gap_start_u_mm
    center_max_mm = center_start_mm + slope * gap_end_u_mm
    wrapped_min_mm = center_min_mm + wrap_index * period_mm
    wrapped_max_mm = center_max_mm + wrap_index * period_mm
    return (
        SswPortGap(
            side_name=side.name,
            face_name=face.name,
            trace_index=trace_index,
            wrap_index=wrap_index,
            u_start_mm=gap_start_u_mm,
            u_end_mm=gap_end_u_mm,
        )
        if min(wrapped_min_mm, wrapped_max_mm) - half_trace_width_mm >= face.start_mm
        and max(wrapped_min_mm, wrapped_max_mm) + half_trace_width_mm <= face.end_mm
        else None
    )


def _ssw_port_gap_trace_candidates(
    config: RuntimeConfig,
    frame: CoilFrame,
    side: SideSpec,
    face: FaceSpec,
    trace_index: int,
    pitch_mm: float,
    trace_width_mm: float,
    period_mm: float,
) -> Iterator[SswPortGap]:
    gap_start_u_mm = config.fixed.PORT_LENGTH_MM
    gap_end_u_mm = gap_start_u_mm + config.fixed.PORT_LENGTH_MM
    slope = _active_twist_factor(config) * pitch_mm / loop_length(config, frame)
    center_start_mm = trace_index * pitch_mm + slope * side.u_start_mm
    center_min_mm = center_start_mm + slope * gap_start_u_mm
    center_max_mm = center_start_mm + slope * gap_end_u_mm
    min_wrap = floor(
        (face.start_mm - max(center_min_mm, center_max_mm)) / period_mm
    ) - 1
    max_wrap = ceil(
        (face.end_mm - min(center_min_mm, center_max_mm)) / period_mm
    ) + 1
    return _compact(
        map(
            lambda wrap_index: _ssw_port_gap_wrap_candidate(
                config,
                frame,
                side,
                face,
                trace_index,
                wrap_index,
                pitch_mm,
                trace_width_mm,
                period_mm,
            ),
            range(min_wrap, max_wrap + 1),
        )
    )


def _ssw_port_gap_face_candidates(
    config: RuntimeConfig,
    frame: CoilFrame,
    side: SideSpec,
    face: FaceSpec,
    pitch_mm: float,
    trace_width_mm: float,
    period_mm: float,
) -> Iterator[SswPortGap]:
    return chain.from_iterable(
        map(
            lambda trace_index: _ssw_port_gap_trace_candidates(
                config,
                frame,
                side,
                face,
                trace_index,
                pitch_mm,
                trace_width_mm,
                period_mm,
            ),
            range(config.ssw.turn(config.common)),
        )
    )


def _ssw_port_gap_side_candidates(
    config: RuntimeConfig,
    frame: CoilFrame,
    side: SideSpec,
    pitch_mm: float,
    trace_width_mm: float,
    period_mm: float,
) -> Iterator[SswPortGap]:
    gap_end_u_mm = config.fixed.PORT_LENGTH_MM * 2
    if gap_end_u_mm > side.length_mm:
        return _empty()

    return chain.from_iterable(
        map(
            lambda face: _ssw_port_gap_face_candidates(
                config,
                frame,
                side,
                face,
                pitch_mm,
                trace_width_mm,
                period_mm,
            ),
            ssw_active_faces(config, frame),
        )
    )


def _ssw_port_gap_spec(
    config: RuntimeConfig,
    frame: CoilFrame,
    pitch_mm: float,
    trace_width_mm: float,
    period_mm: float,
) -> SswPortGap:
    candidates = chain.from_iterable(
        map(
            lambda side: _ssw_port_gap_side_candidates(
                config,
                frame,
                side,
                pitch_mm,
                trace_width_mm,
                period_mm,
            ),
            loop_side_specs(config, frame),
        )
    )
    try:
        return next(candidates)
    except StopIteration as exc:
        # Infeasible-but-in-range point (e.g. few turns / wide trace leaves no spot for the
        # 2 mm port gap). Raise ValueError so the sampler rejects this draw and resamples,
        # consistent with the other geometry validation failures here.
        raise ValueError("No intact SSW trace region found for the 2 mm port gap") from exc


def _ssw_trace_context(config: RuntimeConfig, frame: CoilFrame) -> SswTraceContext:
    validate_config(config)
    ssw_turn = config.ssw.turn(config.common)
    if ssw_turn <= 0:
        raise ValueError("SSW trace generation requires positive SSW turn count")

    period_mm = ssw_active_surface_perimeter(config, frame)
    pitch_mm = period_mm / ssw_turn
    trace_width_mm = pitch_mm * (1 - config.ssw.gap_ratio(config.common))
    return SswTraceContext(
        turn=ssw_turn,
        period_mm=period_mm,
        pitch_mm=pitch_mm,
        trace_width_mm=trace_width_mm,
        slope=_active_twist_factor(config) * pitch_mm / loop_length(config, frame),
        port_gap=_ssw_port_gap_spec(config, frame, pitch_mm, trace_width_mm, period_mm),
    )


def _ssw_trace_wrap_indices(
    side: SideSpec,
    face: FaceSpec,
    trace_index: int,
    context: SswTraceContext,
) -> range:
    center_start_mm = trace_index * context.pitch_mm + context.slope * side.u_start_mm
    center_end_mm = center_start_mm + context.slope * side.length_mm
    min_center_mm = min(center_start_mm, center_end_mm) - context.trace_width_mm / 2
    max_center_mm = max(center_start_mm, center_end_mm) + context.trace_width_mm / 2
    min_wrap = floor((face.start_mm - max_center_mm) / context.period_mm) - 1
    max_wrap = ceil((face.end_mm - min_center_mm) / context.period_mm) + 1
    return range(min_wrap, max_wrap + 1)


def _ssw_horizontal_wrap_tokens(
    config: RuntimeConfig,
    frame: CoilFrame,
    side: SideSpec,
    face: FaceSpec,
    trace_index: int,
    wrap_index: int,
    context: SswTraceContext,
) -> Iterator[BodyToken]:
    polygon = _trace_polygon_for_face(
        config,
        frame,
        side,
        face,
        trace_index,
        wrap_index,
        context.pitch_mm,
        context.trace_width_mm,
        context.period_mm,
    )
    if _polygon_area(polygon) <= 1e-8:
        return _empty()

    return map(
        lambda split_polygon: UvPolygonToken(
            name="ssw_uv_trace",
            config=config,
            frame=frame,
            side=side,
            face=face,
            polygon_uv_mm=split_polygon,
            role="copper",
        ),
        _split_polygon_around_ssw_port_gap(
            side,
            face,
            trace_index,
            wrap_index,
            polygon,
            context.port_gap,
        ),
    )


def _ssw_horizontal_trace_index_tokens(
    config: RuntimeConfig,
    frame: CoilFrame,
    side: SideSpec,
    face: FaceSpec,
    trace_index: int,
    context: SswTraceContext,
) -> Iterator[BodyToken]:
    return chain.from_iterable(
        map(
            lambda wrap_index: _ssw_horizontal_wrap_tokens(
                config,
                frame,
                side,
                face,
                trace_index,
                wrap_index,
                context,
            ),
            _ssw_trace_wrap_indices(side, face, trace_index, context),
        )
    )


def _ssw_horizontal_face_tokens(
    config: RuntimeConfig,
    frame: CoilFrame,
    side: SideSpec,
    face: FaceSpec,
    context: SswTraceContext,
) -> Iterator[BodyToken]:
    return chain.from_iterable(
        map(
            lambda trace_index: _ssw_horizontal_trace_index_tokens(
                config,
                frame,
                side,
                face,
                trace_index,
                context,
            ),
            range(context.turn),
        )
    )


def _ssw_horizontal_side_tokens(
    config: RuntimeConfig,
    frame: CoilFrame,
    side: SideSpec,
    context: SswTraceContext,
) -> Iterator[BodyToken]:
    return chain.from_iterable(
        map(
            lambda face: _ssw_horizontal_face_tokens(
                config,
                frame,
                side,
                face,
                context,
            ),
            ssw_active_faces(config, frame),
        )
    )


def _sidewall_connector_token_for_interval(
    config: RuntimeConfig,
    frame: CoilFrame,
    side: SideSpec,
    boundary_name: str,
    interval: Point2D,
) -> SidewallConnectorToken | None:
    u_min_mm = max(0.0, interval[0])
    u_max_mm = min(side.length_mm, interval[1])
    return (
        SidewallConnectorToken(
            name="ssw_sidewall_connector",
            config=config,
            frame=frame,
            side=side,
            boundary_name=boundary_name,
            u_min_mm=u_min_mm,
            u_max_mm=u_max_mm,
            role="copper",
        )
        if u_max_mm - u_min_mm > 1e-8
        else None
    )


def _sidewall_connector_boundary_tokens(
    config: RuntimeConfig,
    frame: CoilFrame,
    side: SideSpec,
    trace_index: int,
    context: SswTraceContext,
    boundary_name: str,
    top_boundary_v_mm: float,
    bottom_boundary_v_mm: float,
) -> Iterator[BodyToken]:
    top_intervals = _trace_boundary_intervals(
        config,
        frame,
        side,
        trace_index,
        context.pitch_mm,
        context.trace_width_mm,
        context.period_mm,
        top_boundary_v_mm,
    )
    bottom_intervals = _trace_boundary_intervals(
        config,
        frame,
        side,
        trace_index,
        context.pitch_mm,
        context.trace_width_mm,
        context.period_mm,
        bottom_boundary_v_mm,
    )
    return _compact(
        map(
            lambda interval: _sidewall_connector_token_for_interval(
                config,
                frame,
                side,
                boundary_name,
                interval,
            ),
            _intersect_intervals(top_intervals, bottom_intervals),
        )
    )


def _sidewall_connector_trace_tokens(
    config: RuntimeConfig,
    frame: CoilFrame,
    side: SideSpec,
    trace_index: int,
    context: SswTraceContext,
) -> Iterator[BodyToken]:
    board_trace_width_mm = _board_trace_width_mm(config, frame)
    boundaries = (
        ("outer", 0.0, context.period_mm),
        ("inner", board_trace_width_mm, board_trace_width_mm),
    )
    return chain.from_iterable(
        starmap(
            lambda boundary_name, top_boundary_v_mm, bottom_boundary_v_mm: (
                _sidewall_connector_boundary_tokens(
                    config,
                    frame,
                    side,
                    trace_index,
                    context,
                    boundary_name,
                    top_boundary_v_mm,
                    bottom_boundary_v_mm,
                )
            ),
            boundaries,
        )
    )


def _sidewall_connector_side_tokens(
    config: RuntimeConfig,
    frame: CoilFrame,
    side: SideSpec,
    context: SswTraceContext,
) -> Iterator[BodyToken]:
    return chain.from_iterable(
        map(
            lambda trace_index: _sidewall_connector_trace_tokens(
                config,
                frame,
                side,
                trace_index,
                context,
            ),
            range(context.turn),
        )
    )


def _ssw_side_tokens(
    config: RuntimeConfig,
    frame: CoilFrame,
    context: SswTraceContext,
    side: SideSpec,
) -> Iterator[BodyToken]:
    return chain(
        _sidewall_connector_side_tokens(config, frame, side, context),
        _ssw_horizontal_side_tokens(config, frame, side, context),
    )


def _ssw_trace_piece_tokens(
    config: RuntimeConfig,
    frame: CoilFrame,
) -> Iterator[BodyToken]:
    context = _ssw_trace_context(config, frame)
    return chain.from_iterable(
        map(
            lambda side: _ssw_side_tokens(config, frame, context, side),
            loop_side_specs(config, frame),
        )
    )


def _fr4_body_token(
    config: RuntimeConfig,
    fr4_name: str,
    pcb_index: int,
    frame: CoilFrame,
) -> BodyToken:
    void_width_mm, void_height_mm = _void_size(config, frame)
    ring = RingToken(
        name=fr4_name,
        outer_width_mm=_width_mm(config, frame),
        outer_height_mm=_height_mm(config, frame),
        inner_width_mm=void_width_mm,
        inner_height_mm=void_height_mm,
        thickness_mm=config.fixed.FR4_THICKNESS_MM,
        z_center_mm=_fr4_z_center_mm(config, pcb_index),
        origin_xy_mm=frame.origin_xy_mm,
        role="fr4",
    )
    return (
        CutToken(
            name=fr4_name,
            base=ring,
            cutters=_normal_port_landing_cutters(config, frame),
            role="fr4",
        )
        if not config.common.IS_SSW_ENABLED
        else ring
    )


def pcb_part_token(config: RuntimeConfig, pcb_index: int) -> PartToken:
    fr4_name = f"pcb_{pcb_index + 1}_fr4"
    return PartToken(
        name=fr4_name,
        body=UnionToken(
            name=fr4_name,
            children=map(
                lambda frame: _fr4_body_token(config, fr4_name, pcb_index, frame),
                coil_slot_frames(config),
            ),
            role="fr4",
        ),
        color=FR4_COLOR,
        material="fr4",
    )


def pcb_part_tokens(config: RuntimeConfig) -> Iterator[PartToken]:
    return map(lambda pcb_index: pcb_part_token(config, pcb_index), range(config.common.pcb_n))


def coil_copper_part_token(config: RuntimeConfig) -> PartToken:
    if not config.common.IS_SSW_ENABLED:
        name = "coil_copper"
        body_children: Iterable[BodyToken] = map(
            lambda frame: _normal_coil_token(config, frame),
            coil_slot_frames(config),
        )
    else:
        name = "ssw_copper"
        body_children = chain.from_iterable(
            map(
                lambda frame: _ssw_trace_piece_tokens(config, frame),
                coil_slot_frames(config),
            )
        )

    return PartToken(
        name=name,
        body=UnionToken(name=name, children=body_children, role="copper"),
        color=COPPER_COLOR,
        material="copper",
    )


def part_tokens(config: RuntimeConfig) -> Iterator[PartToken]:
    return chain(pcb_part_tokens(config), _singleton(coil_copper_part_token(config)))


def assembly_token(config: RuntimeConfig) -> AssemblyToken:
    return AssemblyToken(
        name="pcb_stack",
        parts=part_tokens(config),
        expected_part_count=config.common.pcb_n + 1,
    )


def _action_value(value: object) -> ActionValue:
    if isinstance(value, str) or isinstance(value, int) or isinstance(value, float):
        return value
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, tuple):
        return tuple(map(_action_value, value))

    raise TypeError(f"Action token value is not transformer-ready: {value!r}")


def _action_params(**params: object) -> tuple[ActionParam, ...]:
    return tuple(map(lambda item: (item[0], _action_value(item[1])), params.items()))


def _raw_action(
    op: str,
    target: str,
    inputs: Iterable[str] = (),
    **params: object,
) -> RawActionToken:
    return RawActionToken(
        op=op,
        target=target,
        inputs=tuple(inputs),
        params=_action_params(**params),
    )


def _frame_id(frame_index: int) -> str:
    return f"frame_{frame_index}"


def _point_id(frame_ref: str, point_index: int) -> str:
    return f"{frame_ref}.point_{point_index}"


def _corner_pad_id(frame_ref: str, point_index: int) -> str:
    return f"{frame_ref}.corner_pad_{point_index}"


def _segment_id(frame_ref: str, segment_index: int) -> str:
    return f"{frame_ref}.segment_{segment_index}"


def _normal_segment_id(frame_ref: str, segment_index: int) -> str:
    return f"{frame_ref}.normal_segment_{segment_index}"


def _port_id(frame_ref: str, name: str) -> str:
    return f"{frame_ref}.port.{name}"


def _ring_id(fr4_name: str, frame_ref: str) -> str:
    return f"{fr4_name}.{frame_ref}.ring"


def _fr4_body_id(fr4_name: str, frame_ref: str) -> str:
    return f"{fr4_name}.{frame_ref}.body"


def _ssw_piece_id(frame_ref: str, piece_index: int) -> str:
    return f"{frame_ref}.ssw_piece_{piece_index}"


def _point2_action(point: Point2D) -> tuple[float, float]:
    return point


def _point3_action(point: Point3D) -> tuple[float, float, float]:
    return point


def _points2_action(points: Iterable[Point2D]) -> tuple[tuple[float, float], ...]:
    return tuple(map(_point2_action, points))


def _points3_action(points: Iterable[Point3D]) -> tuple[tuple[float, float, float], ...]:
    return tuple(map(_point3_action, points))


def _config_action_tokens(config: RuntimeConfig) -> Iterator[RawActionToken]:
    return iter(
        (
            _raw_action(
                "CONFIG",
                "config",
                fixed=(
                    ("FR4_THICKNESS_MM", config.fixed.FR4_THICKNESS_MM),
                    ("COPPER_THICKNESS_MM", config.fixed.COPPER_THICKNESS_MM),
                    ("PORT_LENGTH_MM", config.fixed.PORT_LENGTH_MM),
                    ("PORT_LANDING_PAD_MM", config.fixed.PORT_LANDING_PAD_MM),
                    ("PORT_LANDING_DROP_MM", config.fixed.PORT_LANDING_DROP_MM),
                    ("PORT_LANDING_OVERLAP_MM", config.fixed.PORT_LANDING_OVERLAP_MM),
                    ("WIDTH_MAX_MM", config.fixed.WIDTH_MAX_MM),
                    ("HEIGHT_MAX_MM", config.fixed.HEIGHT_MAX_MM),
                ),
                common=(
                    ("WIDTH_RATIO", config.common.WIDTH_RATIO),
                    ("HEIGHT_RATIO", config.common.HEIGHT_RATIO),
                    ("IS_SSW_ENABLED", config.common.IS_SSW_ENABLED),
                    ("TURN_N_INT", config.common.TURN_N_INT),
                    ("GAP_RATIO", config.common.GAP_RATIO),
                    ("VOID_AREA_RATIO", config.common.VOID_AREA_RATIO),
                    ("VOID_PROFILE", config.common.VOID_PROFILE),
                    ("SERIAL_COIL_N", config.common.SERIAL_COIL_N),
                    ("SERIAL_COIL_GAP_RATIO", config.common.SERIAL_COIL_GAP_RATIO),
                    ("SERIAL_COIL_AXIS", config.common.SERIAL_COIL_AXIS),
                ),
                spiral=(
                    (
                        "NO_SSW_QTURN_START_INT",
                        config.spiral.NO_SSW_QTURN_START_INT,
                    ),
                    ("NO_SSW_QTURN_N_INT", config.spiral.NO_SSW_QTURN_N_INT),
                ),
                ssw=(
                    ("PCB_GAP_MM", config.ssw.PCB_GAP_MM),
                    ("TWIST_FACTOR", config.ssw.TWIST_FACTOR),
                ),
                output_step=config.output_step,
                output_token_toml=config.output_token_toml,
            ),
            _raw_action(
                "VALIDATE_CONFIG",
                "config.validated",
                ("config",),
                pcb_n=config.common.pcb_n,
                mode="ssw" if config.common.IS_SSW_ENABLED else "normal",
            ),
            _raw_action(
                "DERIVE_DIMENSION",
                "board_width_mm",
                ("config",),
                formula="WIDTH_MAX_MM * WIDTH_RATIO",
                value=config.common.width_mm(config.fixed),
            ),
            _raw_action(
                "DERIVE_DIMENSION",
                "board_height_mm",
                ("config",),
                formula="HEIGHT_MAX_MM * HEIGHT_RATIO",
                value=config.common.height_mm(config.fixed),
            ),
        )
    )


def _frame_action_tokens(
    config: RuntimeConfig,
    frames: tuple[CoilFrame, ...],
) -> Iterator[RawActionToken]:
    split_action = _raw_action(
        "FRAME_SPLIT",
        "frames",
        ("config.validated",),
        axis="WIDTH" if config.common.SERIAL_COIL_AXIS == 0 else "HEIGHT",
        count=config.common.SERIAL_COIL_N,
        gap_ratio=config.common.SERIAL_COIL_GAP_RATIO,
    )

    def frame_action(index_frame: tuple[int, CoilFrame]) -> RawActionToken:
        index, frame = index_frame
        return _raw_action(
            "FRAME",
            _frame_id(index),
            ("frames",),
            width_mm=frame.width_mm,
            height_mm=frame.height_mm,
            origin_xy_mm=_point2_action(frame.origin_xy_mm),
        )

    return chain(_singleton(split_action), map(frame_action, enumerate(frames)))


def _void_action_token(
    config: RuntimeConfig,
    frame_ref: str,
    frame: CoilFrame,
) -> RawActionToken:
    void_width_mm, void_height_mm = _void_size(config, frame)
    return _raw_action(
        "VOID_SIZE",
        f"{frame_ref}.void",
        (frame_ref, "config"),
        profile=config.common.VOID_PROFILE,
        area_ratio=config.common.VOID_AREA_RATIO,
        width_mm=void_width_mm,
        height_mm=void_height_mm,
    )


def _loop_sides_action_token(
    config: RuntimeConfig,
    frame_ref: str,
    frame: CoilFrame,
) -> RawActionToken:
    return _raw_action(
        "LOOP_SIDES",
        f"{frame_ref}.loop_sides",
        (frame_ref, f"{frame_ref}.void"),
        sides=tuple(
            map(
                lambda side: (
                    side.name,
                    side.u_start_mm,
                    side.length_mm,
                    _point2_action(side.origin_xy_mm),
                    _point2_action(side.tangent_xy),
                    _point2_action(side.normal_xy),
                ),
                loop_side_specs(config, frame),
            )
        ),
    )


def _normal_trace_refs(
    frame_ref: str,
    centerline_points: tuple[Point2D, ...],
    bridge_token: PolygonExtrudeToken | None,
) -> tuple[str, ...]:
    corner_refs = tuple(map(lambda index: _corner_pad_id(frame_ref, index), range(len(centerline_points))))
    segment_refs = tuple(
        map(
            lambda index: _segment_id(frame_ref, index),
            range(max(0, len(centerline_points) - 1)),
        )
    )
    port_refs = (
        _port_id(frame_ref, "outer_terminal"),
        _port_id(frame_ref, "inner_terminal"),
        _port_id(frame_ref, "inner_landing"),
        *((_port_id(frame_ref, "bridge"),) if bridge_token is not None else ()),
    )
    return (*corner_refs, *segment_refs, *port_refs)


def _normal_corner_point_action(
    config: RuntimeConfig,
    frame_ref: str,
    point_index: int,
    point: Point2D,
) -> RawActionToken:
    return _raw_action(
        "NORMAL_CORNER_POINT",
        _point_id(frame_ref, point_index),
        (f"{frame_ref}.centerline",),
        point_index=point_index,
        xy_mm=_point2_action(point),
        z_bounds_mm=_lower_copper_z_bounds(config),
    )


def _normal_corner_pad_action(
    frame_ref: str,
    point_index: int,
    point: Point2D,
    trace_width_mm: float,
    z_bounds: Point2D,
) -> RawActionToken:
    return _raw_action(
        "MAKE_BOX",
        _corner_pad_id(frame_ref, point_index),
        (_point_id(frame_ref, point_index),),
        center_xy_mm=_point2_action(point),
        width_mm=trace_width_mm,
        height_mm=trace_width_mm,
        z_bounds_mm=z_bounds,
        role="copper",
    )


def _normal_segment_action(
    frame_ref: str,
    segment_index: int,
    edge: tuple[Point2D, Point2D],
    trace_width_mm: float,
    z_bounds: Point2D,
) -> RawActionToken:
    return _raw_action(
        "MAKE_PATH_TRACE",
        _segment_id(frame_ref, segment_index),
        (_normal_segment_id(frame_ref, segment_index),),
        start_xy_mm=_point2_action(edge[0]),
        end_xy_mm=_point2_action(edge[1]),
        trace_width_mm=trace_width_mm,
        z_bounds_mm=z_bounds,
        role="copper",
    )


def _normal_segment_derivation_action(
    frame_ref: str,
    segment_index: int,
    edge: tuple[Point2D, Point2D],
) -> RawActionToken:
    return _raw_action(
        "NORMAL_SEGMENT",
        _normal_segment_id(frame_ref, segment_index),
        (_point_id(frame_ref, segment_index), _point_id(frame_ref, segment_index + 1)),
        start_xy_mm=_point2_action(edge[0]),
        end_xy_mm=_point2_action(edge[1]),
    )


def _normal_port_action_tokens(
    config: RuntimeConfig,
    frame_ref: str,
    frame: CoilFrame,
    centerline_points: tuple[Point2D, ...],
    trace_width_mm: float,
) -> Iterator[RawActionToken]:
    pad_mm = _normal_port_landing_pad_mm(config, trace_width_mm)
    outer_terminal, inner_terminal = _normal_outer_inner_terminals(
        config,
        frame,
        centerline_points,
    )
    inner_landing = _normal_inner_landing_center(
        config,
        centerline_points,
        outer_terminal,
        inner_terminal,
        pad_mm,
    )
    landing_z_bounds = _normal_port_landing_z_bounds(config)
    post_z_bounds = _normal_port_landing_post_z_bounds(config)
    bridge_token = _normal_port_bridge_token(config, inner_terminal, inner_landing, pad_mm)
    clearance = _normal_port_clearance_token(
        config,
        outer_terminal,
        inner_landing,
        pad_mm,
    )
    port_terminal_action = _raw_action(
        "PORT_TERMINALS",
        f"{frame_ref}.port.terminals",
        (f"{frame_ref}.centerline",),
        outer_terminal_xy_mm=_point2_action(outer_terminal),
        inner_terminal_xy_mm=_point2_action(inner_terminal),
    )
    port_landing_action = _raw_action(
        "PORT_LANDING",
        f"{frame_ref}.port.landing",
        (f"{frame_ref}.port.terminals",),
        inner_landing_xy_mm=_point2_action(inner_landing),
        pad_mm=pad_mm,
        landing_z_bounds_mm=landing_z_bounds,
        post_z_bounds_mm=post_z_bounds,
    )
    box_actions = (
        _raw_action(
            "MAKE_BOX",
            _port_id(frame_ref, "outer_terminal"),
            (f"{frame_ref}.port.terminals",),
            center_xy_mm=_point2_action(outer_terminal),
            width_mm=pad_mm,
            height_mm=pad_mm,
            z_bounds_mm=post_z_bounds,
            role="copper",
        ),
        _raw_action(
            "MAKE_BOX",
            _port_id(frame_ref, "inner_terminal"),
            (f"{frame_ref}.port.terminals",),
            center_xy_mm=_point2_action(inner_terminal),
            width_mm=pad_mm,
            height_mm=pad_mm,
            z_bounds_mm=post_z_bounds,
            role="copper",
        ),
        _raw_action(
            "MAKE_BOX",
            _port_id(frame_ref, "inner_landing"),
            (f"{frame_ref}.port.landing",),
            center_xy_mm=_point2_action(inner_landing),
            width_mm=pad_mm,
            height_mm=pad_mm,
            z_bounds_mm=landing_z_bounds,
            role="copper",
        ),
    )
    clearance_action = _raw_action(
        "EXTRUDE_POLYGON",
        _port_id(frame_ref, "clearance"),
        (f"{frame_ref}.port.landing",),
        points_mm=_points3_action(clearance.points_mm),
        extrusion_vector_mm=clearance.extrusion_vector_mm,
        role="clearance",
    )
    bridge_action = (
        _raw_action(
            "EXTRUDE_POLYGON",
            _port_id(frame_ref, "bridge"),
            (f"{frame_ref}.port.landing",),
            points_mm=_points3_action(bridge_token.points_mm),
            extrusion_vector_mm=bridge_token.extrusion_vector_mm,
            role="copper",
        )
        if bridge_token is not None
        else None
    )
    return chain(
        (port_terminal_action, port_landing_action),
        box_actions,
        (clearance_action,),
        _empty() if bridge_action is None else _singleton(bridge_action),
    )


def _normal_frame_action_tokens(
    config: RuntimeConfig,
    frame_ref: str,
    frame: CoilFrame,
) -> Iterator[RawActionToken]:
    trace_width_mm = _normal_coil_trace_width_mm(config, frame)
    pitch_mm = _normal_coil_pitch_mm(config, frame)
    centerline_points = _normal_coil_centerline_points(config, frame)
    z_bounds = _lower_copper_z_bounds(config)
    bridge_token = _normal_port_bridge_for_frame(
        config,
        frame,
        centerline_points,
        trace_width_mm,
    )
    centerline_action = _raw_action(
        "NORMAL_CENTERLINE",
        f"{frame_ref}.centerline",
        (frame_ref, "config"),
        pitch_mm=pitch_mm,
        trace_width_mm=trace_width_mm,
        start_corner=config.spiral.NO_SSW_QTURN_START_INT % 4,
        qturn_count=4 * config.common.TURN_N_INT - config.spiral.NO_SSW_QTURN_N_INT,
        points_xy_mm=_points2_action(centerline_points),
    )
    corner_point_actions = starmap(
        lambda index, point: _normal_corner_point_action(config, frame_ref, index, point),
        enumerate(centerline_points),
    )
    corner_pad_actions = starmap(
        lambda index, point: _normal_corner_pad_action(
            frame_ref,
            index,
            point,
            trace_width_mm,
            z_bounds,
        ),
        enumerate(centerline_points),
    )
    segment_actions = starmap(
        lambda index, edge: _normal_segment_action(
            frame_ref,
            index,
            edge,
            trace_width_mm,
            z_bounds,
        ),
        enumerate(pairwise(centerline_points)),
    )
    segment_derivation_actions = starmap(
        lambda index, edge: _normal_segment_derivation_action(
            frame_ref,
            index,
            edge,
        ),
        enumerate(pairwise(centerline_points)),
    )
    union_action = _raw_action(
        "UNION",
        f"{frame_ref}.normal_coil",
        _normal_trace_refs(frame_ref, centerline_points, bridge_token),
        role="copper",
    )
    return chain(
        (
            _void_action_token(config, frame_ref, frame),
            _loop_sides_action_token(config, frame_ref, frame),
            centerline_action,
        ),
        corner_point_actions,
        corner_pad_actions,
        segment_derivation_actions,
        segment_actions,
        _normal_port_action_tokens(
            config,
            frame_ref,
            frame,
            centerline_points,
            trace_width_mm,
        ),
        _singleton(union_action),
    )


def _ssw_piece_action_tokens(
    piece_ref: str,
    token: BodyToken,
) -> Iterator[RawActionToken]:
    if isinstance(token, UvPolygonToken):
        polygon_token = _uv_polygon_to_polygon_token(token)
        return iter(
            (
                _raw_action(
                    "MAKE_UV_POLYGON",
                    f"{piece_ref}.uv",
                    (f"{piece_ref}.side", f"{piece_ref}.face"),
                    side=token.side.name,
                    face=token.face.name,
                    polygon_uv_mm=_points2_action(token.polygon_uv_mm),
                    role=token.role,
                ),
                _raw_action(
                    "MAP_UV_TO_FACE",
                    f"{piece_ref}.mapped",
                    (f"{piece_ref}.uv",),
                    side=token.side.name,
                    face=token.face.name,
                    points_mm=_points3_action(polygon_token.points_mm),
                ),
                _raw_action(
                    "EXTRUDE_POLYGON",
                    piece_ref,
                    (f"{piece_ref}.mapped",),
                    points_mm=_points3_action(polygon_token.points_mm),
                    extrusion_vector_mm=polygon_token.extrusion_vector_mm,
                    role=token.role,
                ),
            )
        )
    if isinstance(token, SidewallConnectorToken):
        polygon_token = _sidewall_connector_to_polygon_token(token)
        if polygon_token is None:
            return _empty()
        return iter(
            (
                _raw_action(
                    "MAKE_SIDEWALL_CONNECTOR",
                    f"{piece_ref}.connector",
                    (f"{piece_ref}.side",),
                    side=token.side.name,
                    boundary=token.boundary_name,
                    u_bounds_mm=(token.u_min_mm, token.u_max_mm),
                    role=token.role,
                ),
                _raw_action(
                    "EXTRUDE_POLYGON",
                    piece_ref,
                    (f"{piece_ref}.connector",),
                    points_mm=_points3_action(polygon_token.points_mm),
                    extrusion_vector_mm=polygon_token.extrusion_vector_mm,
                    role=token.role,
                ),
            )
        )

    return _empty()


def _ssw_frame_action_tokens(
    config: RuntimeConfig,
    frame_ref: str,
    frame: CoilFrame,
) -> Iterator[RawActionToken]:
    context = _ssw_trace_context(config, frame)
    pieces = tuple(_ssw_trace_piece_tokens(config, frame))
    context_action = _raw_action(
        "SSW_CONTEXT",
        f"{frame_ref}.ssw_context",
        (frame_ref, "config"),
        turn=context.turn,
        period_mm=context.period_mm,
        pitch_mm=context.pitch_mm,
        trace_width_mm=context.trace_width_mm,
        slope=context.slope,
    )
    port_gap_action = _raw_action(
        "PORT_LANDING",
        f"{frame_ref}.ssw_port_gap",
        (f"{frame_ref}.ssw_context",),
        side=context.port_gap.side_name,
        face=context.port_gap.face_name,
        trace_index=context.port_gap.trace_index,
        wrap_index=context.port_gap.wrap_index,
        u_bounds_mm=(context.port_gap.u_start_mm, context.port_gap.u_end_mm),
    )
    piece_actions = chain.from_iterable(
        starmap(
            lambda index, token: _ssw_piece_action_tokens(
                _ssw_piece_id(frame_ref, index),
                token,
            ),
            enumerate(pieces),
        )
    )
    union_action = _raw_action(
        "UNION",
        f"{frame_ref}.ssw_pieces",
        tuple(map(lambda index: _ssw_piece_id(frame_ref, index), range(len(pieces)))),
        role="copper",
    )
    return chain(
        (
            _void_action_token(config, frame_ref, frame),
            _loop_sides_action_token(config, frame_ref, frame),
            context_action,
            port_gap_action,
        ),
        piece_actions,
        _singleton(union_action),
    )


def _mode_frame_action_tokens(
    config: RuntimeConfig,
    index_frame: tuple[int, CoilFrame],
) -> Iterator[RawActionToken]:
    frame_index, frame = index_frame
    frame_ref = _frame_id(frame_index)
    return (
        _ssw_frame_action_tokens(config, frame_ref, frame)
        if config.common.IS_SSW_ENABLED
        else _normal_frame_action_tokens(config, frame_ref, frame)
    )


def _pcb_frame_action_tokens(
    config: RuntimeConfig,
    fr4_name: str,
    pcb_index: int,
    frame_index: int,
    frame: CoilFrame,
) -> Iterator[RawActionToken]:
    frame_ref = _frame_id(frame_index)
    ring_ref = _ring_id(fr4_name, frame_ref)
    body_ref = _fr4_body_id(fr4_name, frame_ref)
    void_width_mm, void_height_mm = _void_size(config, frame)
    ring_action = _raw_action(
        "MAKE_RING",
        ring_ref,
        (frame_ref, f"{frame_ref}.void"),
        outer_width_mm=_width_mm(config, frame),
        outer_height_mm=_height_mm(config, frame),
        inner_width_mm=void_width_mm,
        inner_height_mm=void_height_mm,
        thickness_mm=config.fixed.FR4_THICKNESS_MM,
        z_center_mm=_fr4_z_center_mm(config, pcb_index),
        origin_xy_mm=_point2_action(frame.origin_xy_mm),
        role="fr4",
    )
    if config.common.IS_SSW_ENABLED:
        return _singleton(ring_action)

    trace_width_mm = _normal_coil_trace_width_mm(config, frame)
    centerline_points = _normal_coil_centerline_points(config, frame)
    bridge_token = _normal_port_bridge_for_frame(
        config,
        frame,
        centerline_points,
        trace_width_mm,
    )
    cut_refs = (
        _port_id(frame_ref, "outer_terminal"),
        _port_id(frame_ref, "inner_terminal"),
        _port_id(frame_ref, "inner_landing"),
        *((_port_id(frame_ref, "bridge"),) if bridge_token is not None else ()),
    )
    cut_action = _raw_action(
        "CUT",
        body_ref,
        (ring_ref, *cut_refs),
        base=ring_ref,
        cutters=cut_refs,
        role="fr4",
    )
    return iter((ring_action, cut_action))


def _pcb_part_action_tokens(
    config: RuntimeConfig,
    frames: tuple[CoilFrame, ...],
    pcb_index: int,
) -> Iterator[RawActionToken]:
    fr4_name = f"pcb_{pcb_index + 1}_fr4"
    frame_actions = chain.from_iterable(
        starmap(
            lambda frame_index, frame: _pcb_frame_action_tokens(
                config,
                fr4_name,
                pcb_index,
                frame_index,
                frame,
            ),
            enumerate(frames),
        )
    )
    child_refs = tuple(
        map(
            lambda frame_index: (
                _ring_id(fr4_name, _frame_id(frame_index))
                if config.common.IS_SSW_ENABLED
                else _fr4_body_id(fr4_name, _frame_id(frame_index))
            ),
            range(len(frames)),
        )
    )
    return chain(
        frame_actions,
        (
            _raw_action("UNION", fr4_name, child_refs, role="fr4"),
            _raw_action("PART", fr4_name, (fr4_name,), material="fr4", role="fr4"),
        ),
    )


def _copper_part_action_tokens(
    config: RuntimeConfig,
    frames: tuple[CoilFrame, ...],
) -> Iterator[RawActionToken]:
    name = "ssw_copper" if config.common.IS_SSW_ENABLED else "coil_copper"
    child_refs = tuple(
        map(
            lambda frame_index: (
                f"{_frame_id(frame_index)}.ssw_pieces"
                if config.common.IS_SSW_ENABLED
                else f"{_frame_id(frame_index)}.normal_coil"
            ),
            range(len(frames)),
        )
    )
    return iter(
        (
            _raw_action("UNION", name, child_refs, role="copper"),
            _raw_action("PART", name, (name,), material="copper", role="copper"),
        )
    )


def _part_action_tokens(
    config: RuntimeConfig,
    frames: tuple[CoilFrame, ...],
) -> Iterator[RawActionToken]:
    pcb_actions = chain.from_iterable(
        map(
            lambda pcb_index: _pcb_part_action_tokens(config, frames, pcb_index),
            range(config.common.pcb_n),
        )
    )
    part_refs = (
        *tuple(map(lambda pcb_index: f"pcb_{pcb_index + 1}_fr4", range(config.common.pcb_n))),
        "ssw_copper" if config.common.IS_SSW_ENABLED else "coil_copper",
    )
    render_actions = map(
        lambda part_ref: _raw_action("RENDER", f"render.{part_ref}", (part_ref,), target_type="part"),
        part_refs,
    )
    return chain(
        pcb_actions,
        _copper_part_action_tokens(config, frames),
        (
            _raw_action(
                "ASSEMBLY",
                "pcb_stack",
                part_refs,
                expected_part_count=config.common.pcb_n + 1,
            ),
        ),
        render_actions,
        (
            _raw_action("RENDER", "render.pcb_stack", ("pcb_stack",), target_type="assembly"),
            _raw_action(
                "EXPORT_TOKEN_TOML",
                config.output_token_toml,
                ("action_trace",),
                output_token_toml=config.output_token_toml,
            ),
            _raw_action(
                "EXPORT_STEP",
                config.output_step,
                ("render.pcb_stack",),
                output_step=config.output_step,
            ),
            _raw_action("SHOW_VIEWER", "viewer", ("render.pcb_stack",), port=3939),
        ),
    )


def raw_action_token_stream(config: RuntimeConfig) -> Iterator[RawActionToken]:
    validated = validate_config(config)
    frames = tuple(coil_slot_frames(validated))
    return chain(
        _config_action_tokens(validated),
        _frame_action_tokens(validated, frames),
        chain.from_iterable(map(lambda item: _mode_frame_action_tokens(validated, item), enumerate(frames))),
        _part_action_tokens(validated, frames),
    )


def materialize_action_trace(config: RuntimeConfig) -> tuple[ActionToken, ...]:
    return tuple(
        starmap(
            lambda index, token: ActionToken(
                index=index,
                op=token.op,
                target=token.target,
                inputs=token.inputs,
                params=token.params,
            ),
            enumerate(raw_action_token_stream(config)),
        )
    )


def _is_action_value(value: object) -> bool:
    if isinstance(value, str) or isinstance(value, int) or isinstance(value, float):
        return True
    if isinstance(value, bool) or value is None:
        return True
    if isinstance(value, tuple):
        return all(map(_is_action_value, value))

    return False


def assert_transformer_ready_action_trace(
    trace: tuple[ActionToken, ...],
) -> tuple[ActionToken, ...]:
    def validate_token(token: ActionToken) -> ActionToken:
        if not isinstance(token.index, int):
            raise TypeError("Action token index must be int")
        if not isinstance(token.op, str) or not isinstance(token.target, str):
            raise TypeError("Action token op/target must be strings")
        if not all(map(lambda item: isinstance(item, str), token.inputs)):
            raise TypeError(f"Action token inputs must be string refs: {token!r}")
        if not all(
            map(
                lambda item: isinstance(item[0], str) and _is_action_value(item[1]),
                token.params,
            )
        ):
            raise TypeError(f"Action token params are not transformer-ready: {token!r}")
        return token

    tuple(map(validate_token, trace))
    return trace


def _action_value_to_jsonable(value: ActionValue) -> object:
    if isinstance(value, tuple):
        return list(map(_action_value_to_jsonable, value))

    return value


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_string_array(values: Iterable[str]) -> str:
    return "[" + ", ".join(map(_toml_string, values)) + "]"


def _action_value_type(value: ActionValue) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, str):
        return "str"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if value is None:
        return "none"
    if isinstance(value, tuple):
        return "tuple"

    raise TypeError(f"Unsupported action value for TOML export: {value!r}")


def _action_param_toml_lines(param: ActionParam) -> tuple[str, ...]:
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


def _action_token_toml_lines(token: ActionToken) -> tuple[str, ...]:
    header = (
        "[[actions]]",
        f"index = {token.index}",
        f"op = {_toml_string(token.op)}",
        f"target = {_toml_string(token.target)}",
        f"inputs = {_toml_string_array(token.inputs)}",
    )
    return (*header, *chain.from_iterable(map(_action_param_toml_lines, token.params)))


def action_trace_to_toml(trace: tuple[ActionToken, ...]) -> str:
    validated = assert_transformer_ready_action_trace(trace)
    metadata = (
        "[metadata]",
        'format = "coil_making_action_tokens_v1"',
        f"action_count = {len(validated)}",
        "",
    )
    body = chain.from_iterable(
        map(
            lambda token: (*_action_token_toml_lines(token), ""),
            validated,
        )
    )
    return "\n".join((*metadata, *body))


def save_action_trace_toml(
    trace: tuple[ActionToken, ...],
    output_path: Path,
) -> Path:
    output_path.write_text(action_trace_to_toml(trace), encoding="utf-8")
    return output_path


def _color_to_cq(color: ColorSpec) -> cq.Color:
    return cq.Color(color.red, color.green, color.blue, color.alpha)


def _render_box_token(token: BoxToken) -> cq.Workplane:
    return (
        cq.Workplane("XY")
        .box(token.width_mm, token.height_mm, token.z_max_mm - token.z_min_mm)
        .translate(
            (
                token.center_xy_mm[0],
                token.center_xy_mm[1],
                (token.z_min_mm + token.z_max_mm) / 2,
            )
        )
        .tag(token.name)
    )


def _render_ring_token(token: RingToken) -> cq.Workplane:
    solid = cq.Workplane("XY").box(
        token.outer_width_mm,
        token.outer_height_mm,
        token.thickness_mm,
    )
    if token.inner_width_mm > 0 and token.inner_height_mm > 0:
        solid = solid.cut(
            cq.Workplane("XY").box(
                token.inner_width_mm,
                token.inner_height_mm,
                token.thickness_mm * 2,
            )
        )
    return solid.translate(
        (token.origin_xy_mm[0], token.origin_xy_mm[1], token.z_center_mm)
    ).tag(token.name)


def _path_trace_to_polygon_token(token: PathTraceToken) -> PolygonExtrudeToken | None:
    dx_mm = token.end_xy_mm[0] - token.start_xy_mm[0]
    dy_mm = token.end_xy_mm[1] - token.start_xy_mm[1]
    length_mm = sqrt(dx_mm**2 + dy_mm**2)
    if length_mm <= 1e-8:
        return None

    normal_x = -dy_mm / length_mm
    normal_y = dx_mm / length_mm
    half_width_mm = token.trace_width_mm / 2
    return PolygonExtrudeToken(
        name=token.name,
        points_mm=(
            (
                token.start_xy_mm[0] + normal_x * half_width_mm,
                token.start_xy_mm[1] + normal_y * half_width_mm,
                token.z_min_mm,
            ),
            (
                token.end_xy_mm[0] + normal_x * half_width_mm,
                token.end_xy_mm[1] + normal_y * half_width_mm,
                token.z_min_mm,
            ),
            (
                token.end_xy_mm[0] - normal_x * half_width_mm,
                token.end_xy_mm[1] - normal_y * half_width_mm,
                token.z_min_mm,
            ),
            (
                token.start_xy_mm[0] - normal_x * half_width_mm,
                token.start_xy_mm[1] - normal_y * half_width_mm,
                token.z_min_mm,
            ),
        ),
        extrusion_vector_mm=(0.0, 0.0, token.z_max_mm - token.z_min_mm),
        role=token.role,
    )


def _render_polygon_extrude_token(
    token: PolygonExtrudeToken,
) -> cq.Workplane | None:
    clean_points = _clean_points(token.points_mm)
    if len(clean_points) < 3:
        return None

    wire = cq.Wire.makePolygon(clean_points, close=True)
    solid = cq.Solid.extrudeLinear(wire, [], token.extrusion_vector_mm)
    return cq.Workplane("XY").newObject([solid]).tag(token.name)


def _uv_polygon_to_polygon_token(token: UvPolygonToken) -> PolygonExtrudeToken:
    board_trace_width_mm = _board_trace_width_mm(token.config, token.frame)
    if token.face.name == "top":
        z_min_mm, z_max_mm = _top_copper_z_bounds(token.config)
        radial_points = tuple(
            map(
                lambda point: board_trace_width_mm / 2
                - (point[1] - token.face.start_mm),
                token.polygon_uv_mm,
            )
        )
    elif token.face.name == "bottom":
        z_min_mm, z_max_mm = _lower_copper_z_bounds(token.config)
        radial_points = tuple(
            map(
                lambda point: (point[1] - token.face.start_mm)
                - board_trace_width_mm / 2,
                token.polygon_uv_mm,
            )
        )
    else:
        raise ValueError("UV trace rendering requires top or bottom face")

    xy_points = tuple(
        starmap(
            lambda point, radial_mm: _surface_point_on_side(
                token.config,
                token.frame,
                token.side,
                point[0],
                radial_mm,
            ),
            zip(token.polygon_uv_mm, radial_points),
        )
    )
    return PolygonExtrudeToken(
        name=token.name,
        points_mm=tuple(map(lambda xy: (xy[0], xy[1], z_min_mm), xy_points)),
        extrusion_vector_mm=(0.0, 0.0, z_max_mm - z_min_mm),
        role=token.role,
    )


def _sidewall_connector_to_polygon_token(
    token: SidewallConnectorToken,
) -> PolygonExtrudeToken | None:
    side = token.side
    sides = loop_side_specs(token.config, token.frame)
    side_index = next(index for index, item in enumerate(sides) if item.name == side.name)
    previous_side = sides[side_index - 1]
    next_side = sides[(side_index + 1) % len(sides)]
    u_min_mm = max(0.0, token.u_min_mm)
    u_max_mm = min(side.length_mm, token.u_max_mm)
    if u_max_mm - u_min_mm <= 1e-8:
        return None

    board_trace_width_mm = _board_trace_width_mm(token.config, token.frame)
    copper_thickness_mm = token.config.fixed.COPPER_THICKNESS_MM
    if token.boundary_name == "inner":
        radial_mm = -board_trace_width_mm / 2 - copper_thickness_mm
    elif token.boundary_name == "outer":
        radial_mm = board_trace_width_mm / 2
    else:
        raise ValueError("Sidewall connector boundary must be inner or outer")

    z_min_mm, _ = _lower_copper_z_bounds(token.config)
    _, z_max_mm = _top_copper_z_bounds(token.config)
    lower_start_xy = _surface_point_on_side(
        token.config,
        token.frame,
        side,
        u_min_mm,
        radial_mm,
    )
    lower_end_xy = _surface_point_on_side(
        token.config,
        token.frame,
        side,
        u_max_mm,
        radial_mm,
    )
    if u_min_mm <= 1e-8:
        lower_start_xy = (
            lower_start_xy[0] + previous_side.normal_xy[0] * copper_thickness_mm,
            lower_start_xy[1] + previous_side.normal_xy[1] * copper_thickness_mm,
        )
    if u_max_mm >= side.length_mm - 1e-8:
        lower_end_xy = (
            lower_end_xy[0] + next_side.normal_xy[0] * copper_thickness_mm,
            lower_end_xy[1] + next_side.normal_xy[1] * copper_thickness_mm,
        )

    return PolygonExtrudeToken(
        name=token.name,
        points_mm=(
            (*lower_start_xy, z_min_mm),
            (*lower_end_xy, z_min_mm),
            (*lower_end_xy, z_max_mm),
            (*lower_start_xy, z_max_mm),
        ),
        extrusion_vector_mm=(
            side.normal_xy[0] * copper_thickness_mm,
            side.normal_xy[1] * copper_thickness_mm,
            0.0,
        ),
        role=token.role,
    )


def _unite_workplanes(
    name: str,
    workplanes: Iterable[cq.Workplane],
) -> cq.Workplane:
    rendered = tuple(workplanes)
    if not rendered:
        raise RuntimeError(f"No solids were generated for {name}")

    return reduce(lambda result, workplane: result.union(workplane), rendered[1:], rendered[0]).tag(name)


def _cut_workplanes(
    name: str,
    base: cq.Workplane,
    cutters: Iterable[cq.Workplane],
) -> cq.Workplane:
    return reduce(lambda result, cutter: result.cut(cutter), cutters, base).tag(name)


def render_body_token(token: BodyToken) -> cq.Workplane | None:
    if isinstance(token, BoxToken):
        return _render_box_token(token)
    if isinstance(token, RingToken):
        return _render_ring_token(token)
    if isinstance(token, PathTraceToken):
        polygon_token = _path_trace_to_polygon_token(token)
        return None if polygon_token is None else render_body_token(polygon_token)
    if isinstance(token, PolygonExtrudeToken):
        return _render_polygon_extrude_token(token)
    if isinstance(token, UvPolygonToken):
        return render_body_token(_uv_polygon_to_polygon_token(token))
    if isinstance(token, SidewallConnectorToken):
        polygon_token = _sidewall_connector_to_polygon_token(token)
        return None if polygon_token is None else render_body_token(polygon_token)
    if isinstance(token, UnionToken):
        return _unite_workplanes(
            token.name,
            _compact(map(render_body_token, token.children)),
        )
    if isinstance(token, CutToken):
        base = render_body_token(token.base)
        if base is None:
            raise RuntimeError(f"Base solid for {token.name} rendered empty")
        return _cut_workplanes(
            token.name,
            base,
            _compact(map(render_body_token, token.cutters)),
        )

    raise TypeError(f"Unsupported body token: {token!r}")


def render_part_token(token: PartToken) -> RenderedPart:
    body = render_body_token(token.body)
    if body is None:
        raise RuntimeError(f"Part {token.name} rendered empty")

    return RenderedPart(
        name=token.name,
        body=body,
        color=_color_to_cq(token.color),
        material=token.material,
    )


def render_assembly_token(token: AssemblyToken) -> cq.Assembly:
    assembly = cq.Assembly(name=token.name)
    rendered_parts = tuple(map(render_part_token, token.parts))

    def add_part(part: RenderedPart) -> RenderedPart:
        assembly.add(part.body, name=part.name, color=part.color)
        return part

    tuple(map(add_part, rendered_parts))
    actual_parts = len(assembly.children)
    if actual_parts != token.expected_part_count:
        raise RuntimeError(
            f"Expected {token.expected_part_count} assembly parts, got {actual_parts}"
        )

    return assembly


def build_assembly(config: RuntimeConfig | None = None) -> cq.Assembly:
    validated = validate_config(config or default_config())
    assert_transformer_ready_action_trace(materialize_action_trace(validated))
    return render_assembly_token(assembly_token(validated))


def main() -> None:
    config = validate_config(default_config())
    action_trace = assert_transformer_ready_action_trace(
        materialize_action_trace(config)
    )
    assembly = render_assembly_token(assembly_token(config))
    output_path = Path(__file__).with_name(config.output_step)
    token_output_path = Path(__file__).with_name(config.output_token_toml)
    save_action_trace_toml(action_trace, token_output_path)
    assembly.save(str(output_path), exportType="STEP")
    show(assembly, reset_camera=Camera.RESET, grid=True, axes=True)
    print(f"Generated action tokens: {len(action_trace)}")
    print(f"Saved action token TOML: {token_output_path}")
    print(f"Saved STEP file: {output_path}")


if __name__ == "__main__":
    main()
