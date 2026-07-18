"""SSW AEDT port-artifact generation (packaged, headless).

Builds the STEP scene, derives semantic port edges from the coil-making token TOML, and writes
the AEDT port ledger consumed by the headless HFSS setup/solve path. This logic used to live in
``entry/debug_view_0_3_0_ssw.py``; it now ships inside the ``peetsfea`` wheel so the public runner
API (:func:`peetsfea.run_ssw_random_sample_reports_from_toml_text`) works without the ``entry``
scripts on ``sys.path``. The ``entry`` module re-exports these names for backward compatibility and
keeps the OCP-viewer/CLI wrappers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, TypedDict
import tomllib

import cadquery as cq

from peetsfea import ssw_step as ssw_step_module
from peetsfea.console_log import log_call_duration
from peetsfea.ssw_step import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SOURCE_TOML_PATH,
    SswCoilParameters,
    SswFixedSpec,
    SswStepLedger,
    export_ssw_step_artifacts,
    load_ssw_fixed_spec,
    load_ssw_step_ledger,
)
from peetsfea.ssw_design_space import SswAedtIdentity, build_ssw_aedt_identity
from peetsfea.backend.pyaedt.ssw_ports import (
    CanonicalCoordinates,
    SswAedtBodyLedgerEntry,
    SswAedtPorts,
    SswAedtPortEdgeLedgerEntry,
    SswAedtPortStepLedger,
    adaptive_mesh_max_length_mm,
    write_ssw_aedt_port_ledger,
)

SOURCE_TOML_PATH = DEFAULT_SOURCE_TOML_PATH
OUTPUT_DIR = DEFAULT_OUTPUT_DIR
SEED = 0
AEDT_SCENE_STEP_NAME = "ssw_scene.step"
AEDT_PORT_LEDGER_NAME = "ssw_aedt_port_ledger.json"
AEDT_IMPORTED_LEDGER_NAME = "ssw_aedt_imported_ledger.json"
TOKEN_EDGE_TOLERANCE_MM = 1e-8
Point2 = tuple[float, float]
Point3 = tuple[float, float, float]
PortEdgeVertices = list[list[float]]


class DebugSswSummary(TypedDict):
    source_toml_path: str
    output_dir: str
    seed: int
    step_path: str
    step_ledger_path: str
    token_toml_path: str
    body_names: list[str]
    copper_body_names: list[str]
    fr4_body_names: list[str]
    non_model_body_names: list[str]
    ferrite_body_names: list[str]
    design_id: str
    aedt_filename: str
    design_space_hash: str
    dimension_count: int
    ansys_enabled: bool
    aedt_step_path: str
    aedt_port_ledger_path: str
    aedt_imported_ledger_path: str
    aedt_path: str
    aedt_ports: SswAedtPorts


def _require_file(*, path: Path, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{label} does not exist: {path}")


def _json_action_params_by_key(action: Mapping[str, object]) -> dict[str, object]:
    params = action["params"]
    if isinstance(params, (str, bytes)) or not isinstance(params, list):
        raise TypeError("action params must be a list")
    mapped: dict[str, object] = {}
    for index, param in enumerate(params):
        if not isinstance(param, dict):
            raise TypeError(f"action params[{index}] must be an object")
        key = param["key"]
        value_json = param["value_json"]
        if not isinstance(key, str):
            raise TypeError(f"action params[{index}].key must be str")
        if not isinstance(value_json, str):
            raise TypeError(f"action params[{index}].value_json must be str")
        mapped[key] = json.loads(value_json)
    return mapped


def _token_actions(token_toml_path: Path) -> tuple[Mapping[str, object], ...]:
    token_doc = tomllib.loads(token_toml_path.read_text(encoding="utf-8"))
    actions = token_doc["actions"]
    if isinstance(actions, (str, bytes)) or not isinstance(actions, list):
        raise TypeError("coil making token actions must be a list")
    checked_actions: list[Mapping[str, object]] = []
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise TypeError(f"coil making token actions[{index}] must be an object")
        checked_actions.append(action)
    return tuple(checked_actions)


def _action_params_from_actions(
    *,
    actions: tuple[Mapping[str, object], ...],
    target: str,
    expected_op: str,
) -> dict[str, object]:
    matches = tuple(action for action in actions if action["target"] == target)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one token action for {target!r} (count={len(matches)})")
    op = matches[0]["op"]
    if op != expected_op:
        raise ValueError(f"token action {target!r} must have op {expected_op!r} (actual={op!r})")
    return _json_action_params_by_key(matches[0])


def _placement_params_from_token(*, token_toml_path: Path, target: str) -> dict[str, object]:
    return _action_params_from_actions(
        actions=_token_actions(token_toml_path),
        target=target,
        expected_op="PLACE_COIL_IN_SCENE",
    )


def _required_str(params: Mapping[str, object], *, key: str, context: str) -> str:
    if key not in params:
        raise ValueError(f"{context} is missing required key {key!r}")
    value = params[key]
    if not isinstance(value, str) or value == "":
        raise TypeError(f"{context}.{key} must be a non-empty str")
    return value


def _point2_from_object(value: object, *, context: str) -> Point2:
    if isinstance(value, (str, bytes)) or not isinstance(value, list):
        raise TypeError(f"{context} must be a list of two numbers")
    if len(value) != 2:
        raise ValueError(f"{context} must contain exactly two values")
    if isinstance(value[0], bool) or not isinstance(value[0], (int, float)):
        raise TypeError(f"{context}[0] must be numeric")
    if isinstance(value[1], bool) or not isinstance(value[1], (int, float)):
        raise TypeError(f"{context}[1] must be numeric")
    return (float(value[0]), float(value[1]))


def _point3_from_object(value: object, *, context: str) -> Point3:
    if isinstance(value, (str, bytes)) or not isinstance(value, list):
        raise TypeError(f"{context} must be a list of three numbers")
    if len(value) != 3:
        raise ValueError(f"{context} must contain exactly three values")
    if isinstance(value[0], bool) or not isinstance(value[0], (int, float)):
        raise TypeError(f"{context}[0] must be numeric")
    if isinstance(value[1], bool) or not isinstance(value[1], (int, float)):
        raise TypeError(f"{context}[1] must be numeric")
    if isinstance(value[2], bool) or not isinstance(value[2], (int, float)):
        raise TypeError(f"{context}[2] must be numeric")
    return (float(value[0]), float(value[1]), float(value[2]))


def _required_points2(params: Mapping[str, object], *, key: str, context: str) -> tuple[Point2, ...]:
    if key not in params:
        raise ValueError(f"{context} is missing required key {key!r}")
    value = params[key]
    if isinstance(value, (str, bytes)) or not isinstance(value, list):
        raise TypeError(f"{context}.{key} must be a list of two-dimensional points")
    return tuple(_point2_from_object(point, context=f"{context}.{key}[{index}]") for index, point in enumerate(value))


def _required_points3(params: Mapping[str, object], *, key: str, context: str) -> tuple[Point3, ...]:
    if key not in params:
        raise ValueError(f"{context} is missing required key {key!r}")
    value = params[key]
    if isinstance(value, (str, bytes)) or not isinstance(value, list):
        raise TypeError(f"{context}.{key} must be a list of three-dimensional points")
    return tuple(_point3_from_object(point, context=f"{context}.{key}[{index}]") for index, point in enumerate(value))


def _required_float_pair(params: Mapping[str, object], *, key: str, context: str) -> tuple[float, float]:
    if key not in params:
        raise ValueError(f"{context} is missing required key {key!r}")
    value = params[key]
    if isinstance(value, (str, bytes)) or not isinstance(value, list):
        raise TypeError(f"{context}.{key} must be a list of two numbers")
    if len(value) != 2:
        raise ValueError(f"{context}.{key} must contain exactly two values")
    if isinstance(value[0], bool) or not isinstance(value[0], (int, float)):
        raise TypeError(f"{context}.{key}[0] must be numeric")
    if isinstance(value[1], bool) or not isinstance(value[1], (int, float)):
        raise TypeError(f"{context}.{key}[1] must be numeric")
    return (float(value[0]), float(value[1]))


def _placement_for_coil(*, spec: SswFixedSpec, params: SswCoilParameters) -> cq.Location:
    assembly = ssw_step_module._coilmaker_assembly(params, spec.fixed)
    return ssw_step_module._placement_for_role(spec, params, assembly)


def _world_point_row_from_local(*, local_xyz: Point3, placement: cq.Location) -> list[float]:
    probe_half_mm = 0.003
    bbox = ssw_step_module._located_bbox(
        cq.Workplane("XY").box(probe_half_mm * 2.0, probe_half_mm * 2.0, probe_half_mm * 2.0).translate(local_xyz),
        placement,
    )
    return [
        (bbox.xmin + bbox.xmax) / 2.0,
        (bbox.ymin + bbox.ymax) / 2.0,
        (bbox.zmin + bbox.zmax) / 2.0,
    ]


def _world_edge_vertices(*, local_edge: tuple[Point3, Point3], placement: cq.Location) -> PortEdgeVertices:
    return [
        _world_point_row_from_local(local_xyz=local_edge[0], placement=placement),
        _world_point_row_from_local(local_xyz=local_edge[1], placement=placement),
    ]


def _piece_target_from_uv_target(target: str, *, context: str) -> str:
    suffix = ".uv"
    if not target.endswith(suffix):
        raise ValueError(f"{context}.target must end with {suffix!r}")
    return target[: -len(suffix)]


def _raw_action_str(action: Mapping[str, object], *, key: str, context: str) -> str:
    value = action[key]
    if not isinstance(value, str) or value == "":
        raise TypeError(f"{context}.{key} must be a non-empty str")
    return value


def _semantic_ssw_gap_edge_vertices(
    *,
    actions: tuple[Mapping[str, object], ...],
    role: str,
    placement: cq.Location,
) -> list[PortEdgeVertices]:
    gap_context = f"{role}.frame_0.ssw_port_gap"
    gap_params = _action_params_from_actions(
        actions=actions,
        target=gap_context,
        expected_op="PORT_LANDING",
    )
    side = _required_str(gap_params, key="side", context=gap_context)
    face = _required_str(gap_params, key="face", context=gap_context)
    u_start_mm, u_end_mm = _required_float_pair(gap_params, key="u_bounds_mm", context=gap_context)

    mapped_points_by_piece: dict[str, tuple[Point3, ...]] = {}
    piece_prefix = f"{role}.frame_0.ssw_piece_"
    for index, action in enumerate(actions):
        action_context = f"coil making token actions[{index}]"
        op = _raw_action_str(action, key="op", context=action_context)
        target = _raw_action_str(action, key="target", context=action_context)
        if op == "EXTRUDE_POLYGON" and target.startswith(piece_prefix):
            params = _json_action_params_by_key(action)
            mapped_points_by_piece[target] = _required_points3(params, key="points_mm", context=target)

    start_edges: list[tuple[Point3, Point3]] = []
    end_edges: list[tuple[Point3, Point3]] = []
    for index, action in enumerate(actions):
        action_context = f"coil making token actions[{index}]"
        op = _raw_action_str(action, key="op", context=action_context)
        target = _raw_action_str(action, key="target", context=action_context)
        if op != "MAKE_UV_POLYGON" or not target.startswith(piece_prefix):
            continue
        params = _json_action_params_by_key(action)
        if _required_str(params, key="side", context=target) != side:
            continue
        if _required_str(params, key="face", context=target) != face:
            continue
        piece_target = _piece_target_from_uv_target(target, context=target)
        if piece_target not in mapped_points_by_piece:
            raise ValueError(f"{target} is missing paired EXTRUDE_POLYGON token {piece_target!r}")
        uv_points = _required_points2(params, key="polygon_uv_mm", context=target)
        mapped_points = mapped_points_by_piece[piece_target]
        if len(uv_points) != len(mapped_points):
            raise ValueError(f"{target} UV/mapped point counts differ")
        for point_index, first_uv in enumerate(uv_points):
            next_index = (point_index + 1) % len(uv_points)
            second_uv = uv_points[next_index]
            local_edge = (mapped_points[point_index], mapped_points[next_index])
            if (
                abs(first_uv[0] - u_start_mm) <= TOKEN_EDGE_TOLERANCE_MM
                and abs(second_uv[0] - u_start_mm) <= TOKEN_EDGE_TOLERANCE_MM
            ):
                start_edges.append(local_edge)
            if (
                abs(first_uv[0] - u_end_mm) <= TOKEN_EDGE_TOLERANCE_MM
                and abs(second_uv[0] - u_end_mm) <= TOKEN_EDGE_TOLERANCE_MM
            ):
                end_edges.append(local_edge)
    if len(start_edges) != 1:
        raise ValueError(f"{gap_context} must resolve exactly one start boundary edge (count={len(start_edges)})")
    if len(end_edges) != 1:
        raise ValueError(f"{gap_context} must resolve exactly one end boundary edge (count={len(end_edges)})")
    return [
        _world_edge_vertices(local_edge=end_edges[0], placement=placement),
        _world_edge_vertices(local_edge=start_edges[0], placement=placement),
    ]


def _rx_normal_spiral_edge_vertices(
    *,
    actions: tuple[Mapping[str, object], ...],
    placement: cq.Location,
) -> list[PortEdgeVertices]:
    clearance_context = "rx_ssw_coil.frame_0.port.clearance"
    clearance_params = _action_params_from_actions(
        actions=actions,
        target=clearance_context,
        expected_op="EXTRUDE_POLYGON",
    )
    role = _required_str(clearance_params, key="role", context=clearance_context)
    if role != "clearance":
        raise ValueError(f"{clearance_context}.role must be 'clearance' (actual={role!r})")
    points = _required_points3(clearance_params, key="points_mm", context=clearance_context)
    if len(points) != 4:
        raise ValueError(f"{clearance_context}.points_mm must contain exactly four rectangle vertices")
    return [
        _world_edge_vertices(local_edge=(points[0], points[3]), placement=placement),
        _world_edge_vertices(local_edge=(points[1], points[2]), placement=placement),
    ]


def _canonical_from_bounds(*, min_xyz: tuple[float, float, float], max_xyz: tuple[float, float, float]) -> CanonicalCoordinates:
    return {
        "outer_bounds_min_xyz": [min_xyz[0], min_xyz[1], min_xyz[2]],
        "outer_bounds_max_xyz": [max_xyz[0], max_xyz[1], max_xyz[2]],
        "outer_bounds_size_xyz": [max_xyz[0] - min_xyz[0], max_xyz[1] - min_xyz[1], max_xyz[2] - min_xyz[2]],
    }


def _body_entry_from_ssw(body: Mapping[str, object]) -> SswAedtBodyLedgerEntry:
    object_id = body["object_id"]
    role = body["role"]
    material = body["material"]
    center = body["center_xyz"]
    size = body["size_xyz"]
    if not isinstance(object_id, str) or object_id == "":
        raise TypeError("SSW ledger body object_id must be a non-empty str")
    if not isinstance(role, str) or role == "":
        raise TypeError(f"SSW ledger body role must be a non-empty str (object_id={object_id})")
    if not isinstance(material, str) or material == "":
        raise TypeError(f"SSW ledger body material must be a non-empty str (object_id={object_id})")
    if isinstance(center, (str, bytes)) or not isinstance(center, list) or len(center) != 3:
        raise TypeError(f"SSW ledger body center_xyz must be a list of three values (object_id={object_id})")
    if isinstance(size, (str, bytes)) or not isinstance(size, list) or len(size) != 3:
        raise TypeError(f"SSW ledger body size_xyz must be a list of three values (object_id={object_id})")
    center_xyz = (float(center[0]), float(center[1]), float(center[2]))
    size_xyz = (float(size[0]), float(size[1]), float(size[2]))
    min_xyz = (
        center_xyz[0] - size_xyz[0] / 2.0,
        center_xyz[1] - size_xyz[1] / 2.0,
        center_xyz[2] - size_xyz[2] / 2.0,
    )
    max_xyz = (
        center_xyz[0] + size_xyz[0] / 2.0,
        center_xyz[1] + size_xyz[1] / 2.0,
        center_xyz[2] + size_xyz[2] / 2.0,
    )
    return {
        "object_id": object_id,
        "role": role,
        "material": material,
        "model_state": role != "non_model",
        "canonical_coordinates": _canonical_from_bounds(min_xyz=min_xyz, max_xyz=max_xyz),
    }


def _copper_body_for_role(*, ssw_ledger: SswStepLedger, role: str) -> str:
    prefix = f"{role}_"
    matches = tuple(name for name in ssw_ledger["copper_body_names"] if name.startswith(prefix))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one copper body for {role!r} (matches={matches!r})")
    return matches[0]


def _tx_port_edge_entry(
    *,
    ssw_ledger: SswStepLedger,
    spec: SswFixedSpec,
    actions: tuple[Mapping[str, object], ...],
    placement_params: Mapping[str, object],
) -> SswAedtPortEdgeLedgerEntry:
    context = "scene.tx_ssw_coil.placement"
    port_face = _required_str(placement_params, key="port_face", context=context)
    if port_face != "lower_z":
        raise ValueError(f"{context}.port_face must be 'lower_z' for TX SSW edge ports (actual={port_face!r})")
    placement = _placement_for_coil(spec=spec, params=spec.tx)
    return {
        "role": "tx",
        "copper_body_name": _copper_body_for_role(ssw_ledger=ssw_ledger, role="tx_ssw_coil"),
        "selection": "semantic_edge_vertices",
        "edge_vertices_xyz": _semantic_ssw_gap_edge_vertices(
            actions=actions,
            role="tx_ssw_coil",
            placement=placement,
        ),
    }


def _rx_port_edge_entry(
    *,
    ssw_ledger: SswStepLedger,
    spec: SswFixedSpec,
    actions: tuple[Mapping[str, object], ...],
    placement_params: Mapping[str, object],
) -> SswAedtPortEdgeLedgerEntry:
    context = "scene.rx_ssw_coil.placement"
    coil_mode = _required_str(placement_params, key="coil_mode", context=context)
    port_face = _required_str(placement_params, key="port_face", context=context)
    placement = _placement_for_coil(spec=spec, params=spec.rx)
    if coil_mode == "normal_spiral":
        if port_face != "normal_spiral_landing":
            raise ValueError(f"{context}.port_face must be normal_spiral_landing (actual={port_face!r})")
        return {
            "role": "rx",
            "copper_body_name": _copper_body_for_role(ssw_ledger=ssw_ledger, role="rx_ssw_coil"),
            "selection": "semantic_edge_vertices",
            "edge_vertices_xyz": _rx_normal_spiral_edge_vertices(actions=actions, placement=placement),
        }
    if coil_mode == "ssw":
        if port_face != "rx_x_max":
            raise ValueError(f"{context}.port_face must be rx_x_max for RX SSW edge ports (actual={port_face!r})")
        return {
            "role": "rx",
            "copper_body_name": _copper_body_for_role(ssw_ledger=ssw_ledger, role="rx_ssw_coil"),
            "selection": "semantic_edge_vertices",
            "edge_vertices_xyz": _semantic_ssw_gap_edge_vertices(
                actions=actions,
                role="rx_ssw_coil",
                placement=placement,
            ),
        }
    raise ValueError(f"{context}.coil_mode is unsupported for edge ports (actual={coil_mode!r})")


def _port_edge_entries(
    *,
    ssw_ledger: SswStepLedger,
    spec: SswFixedSpec,
    token_toml_path: Path,
) -> list[SswAedtPortEdgeLedgerEntry]:
    actions = _token_actions(token_toml_path)
    tx_placement = _placement_params_from_token(
        token_toml_path=token_toml_path,
        target="scene.tx_ssw_coil.placement",
    )
    rx_placement = _placement_params_from_token(
        token_toml_path=token_toml_path,
        target="scene.rx_ssw_coil.placement",
    )
    return [
        _tx_port_edge_entry(
            ssw_ledger=ssw_ledger,
            spec=spec,
            actions=actions,
            placement_params=tx_placement,
        ),
        _rx_port_edge_entry(
            ssw_ledger=ssw_ledger,
            spec=spec,
            actions=actions,
            placement_params=rx_placement,
        ),
    ]


@log_call_duration
def generate_ssw_debug_summary(
    *,
    source_toml_path: Path = SOURCE_TOML_PATH,
    output_dir: Path = OUTPUT_DIR,
    seed: int = SEED,
) -> DebugSswSummary:
    identity = build_ssw_aedt_identity(source_toml_path)
    artifacts = export_ssw_step_artifacts(source_toml_path=source_toml_path, output_dir=output_dir, seed=seed)
    step_path = Path(artifacts["scene_step_path"])
    ledger_path = Path(artifacts["ledger_path"])
    token_toml_path = Path(artifacts["token_toml_path"])
    _require_file(path=step_path, label="0.3.x SSW STEP file")
    _require_file(path=ledger_path, label="0.3.x SSW STEP ledger")
    _require_file(path=token_toml_path, label="0.3.x SSW coil making token TOML")
    ledger = load_ssw_step_ledger(ledger_path)
    return {
        "source_toml_path": artifacts["source_toml_path"],
        "output_dir": str(output_dir),
        "seed": seed,
        "step_path": str(step_path),
        "step_ledger_path": str(ledger_path),
        "token_toml_path": str(token_toml_path),
        "body_names": ledger["body_names"],
        "copper_body_names": ledger["copper_body_names"],
        "fr4_body_names": ledger["fr4_body_names"],
        "non_model_body_names": ledger["non_model_body_names"],
        "ferrite_body_names": ledger["ferrite_body_names"],
        "design_id": identity.design_id,
        "aedt_filename": identity.aedt_filename,
        "design_space_hash": identity.point_hash,
        "dimension_count": identity.dimension_count,
        "ansys_enabled": False,
        "aedt_step_path": "",
        "aedt_port_ledger_path": "",
        "aedt_imported_ledger_path": "",
        "aedt_path": "",
        "aedt_ports": {"tx": [], "rx": []},
    }


def _build_ssw_aedt_port_ledger(
    *,
    ssw_ledger: SswStepLedger,
    ssw_ledger_path: Path,
    aedt_step_path: Path,
    identity: SswAedtIdentity,
    port_edges: list[SswAedtPortEdgeLedgerEntry],
    mesh_max_length: str,
) -> SswAedtPortStepLedger:
    body_entries = [_body_entry_from_ssw(body) for body in ssw_ledger["bodies"]]
    return {
        "design_id": identity.design_id,
        "aedt_filename": identity.aedt_filename,
        "dimension_count": identity.dimension_count,
        "design_space_hash": identity.point_hash,
        "source_step_ledger_path": str(ssw_ledger_path),
        "scene_step_path": str(aedt_step_path),
        "seed": ssw_ledger["seed"],
        "units": ssw_ledger["units"],
        "body_names": list(ssw_ledger["body_names"]),
        "copper_body_names": list(ssw_ledger["copper_body_names"]),
        "fr4_body_names": list(ssw_ledger["fr4_body_names"]),
        "non_model_body_names": list(ssw_ledger["non_model_body_names"]),
        "ferrite_body_names": list(ssw_ledger["ferrite_body_names"]),
        "bodies": body_entries,
        "port_edges": port_edges,
        "mesh_max_length": mesh_max_length,
    }


def _ssw_mesh_max_length(spec: SswFixedSpec) -> str:
    return adaptive_mesh_max_length_mm(
        tx_trace_width_mm=ssw_step_module.ssw_trace_width_mm(params=spec.tx, fixed=spec.fixed),
        rx_trace_width_mm=ssw_step_module.ssw_trace_width_mm(params=spec.rx, fixed=spec.fixed),
    )


@log_call_duration
def export_ssw_aedt_port_artifacts(
    *,
    source_toml_path: Path = SOURCE_TOML_PATH,
    output_dir: Path = OUTPUT_DIR,
    seed: int = SEED,
) -> SswAedtPortStepLedger:
    identity = build_ssw_aedt_identity(source_toml_path)
    summary = generate_ssw_debug_summary(source_toml_path=source_toml_path, output_dir=output_dir, seed=seed)
    spec = load_ssw_fixed_spec(source_toml_path)
    ssw_ledger = load_ssw_step_ledger(Path(summary["step_ledger_path"]))
    token_toml_path = Path(summary["token_toml_path"])
    aedt_step_path = Path(summary["step_path"])
    ledger = _build_ssw_aedt_port_ledger(
        ssw_ledger=ssw_ledger,
        ssw_ledger_path=Path(summary["step_ledger_path"]),
        aedt_step_path=aedt_step_path,
        identity=identity,
        port_edges=_port_edge_entries(
            ssw_ledger=ssw_ledger,
            spec=spec,
            token_toml_path=token_toml_path,
        ),
        mesh_max_length=_ssw_mesh_max_length(spec),
    )
    write_ssw_aedt_port_ledger(ledger_path=output_dir / AEDT_PORT_LEDGER_NAME, ledger=ledger)
    return ledger


__all__ = [
    "AEDT_IMPORTED_LEDGER_NAME",
    "AEDT_PORT_LEDGER_NAME",
    "AEDT_SCENE_STEP_NAME",
    "DebugSswSummary",
    "OUTPUT_DIR",
    "SEED",
    "SOURCE_TOML_PATH",
    "TOKEN_EDGE_TOLERANCE_MM",
    "export_ssw_aedt_port_artifacts",
    "generate_ssw_debug_summary",
]
