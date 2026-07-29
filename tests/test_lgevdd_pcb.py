from __future__ import annotations

from math import pi, sin
from pathlib import Path

import pytest

import peetsfea.lgevdd_dev as dev_module
from peetsfea.lgevdd_dev import (
    COPPER_OCP_COLOR,
    FR4_OCP_COLOR,
    show_lgevdd_both_in_ocp,
    show_lgevdd_pcb_in_ocp,
    show_lgevdd_secondary_in_ocp,
)
from peetsfea.lgevdd_primary import build_lgevdd_primary_planar
from peetsfea.lgevdd_secondary import build_lgevdd_secondary_planar
from peetsfea.lgevdd_spec import (
    DEFAULT_SOURCE_TOML_PATH,
    load_lgevdd_pcb_spec,
)
from peetsfea.lgevdd_step import (
    export_lgevdd_both_step,
    export_lgevdd_pcb_step,
    export_lgevdd_secondary_step,
)


def _modified_toml(
    tmp_path: Path,
    *,
    old: str,
    new: str,
    name: str,
) -> Path:
    return _modified_toml_from(
        DEFAULT_SOURCE_TOML_PATH,
        tmp_path,
        old=old,
        new=new,
        name=name,
    )


def _modified_toml_from(
    source_path: Path,
    tmp_path: Path,
    *,
    old: str,
    new: str,
    name: str,
) -> Path:
    source_text = source_path.read_text(encoding="utf-8")
    if source_text.count(old) != 1:
        raise AssertionError(f"test replacement must match exactly once: {old!r}")
    modified_path = tmp_path / name
    modified_path.write_text(source_text.replace(old, new, 1), encoding="utf-8")
    return modified_path


def test_fixed_pcb_spec_uses_primary_planar_contract() -> None:
    spec = load_lgevdd_pcb_spec(DEFAULT_SOURCE_TOML_PATH)

    assert spec.fr4.object_id == "fr4_board"
    assert spec.fr4.material == "fr4_epoxy"
    assert spec.fr4.center_xyz == (0.0, 0.0, 0.0)
    assert spec.fr4.size_x_mm == 240.0
    assert spec.fr4.size_y_mm == 40.0
    assert spec.fr4.thickness_mm == 0.02
    assert spec.primary.object_id == "primary_planar_coil"
    assert spec.primary.material == "copper"
    assert spec.primary.turns == 14
    assert spec.primary.layer_count == 2
    assert spec.primary.trace_width_mm == 1.5
    assert spec.primary.copper_thickness_mm == 0.175
    assert spec.primary.connector_circle_segments == 12
    assert spec.secondary.object_id == "secondary_planar_coil"
    assert spec.secondary.body_ids == (
        "secondary_planar_coil_1",
        "secondary_planar_coil_2",
    )
    assert spec.secondary.body_count == 2
    assert spec.secondary.turns == 2
    assert spec.secondary.layer_count == 2
    assert spec.secondary.trace_width_mm == 7.7
    assert spec.secondary.copper_thickness_mm == 0.105
    assert spec.secondary.inner_clearance_x_mm == 2.8
    assert spec.secondary.inner_clearance_y_mm == 3.3
    assert spec.secondary.turn_gap_x_mm == 0.1
    assert spec.secondary.turn_gap_y_mm == 0.1
    assert spec.secondary.secondary_preg_mm == 0.06
    assert spec.secondary.lead_extension_x_mm == 40.0
    assert len(spec.constraints) == 22


def test_primary_fixed_geometry_is_one_fused_two_layer_solid() -> None:
    spec = load_lgevdd_pcb_spec(DEFAULT_SOURCE_TOML_PATH)
    geometry = build_lgevdd_primary_planar(spec.primary, fr4=spec.fr4)

    assert geometry.top_turns == 7
    assert geometry.bottom_turns == 7
    assert len(geometry.top_centerline_xy) == 29
    assert len(geometry.bottom_centerline_xy) == 29
    assert geometry.top_centerline_xy[0] == pytest.approx((113.0, -15.05))
    assert geometry.bottom_centerline_xy[0] == pytest.approx((113.0, 15.05))
    assert geometry.connector_center_xy == pytest.approx((76.35, 0.0))
    assert geometry.connector_radius_mm == pytest.approx(0.6)
    assert geometry.bottom_z_min_mm == pytest.approx(-0.185)
    assert geometry.bottom_z_max_mm == pytest.approx(-0.01)
    assert geometry.top_z_min_mm == pytest.approx(0.01)
    assert geometry.top_z_max_mm == pytest.approx(0.185)
    assert len(tuple(geometry.shape.solids())) == 1

    bounds = geometry.shape.bounding_box()
    assert bounds.min.X == pytest.approx(-92.7)
    assert bounds.max.X == pytest.approx(113.0)
    assert bounds.min.Y == pytest.approx(-15.8)
    assert bounds.max.Y == pytest.approx(15.8)
    assert bounds.min.Z == pytest.approx(-0.185)
    assert bounds.max.Z == pytest.approx(0.185)


def test_primary_every_internal_corner_has_full_trace_width_joint() -> None:
    spec = load_lgevdd_pcb_spec(DEFAULT_SOURCE_TOML_PATH)
    geometry = build_lgevdd_primary_planar(spec.primary, fr4=spec.fr4)
    quarter_trace = spec.primary.trace_width_mm / 4.0
    layers = (
        (
            geometry.top_centerline_xy,
            (geometry.top_z_min_mm + geometry.top_z_max_mm) / 2.0,
        ),
        (
            geometry.bottom_centerline_xy,
            (geometry.bottom_z_min_mm + geometry.bottom_z_max_mm) / 2.0,
        ),
    )

    for centerline, z_coordinate in layers:
        for corner_x, corner_y in centerline[1:-1]:
            for x_sign in (-1.0, 1.0):
                for y_sign in (-1.0, 1.0):
                    sample = (
                        corner_x + x_sign * quarter_trace,
                        corner_y + y_sign * quarter_trace,
                        z_coordinate,
                    )
                    assert geometry.shape.is_inside(sample), (
                        "internal 90-degree trace joint is missing copper at "
                        f"corner={(corner_x, corner_y)}, sample={sample}"
                    )


def test_primary_odd_turns_put_extra_turn_on_top(tmp_path: Path) -> None:
    odd_toml = _modified_toml(
        tmp_path,
        old="range = [true, 14, 14, 1]",
        new="range = [true, 15, 15, 1]",
        name="odd.toml",
    )
    spec = load_lgevdd_pcb_spec(odd_toml)
    geometry = build_lgevdd_primary_planar(spec.primary, fr4=spec.fr4)

    assert geometry.top_turns == 8
    assert geometry.bottom_turns == 7
    assert len(geometry.top_centerline_xy) == 33
    assert len(geometry.bottom_centerline_xy) == 29
    assert geometry.top_centerline_xy[-1] == geometry.bottom_centerline_xy[-1]
    assert len(tuple(geometry.shape.solids())) == 1


def test_primary_geometry_is_deterministic() -> None:
    spec_a = load_lgevdd_pcb_spec(DEFAULT_SOURCE_TOML_PATH)
    spec_b = load_lgevdd_pcb_spec(DEFAULT_SOURCE_TOML_PATH)
    geometry_a = build_lgevdd_primary_planar(spec_a.primary, fr4=spec_a.fr4)
    geometry_b = build_lgevdd_primary_planar(spec_b.primary, fr4=spec_b.fr4)

    assert geometry_a.top_centerline_xy == geometry_b.top_centerline_xy
    assert geometry_a.bottom_centerline_xy == geometry_b.bottom_centerline_xy
    assert geometry_a.connector_center_xy == geometry_b.connector_center_xy
    assert geometry_a.shape.volume == pytest.approx(geometry_b.shape.volume, abs=1.0e-9)
    assert geometry_a.shape.bounding_box().min == geometry_b.shape.bounding_box().min
    assert geometry_a.shape.bounding_box().max == geometry_b.shape.bounding_box().max


def test_secondary_fixed_geometry_is_two_symmetric_connected_bodies() -> None:
    spec = load_lgevdd_pcb_spec(DEFAULT_SOURCE_TOML_PATH)
    primary_geometry = build_lgevdd_primary_planar(spec.primary, fr4=spec.fr4)
    geometry = build_lgevdd_secondary_planar(
        spec.secondary,
        primary=spec.primary,
        fr4=spec.fr4,
        primary_geometry=primary_geometry,
    )

    assert geometry.first_layer_turns == 1
    assert geometry.second_layer_turns == 1
    assert tuple(body.object_id for body in geometry.bodies) == spec.secondary.body_ids
    upper, lower = geometry.bodies
    assert len(upper.layers) == 2
    assert len(lower.layers) == 2
    assert upper.bridge_required is True
    assert lower.bridge_required is True
    assert upper.bridge_center_xy == pytest.approx((-79.65, 0.0))
    assert lower.bridge_center_xy == pytest.approx((-79.65, 0.0))
    assert upper.terminal_start_xyz == pytest.approx((-113.0, -10.65, 0.4625))
    assert upper.terminal_end_xyz == pytest.approx((-113.0, 10.65, 0.2975))
    assert lower.terminal_start_xyz == pytest.approx((-113.0, -10.65, -0.2975))
    assert lower.terminal_end_xyz == pytest.approx((-113.0, 10.65, -0.4625))
    assert len(tuple(upper.shape.solids())) == 1
    assert len(tuple(lower.shape.solids())) == 1

    upper_bounds = upper.shape.bounding_box()
    lower_bounds = lower.shape.bounding_box()
    assert (
        upper_bounds.min.X,
        upper_bounds.min.Y,
        upper_bounds.min.Z,
        upper_bounds.max.X,
        upper_bounds.max.Y,
        upper_bounds.max.Z,
    ) == pytest.approx((-113.0, -14.5, 0.245, 83.5, 14.5, 0.515))
    assert (
        lower_bounds.min.X,
        lower_bounds.min.Y,
        lower_bounds.min.Z,
        lower_bounds.max.X,
        lower_bounds.max.Y,
        lower_bounds.max.Z,
    ) == pytest.approx((-113.0, -14.5, -0.515, 83.5, 14.5, -0.245))


def test_secondary_odd_turns_put_extra_turn_on_first_layer(tmp_path: Path) -> None:
    odd_turns_toml = _modified_toml(
        tmp_path,
        old="range = [true, 2, 2, 1]\ndescription = \"Series turns in each secondary half-winding\"",
        new="range = [true, 3, 3, 1]\ndescription = \"Series turns in each secondary half-winding\"",
        name="secondary_odd_turns.toml",
    )
    odd_toml = _modified_toml_from(
        odd_turns_toml,
        tmp_path,
        old="range = [false, 40.0, 40.0, 1]\ndescription = \"FR4 board Y size(mm)\"",
        new="range = [false, 60.0, 60.0, 1]\ndescription = \"FR4 board Y size(mm)\"",
        name="secondary_odd.toml",
    )
    spec = load_lgevdd_pcb_spec(odd_toml)
    primary_geometry = build_lgevdd_primary_planar(spec.primary, fr4=spec.fr4)
    geometry = build_lgevdd_secondary_planar(
        spec.secondary,
        primary=spec.primary,
        fr4=spec.fr4,
        primary_geometry=primary_geometry,
    )

    assert geometry.first_layer_turns == 2
    assert geometry.second_layer_turns == 1
    for body in geometry.bodies:
        assert tuple(layer.turns for layer in body.layers) == (2, 1)
        assert len(tuple(body.shape.solids())) == 1


def test_secondary_one_turn_uses_one_closed_layer_without_bridge(
    tmp_path: Path,
) -> None:
    one_turn_toml = _modified_toml(
        tmp_path,
        old="range = [true, 2, 2, 1]\ndescription = \"Series turns in each secondary half-winding\"",
        new="range = [true, 1, 1, 1]\ndescription = \"Series turns in each secondary half-winding\"",
        name="secondary_one_turn.toml",
    )
    spec = load_lgevdd_pcb_spec(one_turn_toml)
    primary_geometry = build_lgevdd_primary_planar(spec.primary, fr4=spec.fr4)
    geometry = build_lgevdd_secondary_planar(
        spec.secondary,
        primary=spec.primary,
        fr4=spec.fr4,
        primary_geometry=primary_geometry,
    )

    assert geometry.first_layer_turns == 1
    assert geometry.second_layer_turns == 0
    for body in geometry.bodies:
        assert len(body.layers) == 1
        assert body.bridge_required is False
        assert body.terminal_start_xyz[0] == pytest.approx(-113.0)
        assert body.terminal_end_xyz[0] == pytest.approx(-113.0)
        assert len(tuple(body.shape.solids())) == 1


def test_secondary_geometry_is_deterministic() -> None:
    spec_a = load_lgevdd_pcb_spec(DEFAULT_SOURCE_TOML_PATH)
    spec_b = load_lgevdd_pcb_spec(DEFAULT_SOURCE_TOML_PATH)
    primary_a = build_lgevdd_primary_planar(spec_a.primary, fr4=spec_a.fr4)
    primary_b = build_lgevdd_primary_planar(spec_b.primary, fr4=spec_b.fr4)
    geometry_a = build_lgevdd_secondary_planar(
        spec_a.secondary,
        primary=spec_a.primary,
        fr4=spec_a.fr4,
        primary_geometry=primary_a,
    )
    geometry_b = build_lgevdd_secondary_planar(
        spec_b.secondary,
        primary=spec_b.primary,
        fr4=spec_b.fr4,
        primary_geometry=primary_b,
    )

    for body_a, body_b in zip(geometry_a.bodies, geometry_b.bodies, strict=True):
        assert body_a.terminal_start_xyz == body_b.terminal_start_xyz
        assert body_a.terminal_end_xyz == body_b.terminal_end_xyz
        assert body_a.shape.volume == pytest.approx(body_b.shape.volume, abs=1.0e-9)
        assert body_a.shape.bounding_box().min == body_b.shape.bounding_box().min
        assert body_a.shape.bounding_box().max == body_b.shape.bounding_box().max


def test_pcb_step_round_trip_preserves_two_named_solids(tmp_path: Path) -> None:
    step_path = tmp_path / "lgevdd_pcb.step"
    artifacts = export_lgevdd_pcb_step(
        source_toml_path=DEFAULT_SOURCE_TOML_PATH,
        step_path=step_path,
    )

    assert artifacts.step_path == step_path.resolve()
    assert step_path.stat().st_size > 0
    assert len(tuple(artifacts.scene_shape.solids())) == 2
    assert len(tuple(artifacts.fr4_shape.solids())) == 1
    assert len(tuple(artifacts.primary_shape.solids())) == 1
    assert {child.label for child in artifacts.scene_shape.children} == {
        "fr4_board",
        "primary_planar_coil",
    }
    assert sorted(path.name for path in tmp_path.iterdir()) == ["lgevdd_pcb.step"]

    spec = artifacts.spec
    geometry = artifacts.primary_geometry
    fr4_bounds = artifacts.fr4_shape.bounding_box()
    assert fr4_bounds.size.X == pytest.approx(240.0)
    assert fr4_bounds.size.Y == pytest.approx(40.0)
    assert fr4_bounds.size.Z == pytest.approx(0.02)
    connector_polygon_area = (
        spec.primary.connector_circle_segments
        * geometry.connector_radius_mm**2
        * sin(2.0 * pi / spec.primary.connector_circle_segments)
        / 2.0
    )
    expected_fr4_volume = (
        spec.fr4.size_x_mm * spec.fr4.size_y_mm
        - (
            spec.primary.center_keepout_width_x_mm
            * spec.primary.center_keepout_height_y_mm
        )
        - connector_polygon_area
    ) * spec.fr4.thickness_mm
    assert artifacts.fr4_shape.volume == pytest.approx(expected_fr4_volume)
    assert artifacts.fr4_shape.is_inside((0.0, 0.0, 0.0)) is False
    assert artifacts.fr4_shape.is_inside((73.5, 0.0, 0.0)) is True
    primary_bounds = artifacts.primary_shape.bounding_box()
    assert primary_bounds.size.X == pytest.approx(205.7)
    assert primary_bounds.size.Y == pytest.approx(31.6)
    assert primary_bounds.size.Z == pytest.approx(0.37)


def test_secondary_step_round_trip_contains_only_two_secondary_bodies(
    tmp_path: Path,
) -> None:
    step_path = tmp_path / "lgevdd_secondary.step"
    artifacts = export_lgevdd_secondary_step(
        source_toml_path=DEFAULT_SOURCE_TOML_PATH,
        step_path=step_path,
    )

    assert artifacts.step_path == step_path.resolve()
    assert step_path.stat().st_size > 0
    assert len(tuple(artifacts.scene_shape.solids())) == 2
    assert len(artifacts.secondary_shapes) == 2
    assert {child.label for child in artifacts.scene_shape.children} == set(
        artifacts.spec.secondary.body_ids
    )
    assert {
        artifacts.spec.fr4.object_id,
        artifacts.spec.primary.object_id,
    }.isdisjoint(child.label for child in artifacts.scene_shape.children)


def test_both_step_round_trip_contains_fr4_and_all_three_windings(
    tmp_path: Path,
) -> None:
    step_path = tmp_path / "lgevdd_both.step"
    artifacts = export_lgevdd_both_step(
        source_toml_path=DEFAULT_SOURCE_TOML_PATH,
        step_path=step_path,
    )

    assert artifacts.step_path == step_path.resolve()
    assert step_path.stat().st_size > 0
    assert len(tuple(artifacts.scene_shape.solids())) == 4
    assert len(artifacts.secondary_shapes) == 2
    assert {child.label for child in artifacts.scene_shape.children} == {
        artifacts.spec.fr4.object_id,
        artifacts.spec.primary.object_id,
        *artifacts.spec.secondary.body_ids,
    }
    assert artifacts.primary_shape.distance_to(artifacts.secondary_shapes[0]) > 0.0
    assert artifacts.primary_shape.distance_to(artifacts.secondary_shapes[1]) > 0.0


def test_constraint_evaluator_rejects_too_short_primary_lead(tmp_path: Path) -> None:
    invalid_toml = _modified_toml(
        tmp_path,
        old=(
            "[modeled_objects.lead_extension_x_mm]\n"
            "range = [false, 40.0, 40.0, 1]\n"
            'description = "Positive-X terminal lead extension from the keepout edge(mm)"'
        ),
        new=(
            "[modeled_objects.lead_extension_x_mm]\n"
            "range = [false, 10.0, 10.0, 1]\n"
            'description = "Positive-X terminal lead extension from the keepout edge(mm)"'
        ),
        name="short_lead.toml",
    )

    with pytest.raises(
        ValueError,
        match="constraint 'primary_lead_outside_outer_turn' failed",
    ):
        load_lgevdd_pcb_spec(invalid_toml)


def test_constraint_evaluator_rejects_secondary_radial_build_outside_window(
    tmp_path: Path,
) -> None:
    invalid_toml = _modified_toml(
        tmp_path,
        old="range = [false, 7.7, 7.7, 1]\ndescription = \"Secondary planar trace width(mm)\"",
        new="range = [false, 30.0, 30.0, 1]\ndescription = \"Secondary planar trace width(mm)\"",
        name="wide_secondary.toml",
    )

    with pytest.raises(
        ValueError,
        match="constraint 'secondary_radial_build_x_within_window' failed",
    ):
        load_lgevdd_pcb_spec(invalid_toml)


def test_constraint_evaluator_rejects_center_hole_as_wide_as_fr4(
    tmp_path: Path,
) -> None:
    invalid_toml = _modified_toml(
        tmp_path,
        old="range = [false, 146.0, 146.0, 1]",
        new="range = [false, 240.0, 240.0, 1]",
        name="wide_center_hole.toml",
    )

    with pytest.raises(
        ValueError,
        match="constraint 'fr4_center_hole_x_within_board' failed",
    ):
        load_lgevdd_pcb_spec(invalid_toml)


def test_constraint_evaluator_rejects_unknown_function(tmp_path: Path) -> None:
    invalid_toml = _modified_toml(
        tmp_path,
        old=(
            'lhs = { func = "primary_planar_radial_build_x('
            'primary_planar_coil)" }'
        ),
        new=(
            'lhs = { func = "unregistered_geometry_function('
            'primary_planar_coil)" }'
        ),
        name="unknown_function.toml",
    )

    with pytest.raises(ValueError, match="func must be one of"):
        load_lgevdd_pcb_spec(invalid_toml)


def test_fixed_parser_rejects_non_fixed_turn_range(tmp_path: Path) -> None:
    invalid_toml = _modified_toml(
        tmp_path,
        old="range = [true, 14, 14, 1]",
        new="range = [true, 12, 16, 3]",
        name="turn_sweep.toml",
    )

    with pytest.raises(ValueError, match="must be fixed"):
        load_lgevdd_pcb_spec(invalid_toml)


def test_ocp_view_uses_fr4_and_copper_colors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifacts = export_lgevdd_pcb_step(
        source_toml_path=DEFAULT_SOURCE_TOML_PATH,
        step_path=tmp_path / "lgevdd_pcb.step",
    )
    captured: dict[str, object] = {}

    def _capture_show(*cad_objects: object, **kwargs: object) -> None:
        captured["cad_objects"] = cad_objects
        captured["kwargs"] = kwargs

    monkeypatch.setattr(dev_module, "show", _capture_show)
    show_lgevdd_pcb_in_ocp(artifacts=artifacts, ocp_port=3940)

    assert captured["cad_objects"] == (
        artifacts.fr4_shape,
        artifacts.primary_shape,
    )
    raw_kwargs = captured["kwargs"]
    assert isinstance(raw_kwargs, dict)
    assert raw_kwargs["colors"] == [FR4_OCP_COLOR, COPPER_OCP_COLOR]
    assert raw_kwargs["alphas"] == [0.65, 1.0]
    assert raw_kwargs["port"] == 3940


def test_secondary_ocp_view_uses_only_two_copper_bodies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifacts = export_lgevdd_secondary_step(
        source_toml_path=DEFAULT_SOURCE_TOML_PATH,
        step_path=tmp_path / "lgevdd_secondary.step",
    )
    captured: dict[str, object] = {}

    def _capture_show(*cad_objects: object, **kwargs: object) -> None:
        captured["cad_objects"] = cad_objects
        captured["kwargs"] = kwargs

    monkeypatch.setattr(dev_module, "show", _capture_show)
    show_lgevdd_secondary_in_ocp(artifacts=artifacts, ocp_port=3940)

    assert captured["cad_objects"] == artifacts.secondary_shapes
    raw_kwargs = captured["kwargs"]
    assert isinstance(raw_kwargs, dict)
    assert raw_kwargs["names"] == list(artifacts.spec.secondary.body_ids)
    assert raw_kwargs["colors"] == [COPPER_OCP_COLOR, COPPER_OCP_COLOR]
    assert raw_kwargs["alphas"] == [1.0, 1.0]
    assert raw_kwargs["port"] == 3940


def test_both_ocp_view_uses_fr4_and_all_three_windings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifacts = export_lgevdd_both_step(
        source_toml_path=DEFAULT_SOURCE_TOML_PATH,
        step_path=tmp_path / "lgevdd_both.step",
    )
    captured: dict[str, object] = {}

    def _capture_show(*cad_objects: object, **kwargs: object) -> None:
        captured["cad_objects"] = cad_objects
        captured["kwargs"] = kwargs

    monkeypatch.setattr(dev_module, "show", _capture_show)
    show_lgevdd_both_in_ocp(artifacts=artifacts, ocp_port=3940)

    assert captured["cad_objects"] == (
        artifacts.fr4_shape,
        artifacts.primary_shape,
        *artifacts.secondary_shapes,
    )
    raw_kwargs = captured["kwargs"]
    assert isinstance(raw_kwargs, dict)
    assert raw_kwargs["names"] == [
        artifacts.spec.fr4.object_id,
        artifacts.spec.primary.object_id,
        *artifacts.spec.secondary.body_ids,
    ]
    assert raw_kwargs["colors"] == [
        FR4_OCP_COLOR,
        COPPER_OCP_COLOR,
        COPPER_OCP_COLOR,
        COPPER_OCP_COLOR,
    ]
    assert raw_kwargs["alphas"] == [0.65, 1.0, 1.0, 1.0]
    assert raw_kwargs["port"] == 3940
