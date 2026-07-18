from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from peetsfea.aedt.protocols import HfssSession
from peetsfea.backend.pyaedt.minimal_em import setup_minimal_step_ledger, setup_minimal_step_ledger_into_hfss
from peetsfea.minimal_step import MinimalStepLedger, export_minimal_step_artifacts, load_minimal_step_ledger
from peetsfea.minimal_spec import SCHEMA_ID, SPEC_VERSION


def _write_spec(tmp_path: Path) -> Path:
    path = tmp_path / "spec.toml"
    path.write_text(
        f"""
spec_version = "{SPEC_VERSION}"
schema_id = "{SCHEMA_ID}"

[design]
units = "mm"

[[non_model_objects]]
id = "air_context"
kind = "air_context"
primitive = "box"
present = true
non_model = true
material = "vacuum"
plane = "XY"
origin_xyz = [-100.0, -75.0, -25.0]
size_xyz = [200.0, 150.0, 50.0]
""",
        encoding="utf-8",
    )
    return path


class _FakeBoundaryModule:
    def __init__(self, parent: "_FakeHfss") -> None:
        self._parent = parent
        self.assign_lumped_port_calls: list[list[object]] = []
        self.boundary_names: list[str] = []
        self.assign_result: object = True

    def AssignLumpedPort(self, props: list[object]) -> object:
        self.assign_lumped_port_calls.append(list(props))
        if self.assign_result is False:
            return False
        raw_name = props[0]
        assert isinstance(raw_name, str)
        boundary_name = raw_name.removeprefix("NAME:")
        self.boundary_names.append(boundary_name)
        self._parent.excitation_names.append(f"{boundary_name}_T1")
        return True

    def GetBoundaries(self) -> list[str]:
        return list(self.boundary_names)


class _FakeMeshModule:
    def __init__(self) -> None:
        self.assign_length_calls: list[list[object]] = []

    def AssignLengthOp(self, props: list[object]) -> object:
        self.assign_length_calls.append(list(props))
        return True


class _FakeAnalysisSetupModule:
    def __init__(self, parent: "_FakeHfss") -> None:
        self._parent = parent

    def InsertSetup(self, setup_type: str, props: list[object]) -> object:
        self._parent.insert_setup_calls.append((setup_type, list(props)))
        return True

    def InsertFrequencySweep(self, setup_name: str, props: list[object]) -> object:
        self._parent.insert_sweep_calls.append((setup_name, list(props)))
        return True


class _FakeSolutionsModule:
    def __init__(self, parent: "_FakeHfss") -> None:
        self._parent = parent

    def EditSources(self, payload: list[object]) -> object:
        self._parent.edit_sources_calls.append(list(payload))
        return True


class _FakeReportSetupModule:
    def __init__(self, parent: "_FakeHfss") -> None:
        self._parent = parent

    def CreateReport(
        self,
        plot_name: str,
        report_category: str,
        plot_type: str,
        setup_sweep_name: str,
        context: list[object],
        variations: list[object],
        components: list[object],
        options: list[object],
    ) -> object:
        del options
        self._parent.create_report_calls.append(
            {
                "plot_name": plot_name,
                "report_category": report_category,
                "plot_type": plot_type,
                "setup_sweep_name": setup_sweep_name,
                "context": list(context),
                "variations": list(variations),
                "components": list(components),
            }
        )
        return True

    def ExportToFile(self, report_name: str, export_path: str) -> object:
        self._parent.export_report_calls.append((report_name, export_path))
        Path(export_path).write_text("Freq,S21_mag_ratio\n1,0\n", encoding="utf-8")
        return True

    def GetAllReportNames(self) -> list[str]:
        return [cast(str, call["plot_name"]) for call in self._parent.create_report_calls]


class _FakeDesign:
    def __init__(self, parent: "_FakeHfss") -> None:
        self._parent = parent
        self.mesh_module = _FakeMeshModule()
        self.validate_design_calls = 0

    def GetModule(self, name: str) -> object:
        if name == "MeshSetup":
            return self.mesh_module
        if name == "AnalysisSetup":
            return _FakeAnalysisSetupModule(self._parent)
        if name == "Solutions":
            return _FakeSolutionsModule(self._parent)
        if name == "ReportSetup":
            return _FakeReportSetupModule(self._parent)
        raise ValueError(f"unexpected module: {name}")

    def ValidateDesign(self) -> object:
        self.validate_design_calls += 1
        return True


class _FakeDesktop:
    def __init__(self) -> None:
        self.release_calls: list[tuple[bool, bool]] = []

    def GetMessages(self, project_name: str, design_name: str, level: int) -> list[str]:
        del project_name, design_name, level
        return []

    def release_desktop(self, close_projects: bool, close_on_exit: bool) -> object:
        self.release_calls.append((close_projects, close_on_exit))
        return True


class _FakeMaterials:
    def __init__(self) -> None:
        self.exists_material_calls: list[str] = []

    def exists_material(self, name: str) -> object:
        self.exists_material_calls.append(name)
        return name in {"copper", "vacuum"}


class _FakeModelObject:
    def __init__(self, name: str) -> None:
        self.name = name
        self.material_name = ""
        self.color: tuple[int, int, int] = (0, 0, 0)
        self.transparency = 0.0


class _FakeModeler:
    def __init__(self, ledger: MinimalStepLedger) -> None:
        self._ledger = ledger
        self._object_names: list[str] = []
        self._objects: dict[str, _FakeModelObject] = {}
        self.import_calls: list[Path] = []
        self.import_kwargs: list[dict[str, object]] = []
        self.set_model_state_calls: list[tuple[str, bool]] = []
        self.create_region_calls: list[dict[str, object]] = []
        self._object_edges: dict[str, list[int]] = {}
        self._edge_vertices: dict[int, tuple[int, int]] = {}
        self._vertex_positions: dict[int, tuple[float, float, float]] = {}
        self._next_edge_id = 1
        self._next_vertex_id = 1

    @property
    def object_names(self) -> list[str]:
        return list(self._object_names)

    def import_3d_cad(self, input_file: Path, **kwargs: object) -> object:
        self.import_calls.append(input_file)
        self.import_kwargs.append(dict(kwargs))
        self._object_names.extend(self._ledger["body_names"])
        for object_name in self._ledger["body_names"]:
            self._objects[object_name] = _FakeModelObject(object_name)
        for cell in self._ledger["port_cells"]:
            self._seed_sheet_edges(cell["port_sheet_name"], cell["port_sheet_vertices_xyz"])
        return True

    def get_object_from_name(self, assignment: str) -> object:
        if assignment not in self._objects:
            return False
        return self._objects[assignment]

    def _seed_sheet_edges(self, sheet_name: str, vertices: list[list[float]]) -> None:
        vertex_ids: list[int] = []
        for raw_vertex in vertices:
            vertex_id = self._next_vertex_id
            self._next_vertex_id += 1
            self._vertex_positions[vertex_id] = (float(raw_vertex[0]), float(raw_vertex[1]), float(raw_vertex[2]))
            vertex_ids.append(vertex_id)
        edge_ids: list[int] = []
        for first_id, second_id in zip(vertex_ids, [*vertex_ids[1:], vertex_ids[0]], strict=True):
            edge_id = self._next_edge_id
            self._next_edge_id += 1
            self._edge_vertices[edge_id] = (first_id, second_id)
            edge_ids.append(edge_id)
        self._object_edges[sheet_name] = edge_ids

    def set_object_model_state(self, name: str, model: bool) -> object:
        self.set_model_state_calls.append((name, model))
        return True

    def get_object_edges(self, assignment: str) -> list[int]:
        if assignment not in self._object_edges:
            return []
        return list(self._object_edges[assignment])

    def get_edge_vertices(self, assignment: int) -> list[int]:
        first_id, second_id = self._edge_vertices[assignment]
        return [first_id, second_id]

    def get_vertex_position(self, assignment: int) -> list[float]:
        x, y, z = self._vertex_positions[assignment]
        return [x, y, z]

    def create_region(self, pad_value: int, pad_type: str, name: str) -> object:
        self.create_region_calls.append({"pad_value": pad_value, "pad_type": pad_type, "name": name})
        self._object_names.append(name)
        self._objects[name] = _FakeModelObject(name)
        return _FakeObject(name)

    def get_object_faces(self, assignment: str) -> list[int]:
        del assignment
        return [1, 2, 3, 4, 5, 6]


class _FakeObject:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeHfss:
    def __init__(self, ledger: MinimalStepLedger) -> None:
        self.modeler = _FakeModeler(ledger)
        self.odesign = _FakeDesign(self)
        self.desktop_class = _FakeDesktop()
        self.materials = _FakeMaterials()
        self.oboundary = _FakeBoundaryModule(self)
        self.excitation_names: list[str] = []
        self.setup_names: list[str] = []
        self.insert_setup_calls: list[tuple[str, list[object]]] = []
        self.insert_sweep_calls: list[tuple[str, list[object]]] = []
        self.edit_sources_calls: list[list[object]] = []
        self.create_output_variables: list[tuple[str, str, str]] = []
        self.create_report_calls: list[dict[str, object]] = []
        self.export_report_calls: list[tuple[str, str]] = []
        self.radiation_calls: list[tuple[object, str]] = []
        self.validation_settings_calls: list[tuple[str, bool, bool]] = []
        self.delete_setup_calls: list[str] = []
        self.saved_paths: list[str] = []
        self.get_traces_for_plot_calls: list[dict[str, object]] = []
        self.assign_material_calls: list[tuple[str, str]] = []

    def assign_material(self, assignment: str | list[str], material: str) -> object:
        if not isinstance(assignment, str):
            raise TypeError("fake assign_material expects one object name")
        self.assign_material_calls.append((assignment, material))
        raw_object = self.modeler.get_object_from_name(assignment)
        assert isinstance(raw_object, _FakeModelObject)
        raw_object.material_name = material
        return True

    def assign_radiation_boundary_to_faces(self, assignment: object, name: str) -> object:
        self.radiation_calls.append((assignment, name))
        return True

    def create_output_variable(self, variable: str, expression: str, solution: str) -> object:
        self.create_output_variables.append((variable, expression, solution))
        return True

    def save_project(self, path: str) -> object:
        self.saved_paths.append(path)
        return True

    def analyze_setup(self, name: str, blocking: bool = True) -> object:
        del name, blocking
        return True

    def change_validation_settings(
        self,
        entity_check_level: str = "Strict",
        ignore_unclassified: bool = False,
        skip_intersections: bool = False,
    ) -> object:
        self.validation_settings_calls.append((entity_check_level, ignore_unclassified, skip_intersections))
        return True

    def delete_setup(self, name: str) -> object:
        self.delete_setup_calls.append(name)
        return True

    def get_traces_for_plot(
        self,
        get_self_terms: bool,
        get_mutual_terms: bool,
        first_element_filter: str,
        second_element_filter: str,
        category: str,
        differential_pairs: list[object],
    ) -> list[str]:
        self.get_traces_for_plot_calls.append(
            {
                "get_self_terms": get_self_terms,
                "get_mutual_terms": get_mutual_terms,
                "first_element_filter": first_element_filter,
                "second_element_filter": second_element_filter,
                "category": category,
                "differential_pairs": list(differential_pairs),
            }
        )
        return ["St(1_T1,1_T1)", "St(1_T1,2_T1)", "St(2_T1,2_T1)"]


def _ledger_path(tmp_path: Path) -> Path:
    spec_path = _write_spec(tmp_path)
    artifacts = export_minimal_step_artifacts(source_toml_path=spec_path, output_dir=tmp_path)
    return Path(artifacts["ledger_path"])


def test_setup_minimal_step_ledger_into_hfss_creates_two_port_setup(tmp_path: Path) -> None:
    ledger_path = _ledger_path(tmp_path)
    ledger = load_minimal_step_ledger(ledger_path)
    hfss = _FakeHfss(ledger)

    result = setup_minimal_step_ledger_into_hfss(
        hfss=cast(HfssSession, hfss),
        step_ledger_path=ledger_path,
        output_aedt_path=tmp_path / "minimal.aedt",
        imported_ledger_path=tmp_path / "minimal_imported_ledger.json",
    )

    assert hfss.modeler.import_calls == [Path(ledger["scene_step_path"])]
    assert hfss.modeler.import_kwargs == [{"create_group": False, "import_free_surfaces": True, "import_materials": False}]
    assert hfss.modeler.set_model_state_calls == [("air_context", False)]
    expected_material_assignments = {body["object_id"]: body["material"] for body in ledger["bodies"]}
    assert hfss.materials.exists_material_calls == [
        expected_material_assignments[body_name] for body_name in ledger["body_names"]
    ]
    assert hfss.assign_material_calls == [
        (body_name, expected_material_assignments[body_name]) for body_name in ledger["body_names"]
    ]
    for copper_body_name in ledger["copper_body_names"]:
        raw_object = hfss.modeler.get_object_from_name(copper_body_name)
        assert isinstance(raw_object, _FakeModelObject)
        assert raw_object.material_name == "copper"
        assert raw_object.color == (184, 115, 51)
        assert raw_object.transparency == 0.0
    air_context = hfss.modeler.get_object_from_name("air_context")
    assert isinstance(air_context, _FakeModelObject)
    assert air_context.color == (128, 128, 128)
    assert air_context.transparency == 0.85
    for port_sheet_name in ledger["port_sheet_names"]:
        port_sheet = hfss.modeler.get_object_from_name(port_sheet_name)
        assert isinstance(port_sheet, _FakeModelObject)
        assert port_sheet.color == (180, 215, 255)
        assert port_sheet.transparency == 0.88
    mesh_payload = hfss.odesign.mesh_module.assign_length_calls[0]
    assert mesh_payload[mesh_payload.index("Objects:=") + 1] == ledger["copper_body_names"]
    assert [call[0] for call in hfss.oboundary.assign_lumped_port_calls] == ["NAME:1", "NAME:2"]
    assert result["ports"] == {"tx": ["1_T1"], "rx": ["2_T1"]}
    setup_payload = hfss.insert_setup_calls[0][1]
    assert setup_payload[setup_payload.index("MaxDeltaS:=") + 1] == 0.0017
    assert setup_payload[setup_payload.index("MaximumPasses:=") + 1] == 22
    assert setup_payload[setup_payload.index("MinimumPasses:=") + 1] == 20
    assert setup_payload[setup_payload.index("MinimumConvergedPasses:=") + 1] == 21
    assert setup_payload[setup_payload.index("PercentRefinement:=") + 1] == 25
    assert setup_payload[setup_payload.index("BasisOrder:=") + 1] == 0
    assert setup_payload[setup_payload.index("DoLambdaRefine:=") + 1] is False
    assert setup_payload[setup_payload.index("DoMaterialLambda:=") + 1] is True
    assert setup_payload[setup_payload.index("Target:=") + 1] == 0.1
    assert setup_payload[setup_payload.index("DrivenSolverType:=") + 1] == "Direct Solver"
    assert setup_payload[setup_payload.index("SaveAnyFields:=") + 1] is True
    assert any(isinstance(item, list) and item == ["NAME:MeshLink", "ImportMesh:=", False] for item in setup_payload)
    assert hfss.insert_sweep_calls[0][0] == "Setup1"
    sweep_payload = hfss.insert_sweep_calls[0][1]
    assert sweep_payload[sweep_payload.index("RangeSamples:=") + 1] == 100
    assert sweep_payload[sweep_payload.index("SMatrixOnlySolveMode:=") + 1] == "Auto"
    assert any(isinstance(item, list) and item[0] == "NAME:SweepRanges" for item in sweep_payload)
    assert hfss.edit_sources_calls
    assert [name for name, _expression, _solution in hfss.create_output_variables] == [
        "Ltx_uH",
        "Lrx_uH",
        "M_uH",
        "k_ratio",
        "Qtx_ratio",
        "Qrx_ratio",
        "FOM_ratio",
        "Rtx_ac_ohm",
        "Rrx_ac_ohm",
        "Xtx_ohm",
        "Xrx_ohm",
        "M_over_Ltx_ratio",
        "M_over_Lrx_ratio",
        "Gtx_S",
        "Btx_S",
        "Grx_S",
        "Brx_S",
        "S11_mag_ratio",
        "S21_mag_ratio",
        "S21_phase_deg",
        "S22_mag_ratio",
        "eta_s21_power_ratio",
        "eta_tx_accept_ratio",
        "eta_rx_accept_ratio",
        "eta_match_product_ratio",
        "eta_s21_from_tx_accept_ratio",
        "eta_s21_from_rx_accept_ratio",
        "eta_s21_two_sided_norm_ratio",
        "eta_fom_max_ratio",
    ]
    assert ("S21_mag_ratio", "mag(St(1_T1,2_T1))", "Setup1 : Sweep") in hfss.create_output_variables
    assert [call["plot_name"] for call in hfss.create_report_calls] == ["Output Variables Table1", "Table1", "Table2"]
    output_report_components = cast(list[object], hfss.create_report_calls[0]["components"])
    assert output_report_components[output_report_components.index("Y Component:=") + 1] == [
        name for name, _expression, _solution in hfss.create_output_variables
    ]
    diagnostic_components = cast(list[object], hfss.create_report_calls[1]["components"])
    diagnostic_traces = cast(list[object], diagnostic_components[diagnostic_components.index("Y Component:=") + 1])
    assert "Volume(tx_signal_pad)" in diagnostic_traces
    assert "Area(rx_port_sheet)" in diagnostic_traces
    assert "Volume(Region_Abs_2000mm)" in diagnostic_traces
    adaptive_pass_components = cast(list[object], hfss.create_report_calls[2]["components"])
    assert adaptive_pass_components[adaptive_pass_components.index("X Component:=") + 1] == "Pass"
    adaptive_pass_traces = cast(list[object], adaptive_pass_components[adaptive_pass_components.index("Y Component:=") + 1])
    assert adaptive_pass_traces[-2:] == ["SolvedElements", "MaxMagDeltaS"]
    assert hfss.create_report_calls[2]["variations"] == ["Pass:=", ["All"], "Freq:=", ["All"]]
    assert result["reports"] == ["Output Variables Table1", "Table1", "Table2"]
    assert hfss.validation_settings_calls == [("None", False, False)]
    assert hfss.odesign.validate_design_calls == 1
    assert hfss.saved_paths == [str(tmp_path / "minimal.aedt")]
    imported = json.loads((tmp_path / "minimal_imported_ledger.json").read_text(encoding="utf-8"))
    assert imported["copper_body_names"] == ledger["copper_body_names"]
    assert imported["material_assignments"] == expected_material_assignments
    assert imported["visual_assignments"]["air_context"] == {"color": [128, 128, 128], "transparency": 0.85}
    assert imported["visual_assignments"]["tx_signal_pad"] == {"color": [184, 115, 51], "transparency": 0.0}
    assert imported["visual_assignments"]["tx_port_sheet"] == {"color": [180, 215, 255], "transparency": 0.88}


def test_setup_minimal_step_ledger_into_hfss_raises_on_port_assignment_false(tmp_path: Path) -> None:
    ledger_path = _ledger_path(tmp_path)
    hfss = _FakeHfss(load_minimal_step_ledger(ledger_path))
    hfss.oboundary.assign_result = False

    with pytest.raises(RuntimeError, match="AssignLumpedPort"):
        setup_minimal_step_ledger_into_hfss(
            hfss=cast(HfssSession, hfss),
            step_ledger_path=ledger_path,
            output_aedt_path=tmp_path / "minimal.aedt",
            imported_ledger_path=tmp_path / "minimal_imported_ledger.json",
        )


def test_setup_minimal_step_ledger_releases_desktop_by_default(tmp_path: Path) -> None:
    ledger_path = _ledger_path(tmp_path)
    hfss = _FakeHfss(load_minimal_step_ledger(ledger_path))

    def _factory(design_name: str) -> HfssSession:
        assert design_name == "minimal_gui_test"
        return cast(HfssSession, hfss)

    setup_minimal_step_ledger(
        step_ledger_path=ledger_path,
        output_aedt_path=tmp_path / "minimal.aedt",
        imported_ledger_path=tmp_path / "minimal_imported_ledger.json",
        design_name="minimal_gui_test",
        hfss_factory=_factory,
    )

    assert hfss.desktop_class.release_calls == [(True, True)]


def test_setup_minimal_step_ledger_can_leave_graphical_desktop_open(tmp_path: Path) -> None:
    ledger_path = _ledger_path(tmp_path)
    hfss = _FakeHfss(load_minimal_step_ledger(ledger_path))

    def _factory(design_name: str) -> HfssSession:
        assert design_name == "minimal_gui_test"
        return cast(HfssSession, hfss)

    setup_minimal_step_ledger(
        step_ledger_path=ledger_path,
        output_aedt_path=tmp_path / "minimal.aedt",
        imported_ledger_path=tmp_path / "minimal_imported_ledger.json",
        design_name="minimal_gui_test",
        hfss_factory=_factory,
        release_desktop_on_exit=False,
    )

    assert hfss.desktop_class.release_calls == []
