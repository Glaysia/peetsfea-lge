from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import cast

import pytest

from peetsfea.ssw_aedt_artifacts import (
    AEDT_IMPORTED_LEDGER_NAME,
    AEDT_PORT_LEDGER_NAME,
    SOURCE_TOML_PATH,
    export_ssw_aedt_port_artifacts,
)
from peetsfea.aedt.protocols import HfssSession
import peetsfea.backend.pyaedt.ssw_ports as ssw_ports
from peetsfea.backend.pyaedt.ssw_ports import (
    SSW_REPORT_NAMES,
    SswAedtBodyLedgerEntry,
    SswAedtPortStepLedger,
    adaptive_mesh_max_length_mm,
    setup_ssw_aedt_ports,
    setup_ssw_aedt_ports_into_hfss,
    solve_ssw_aedt_ports,
    write_ssw_aedt_port_ledger,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = REPO_ROOT / "run"


class _FakeBoundaryModule:
    def __init__(self, parent: "_FakeHfss") -> None:
        self._parent = parent
        self.assign_lumped_port_calls: list[list[object]] = []
        self.assign_result: object = True

    def AssignLumpedPort(self, props: list[object]) -> object:
        self.assign_lumped_port_calls.append(list(props))
        if self.assign_result is False:
            return False
        raw_name = props[0]
        assert isinstance(raw_name, str)
        boundary_name = raw_name.removeprefix("NAME:")
        self._parent.excitation_names.append(f"{boundary_name}_T1")
        return True

    def GetBoundaries(self) -> list[str]:
        return []


class _FakeDesktop:
    def __init__(self) -> None:
        self.aedt_process_id = os.getpid()
        self.release_calls: list[tuple[bool, bool]] = []

    def release_desktop(self, close_projects: bool, close_on_exit: bool) -> object:
        self.release_calls.append((close_projects, close_on_exit))
        return True


class _FakeMaterials:
    def __init__(self) -> None:
        self.exists_material_calls: list[str] = []
        self.add_material_calls: list[str] = []
        self.aedmattolibrary_calls: list[str] = []
        self.material_keys: dict[str, _FakeMaterial] = {
            "copper": _FakeMaterial(),
            "vacuum": _FakeMaterial(),
        }

    def exists_material(self, name: str) -> object:
        self.exists_material_calls.append(name)
        return name.casefold() in self.material_keys

    def add_material(self, name: str) -> object:
        self.add_material_calls.append(name)
        material = _FakeMaterial(name=name)
        self.material_keys[name.casefold()] = material
        return material

    def _aedmattolibrary(self, name: str) -> object:
        self.aedmattolibrary_calls.append(name)
        self.material_keys[name.casefold()] = _FakeMaterial(name=name)
        return self.material_keys[name.casefold()]


class _FakeMaterial:
    def __init__(self, *, name: str = "") -> None:
        self.name = name


class _FakeDefinitionManager:
    def __init__(self) -> None:
        self.material_names: list[str] = []
        self.add_material_calls: list[list[object]] = []
        self.edit_material_calls: list[tuple[str, list[object]]] = []

    def GetProjectMaterialNames(self) -> list[str]:
        return list(self.material_names)

    def AddMaterial(self, payload: list[object]) -> object:
        self.add_material_calls.append(payload)
        raw_name = payload[0]
        assert isinstance(raw_name, str)
        self.material_names.append(raw_name.removeprefix("NAME:"))
        return True

    def EditMaterial(self, name: str, payload: list[object]) -> object:
        self.edit_material_calls.append((name, payload))
        return True


class _FakeProject:
    def __init__(self) -> None:
        self.definition_manager = _FakeDefinitionManager()
        self.add_dataset_calls: list[list[object]] = []

    def GetDefinitionManager(self) -> _FakeDefinitionManager:
        return self.definition_manager

    def AddDataset(self, payload: list[object]) -> object:
        self.add_dataset_calls.append(payload)
        return True


class _FakeDesign:
    def __init__(self) -> None:
        self.import_dataset_calls: list[str] = []
        self.mesh_module = _FakeMeshModule()
        self.analysis_setup_module = _FakeAnalysisSetupModule()
        self.report_setup_module = _FakeReportSetupModule()
        self.solutions_module = _FakeSolutionsModule()
        self.fields_reporter_module = _FakeFieldsReporterModule()

    def ImportDataset(self, path: str) -> object:
        self.import_dataset_calls.append(path)
        return True

    def GetModule(self, name: str) -> object:
        if name == "MeshSetup":
            return self.mesh_module
        if name == "AnalysisSetup":
            return self.analysis_setup_module
        if name == "ReportSetup":
            return self.report_setup_module
        if name == "Solutions":
            return self.solutions_module
        if name == "FieldsReporter":
            return self.fields_reporter_module
        raise ValueError(f"unsupported fake module {name!r}")

    def ValidateDesign(self) -> object:
        return True


class _FakeMeshModule:
    def __init__(self) -> None:
        self.assign_length_calls: list[list[object]] = []
        self.assign_result: object = True

    def AssignLengthOp(self, props: list[object]) -> object:
        self.assign_length_calls.append(list(props))
        return self.assign_result


class _FakeAnalysisSetupModule:
    def __init__(self) -> None:
        self.insert_setup_calls: list[tuple[str, list[object]]] = []
        self.insert_sweep_calls: list[tuple[str, list[object]]] = []
        self.insert_setup_result: object = True
        self.insert_sweep_result: object = True

    def InsertSetup(self, setup_type: str, props: list[object]) -> object:
        self.insert_setup_calls.append((setup_type, list(props)))
        return self.insert_setup_result

    def InsertFrequencySweep(self, setup_name: str, props: list[object]) -> object:
        self.insert_sweep_calls.append((setup_name, list(props)))
        return self.insert_sweep_result


class _FakeSolutionsModule:
    def __init__(self) -> None:
        self.edit_sources_calls: list[list[object]] = []
        self.edit_sources_result: object = True

    def EditSources(self, payload: list[object]) -> object:
        self.edit_sources_calls.append(list(payload))
        return self.edit_sources_result


class _FakeReportSetupModule:
    def __init__(self) -> None:
        self.create_report_calls: list[dict[str, object]] = []
        self.export_to_file_calls: list[tuple[str, str]] = []
        self.create_report_result: object = True
        self.export_to_file_result: object = True
        self.write_exported_file = True
        self.report_names_result: object = True

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
        self.create_report_calls.append(
            {
                "plot_name": plot_name,
                "report_category": report_category,
                "plot_type": plot_type,
                "setup_sweep_name": setup_sweep_name,
                "context": list(context),
                "variations": list(variations),
                "components": list(components),
                "options": list(options),
            }
        )
        return self.create_report_result

    def GetAllReportNames(self) -> object:
        if self.report_names_result is False:
            return ["Results1_Pass"]
        return [cast(str, call["plot_name"]) for call in self.create_report_calls]

    def ExportToFile(self, report_name: str, export_path: str) -> object:
        self.export_to_file_calls.append((report_name, export_path))
        if self.export_to_file_result is False:
            return False
        if self.write_exported_file:
            Path(export_path).write_text(f"Freq,{report_name}\n6.78MHz,0\n", encoding="utf-8")
        return True


class _FakeFieldsReporterModule:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.add_named_expression_result: object = True

    def CalcStack(self, command: str) -> object:
        self.calls.append(("CalcStack", command))
        return True

    def CopyNamedExprToStack(self, expression_name: str) -> object:
        self.calls.append(("CopyNamedExprToStack", expression_name))
        return True

    def EnterVol(self, assignment: str) -> object:
        self.calls.append(("EnterVol", assignment))
        return True

    def CalcOp(self, operation: str) -> object:
        self.calls.append(("CalcOp", operation))
        return True

    def AddNamedExpression(self, expression_name: str, field_type: str) -> object:
        self.calls.append(("AddNamedExpression", (expression_name, field_type)))
        if self.add_named_expression_result is False:
            return False
        return True


class _FakeModelObject:
    def __init__(self, name: str) -> None:
        self.name = name
        self.material_name = ""
        self.solve_inside = False
        self.color: tuple[int, int, int] = (0, 0, 0)
        self.transparency = 0.0


class _FakeModeler:
    def __init__(self, ledger: SswAedtPortStepLedger) -> None:
        self._ledger = ledger
        self._object_names: list[str] = []
        self._objects: dict[str, _FakeModelObject] = {}
        self.import_calls: list[Path] = []
        self.import_kwargs: list[dict[str, object]] = []
        self.create_region_calls: list[dict[str, object]] = []
        self.create_region_result: object = True
        self.region_face_ids: list[int] = [301, 302, 303, 304, 305, 306]
        self.set_model_state_calls: list[tuple[str, bool]] = []
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
        self._seed_copper_port_edges()
        return True

    def create_region(self, pad_value: int, pad_type: str, name: str) -> object:
        self.create_region_calls.append({"pad_value": pad_value, "pad_type": pad_type, "name": name})
        if self.create_region_result is False:
            return False
        self._object_names.append(name)
        region = _FakeModelObject(name)
        self._objects[name] = region
        return region

    def get_object_from_name(self, assignment: str) -> object:
        if assignment not in self._objects:
            return False
        return self._objects[assignment]

    def get_object_faces(self, assignment: str) -> list[int]:
        if assignment not in self._objects:
            return []
        return list(self.region_face_ids)

    def _seed_edge(
        self,
        *,
        object_name: str,
        edge_id: int,
        first_xyz: tuple[float, float, float],
        second_xyz: tuple[float, float, float],
    ) -> None:
        first_vertex_id = self._next_vertex_id
        self._next_vertex_id += 1
        second_vertex_id = self._next_vertex_id
        self._next_vertex_id += 1
        self._vertex_positions[first_vertex_id] = first_xyz
        self._vertex_positions[second_vertex_id] = second_xyz
        self._edge_vertices[edge_id] = (first_vertex_id, second_vertex_id)
        if object_name not in self._object_edges:
            self._object_edges[object_name] = []
        self._object_edges[object_name].append(edge_id)

    def _seed_copper_port_edges(self) -> None:
        self._seed_edge(
            object_name="tx_ssw_coil_ssw_copper",
            edge_id=101,
            first_xyz=(0.0, -1.0, 0.0),
            second_xyz=(10.0, -1.0, 0.0),
        )
        self._seed_edge(
            object_name="tx_ssw_coil_ssw_copper",
            edge_id=102,
            first_xyz=(0.0, 1.0, 0.0),
            second_xyz=(10.0, 1.0, 0.0),
        )
        self._seed_edge(
            object_name="tx_ssw_coil_ssw_copper",
            edge_id=103,
            first_xyz=(0.0, 20.0, 0.0),
            second_xyz=(10.0, 20.0, 0.0),
        )
        self._seed_edge(
            object_name="rx_ssw_coil_coil_copper",
            edge_id=201,
            first_xyz=(9.0, 5.0, 0.0),
            second_xyz=(9.0, 5.0, 5.5),
        )
        self._seed_edge(
            object_name="rx_ssw_coil_coil_copper",
            edge_id=202,
            first_xyz=(9.0, 7.0, 0.0),
            second_xyz=(9.0, 7.0, 5.5),
        )
        self._seed_edge(
            object_name="rx_ssw_coil_coil_copper",
            edge_id=203,
            first_xyz=(10.0, 5.0, 0.0),
            second_xyz=(10.0, 5.0, 5.5),
        )
        self._seed_edge(
            object_name="rx_ssw_coil_coil_copper",
            edge_id=204,
            first_xyz=(10.0, 7.0, 0.0),
            second_xyz=(10.0, 7.0, 5.5),
        )

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


class _FakeHfss:
    def __init__(self, ledger: SswAedtPortStepLedger) -> None:
        self.modeler = _FakeModeler(ledger)
        self.desktop_class = _FakeDesktop()
        self.odesign = _FakeDesign()
        self.oproject = _FakeProject()
        self.materials = _FakeMaterials()
        self.oboundary = _FakeBoundaryModule(self)
        self.excitation_names: list[str] = []
        self.saved_paths: list[str] = []
        self.assign_material_calls: list[tuple[str, str]] = []
        self.radiation_calls: list[tuple[object, str]] = []
        self.assign_radiation_result: object = True
        self.create_output_variables: list[tuple[str, str, str]] = []
        self.create_output_variable_result: object = True
        self.analyze_setup_calls: list[tuple[str, bool]] = []
        self.analyze_setup_result: object = True

    def assign_material(self, assignment: str | list[str], material: str) -> object:
        if not isinstance(assignment, str):
            raise TypeError("fake assign_material expects one object name")
        self.assign_material_calls.append((assignment, material))
        raw_object = self.modeler.get_object_from_name(assignment)
        assert isinstance(raw_object, _FakeModelObject)
        raw_object.material_name = material
        return True

    def create_output_variable(self, variable: str, expression: str, solution: str) -> object:
        self.create_output_variables.append((variable, expression, solution))
        return self.create_output_variable_result

    def assign_radiation_boundary_to_faces(self, assignment: object, name: str) -> object:
        self.radiation_calls.append((assignment, name))
        return self.assign_radiation_result

    def get_traces_for_plot(
        self,
        get_self_terms: bool,
        get_mutual_terms: bool,
        first_element_filter: str,
        second_element_filter: str,
        category: str,
        setup_name: object,
    ) -> list[str]:
        del get_self_terms, get_mutual_terms, first_element_filter, second_element_filter, category, setup_name
        return ["St(1_T1,1_T1)", "St(1_T1,2_T1)", "St(2_T1,2_T1)"]

    def save_project(self, path: str) -> object:
        self.saved_paths.append(path)
        return True

    def analyze_setup(self, name: str, blocking: bool = True, cores: int = 0, gpus: int = 0) -> object:
        self.analyze_setup_calls.append((name, blocking))
        return self.analyze_setup_result


def test_adaptive_mesh_max_length_uses_smaller_half_trace_width() -> None:
    # min(13/2, 9/2) = 4.5mm
    assert adaptive_mesh_max_length_mm(tx_trace_width_mm=13.0, rx_trace_width_mm=9.0) == "4.5mm"


def test_adaptive_mesh_max_length_has_no_floor() -> None:
    # 0.3.9.3 removed the 3mm floor: min(4/2, 5/2) = 2.0 -> 2mm
    assert adaptive_mesh_max_length_mm(tx_trace_width_mm=4.0, rx_trace_width_mm=5.0) == "2mm"


def _body_entry(object_id: str, role: str, material: str, model_state: bool) -> SswAedtBodyLedgerEntry:
    return {
        "object_id": object_id,
        "role": role,
        "material": material,
        "model_state": model_state,
        "canonical_coordinates": {
            "outer_bounds_min_xyz": [0.0, 0.0, 0.0],
            "outer_bounds_max_xyz": [1.0, 1.0, 1.0],
            "outer_bounds_size_xyz": [1.0, 1.0, 1.0],
        },
    }


def _ledger(tmp_path: Path) -> SswAedtPortStepLedger:
    design_space_hash = "1234567890abcdef"
    body_names = [
        "tv",
        "tx_ssw_coil_ssw_copper",
        "rx_ssw_coil_coil_copper",
        "tx_mull_ferrite_sheet",
        "tx_ssw_coil_pcb_1_fr4",
    ]
    return {
        "design_id": f"0_3_1_p{design_space_hash}",
        "aedt_filename": f"0_3_1_p{design_space_hash}.aedt",
        "dimension_count": 18,
        "design_space_hash": design_space_hash,
        "source_step_ledger_path": str(tmp_path / "ssw_step_ledger.json"),
        "scene_step_path": str(tmp_path / "ssw_scene.step"),
        "seed": 0,
        "units": "mm",
        "body_names": body_names,
        "copper_body_names": ["tx_ssw_coil_ssw_copper", "rx_ssw_coil_coil_copper"],
        "fr4_body_names": ["tx_ssw_coil_pcb_1_fr4"],
        "non_model_body_names": ["tv"],
        "ferrite_body_names": ["tx_mull_ferrite_sheet"],
        "bodies": [
            _body_entry("tv", "non_model", "vacuum", False),
            _body_entry("tx_ssw_coil_ssw_copper", "copper", "copper", True),
            _body_entry("rx_ssw_coil_coil_copper", "copper", "copper", True),
            _body_entry("tx_mull_ferrite_sheet", "ferrite", "mull_ferrite", True),
            _body_entry("tx_ssw_coil_pcb_1_fr4", "fr4", "fr4", True),
        ],
        "port_edges": [
            {
                "role": "tx",
                "copper_body_name": "tx_ssw_coil_ssw_copper",
                "selection": "semantic_edge_vertices",
                "edge_vertices_xyz": [
                    [[0.0, -1.0, 0.0], [10.0, -1.0, 0.0]],
                    [[0.0, 1.0, 0.0], [10.0, 1.0, 0.0]],
                ],
            },
            {
                "role": "rx",
                "copper_body_name": "rx_ssw_coil_coil_copper",
                "selection": "semantic_edge_vertices",
                "edge_vertices_xyz": [
                    [[9.0, 5.0, 0.0], [9.0, 5.0, 5.5]],
                    [[9.0, 7.0, 0.0], [9.0, 7.0, 5.5]],
                ],
            },
        ],
        "mesh_max_length": "3.5mm",
    }


def _ledger_path(tmp_path: Path) -> Path:
    ledger = _ledger(tmp_path)
    ledger_path = tmp_path / "ssw_aedt_port_ledger.json"
    write_ssw_aedt_port_ledger(ledger_path=ledger_path, ledger=ledger)
    Path(ledger["scene_step_path"]).write_text("placeholder", encoding="utf-8")
    return ledger_path


def _patch_fake_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssw_ports, "_resolve_host_aedt_process_id", lambda reported_pid: int(reported_pid))


def test_setup_ssw_aedt_ports_into_hfss_creates_tx_rx_terminal_ports(tmp_path: Path) -> None:
    ledger_path = _ledger_path(tmp_path)
    ledger = _ledger(tmp_path)
    hfss = _FakeHfss(ledger)

    result = setup_ssw_aedt_ports_into_hfss(
        hfss=cast(HfssSession, hfss),
        port_ledger_path=ledger_path,
        output_aedt_path=tmp_path / "ssw_ports.aedt",
        imported_ledger_path=tmp_path / "ssw_imported.json",
    )

    assert hfss.modeler.import_calls == [Path(ledger["scene_step_path"])]
    assert hfss.modeler.import_kwargs == [{"create_group": False, "import_free_surfaces": False, "import_materials": False}]
    assert hfss.modeler.set_model_state_calls == [("tv", False)]
    expected_material_assignments = {body["object_id"]: body["material"] for body in ledger["bodies"]}
    expected_material_assignments["tx_mull_ferrite_sheet"] = "MULL12060ferrite"
    assert hfss.materials.exists_material_calls == [
        "vacuum",
        "copper",
        "copper",
        "MULL12060ferrite",
        "fr4",
        "fr4",
    ]
    assert hfss.materials.add_material_calls == ["fr4"]
    assert hfss.materials.aedmattolibrary_calls == ["MULL12060ferrite"]
    assert hfss.odesign.import_dataset_calls
    assert [payload[0] for payload in hfss.oproject.add_dataset_calls] == ["NAME:$mu_r_real", "NAME:$mu_tand_m"]
    assert len(hfss.oproject.definition_manager.add_material_calls) == 1
    assert hfss.oproject.definition_manager.add_material_calls[0][0] == "NAME:MULL12060ferrite"
    assert hfss.assign_material_calls == [
        (body_name, expected_material_assignments[body_name]) for body_name in ledger["body_names"]
    ]
    tx_copper_object = cast(_FakeModelObject, hfss.modeler.get_object_from_name("tx_ssw_coil_ssw_copper"))
    rx_copper_object = cast(_FakeModelObject, hfss.modeler.get_object_from_name("rx_ssw_coil_coil_copper"))
    fr4_object = cast(_FakeModelObject, hfss.modeler.get_object_from_name("tx_ssw_coil_pcb_1_fr4"))
    assert tx_copper_object.solve_inside is True
    assert rx_copper_object.solve_inside is True
    assert fr4_object.solve_inside is False
    mesh_payload = hfss.odesign.mesh_module.assign_length_calls[0]
    assert mesh_payload[0] == "NAME:Length1"
    assert mesh_payload[mesh_payload.index("Objects:=") + 1] == [
        "rx_ssw_coil_coil_copper",
        "tx_ssw_coil_ssw_copper",
        "tx_ssw_coil_pcb_1_fr4",
    ]
    assert mesh_payload[mesh_payload.index("MaxLength:=") + 1] == "3.5mm"
    assert mesh_payload[mesh_payload.index("NumMaxElem:=") + 1] == "20000"
    assert hfss.odesign.analysis_setup_module.insert_setup_calls[0][0] == "HfssDriven"
    setup_payload = hfss.odesign.analysis_setup_module.insert_setup_calls[0][1]
    assert setup_payload[0] == "NAME:Setup1"
    assert setup_payload[setup_payload.index("Frequency:=") + 1] == "6.78MHz"
    assert setup_payload[setup_payload.index("MaxDeltaS:=") + 1] == 0.003
    assert setup_payload[setup_payload.index("MaximumPasses:=") + 1] == 16
    assert setup_payload[setup_payload.index("MinimumPasses:=") + 1] == 16
    assert setup_payload[setup_payload.index("MinimumConvergedPasses:=") + 1] == 16
    assert setup_payload[setup_payload.index("PercentRefinement:=") + 1] == 20
    assert setup_payload[setup_payload.index("MaxPass:=") + 1] == 16
    assert setup_payload[setup_payload.index("MinPass:=") + 1] == 16
    assert setup_payload[setup_payload.index("MinConvPass:=") + 1] == 16
    assert setup_payload[setup_payload.index("BasisOrder:=") + 1] == 0
    assert setup_payload[setup_payload.index("DrivenSolverType:=") + 1] == "Direct Solver"
    assert hfss.odesign.analysis_setup_module.insert_sweep_calls[0][0] == "Setup1"
    sweep_payload = hfss.odesign.analysis_setup_module.insert_sweep_calls[0][1]
    assert sweep_payload[0] == "NAME:Sweep"
    assert sweep_payload[sweep_payload.index("RangeStart:=") + 1] == "0.1MHz"
    assert sweep_payload[sweep_payload.index("RangeEnd:=") + 1] == "100MHz"
    assert sweep_payload[sweep_payload.index("RangeCount:=") + 1] == 81
    assert sweep_payload[sweep_payload.index("Type:=") + 1] == "Interpolating"
    assert hfss.oboundary.assign_lumped_port_calls == [
        [
            "NAME:1",
            "Edges:=",
            [101, 102],
            "LumpedPortType:=",
            "Terminal",
            "DoDeembed:=",
            False,
            "RenormalizeAllTerminals:=",
            True,
            "ShowReporterFilter:=",
            False,
            "Impedance:=",
            "50ohm",
        ],
        [
            "NAME:2",
            "Edges:=",
            [201, 202],
            "LumpedPortType:=",
            "Terminal",
            "DoDeembed:=",
            False,
            "RenormalizeAllTerminals:=",
            True,
            "ShowReporterFilter:=",
            False,
            "Impedance:=",
            "50ohm",
        ],
    ]
    assert result["ports"] == {"tx": ["1_T1"], "rx": ["2_T1"]}
    assert hfss.odesign.solutions_module.edit_sources_calls == [
        [
            [
                "UseIncidentVoltage:=",
                True,
                "IncludePortPostProcessing:=",
                False,
                "UseElementPatternMode:=",
                False,
                "SpecifySystemPower:=",
                False,
            ],
            ["Name:=", "1_T1", "Magnitude:=", "100V", "Phase:=", "0deg"],
            ["Name:=", "2_T1", "Magnitude:=", "100V", "Phase:=", "90deg"],
        ]
    ]
    assert result["sources"] == {
        "tx_source_name": "1_T1",
        "tx_magnitude": "100V",
        "tx_phase_deg": "0deg",
        "rx_source_name": "2_T1",
        "rx_magnitude": "100V",
        "rx_phase_deg": "90deg",
    }
    assert result["design_id"] == ledger["design_id"]
    assert result["aedt_filename"] == ledger["aedt_filename"]
    assert result["dimension_count"] == ledger["dimension_count"]
    assert result["design_space_hash"] == ledger["design_space_hash"]
    assert result["mesh"]["objects"] == [
        "rx_ssw_coil_coil_copper",
        "tx_ssw_coil_ssw_copper",
        "tx_ssw_coil_pcb_1_fr4",
    ]
    assert result["mesh"]["operation"] == "AssignLengthOp"
    assert result["mesh"]["max_length"] == "3.5mm"
    assert result["mesh"]["num_max_elem"] == "20000"
    assert hfss.modeler.create_region_calls == [
        {"pad_value": 2000, "pad_type": "Absolute Offset", "name": "Region_Abs_2000mm"}
    ]
    assert hfss.radiation_calls == [
        ([301], "Rad_RegionAbs_0"),
        ([302], "Rad_RegionAbs_1"),
        ([303], "Rad_RegionAbs_2"),
        ([304], "Rad_RegionAbs_3"),
        ([305], "Rad_RegionAbs_4"),
        ([306], "Rad_RegionAbs_5"),
    ]
    assert result["boundary"] == {
        "type": "radiation",
        "offset_type": "Absolute Offset",
        "offset_value": "2000.0",
        "region_name": "Region_Abs_2000mm",
        "face_count": "6",
        "boundary_names": [
            "Rad_RegionAbs_0",
            "Rad_RegionAbs_1",
            "Rad_RegionAbs_2",
            "Rad_RegionAbs_3",
            "Rad_RegionAbs_4",
            "Rad_RegionAbs_5",
        ],
    }
    assert result["analysis_setup"]["setup_name"] == "Setup1"
    assert result["analysis_setup"]["frequency"] == "6.78MHz"
    assert result["frequency_sweep"]["sweep_name"] == "Sweep"
    assert result["frequency_sweep"]["range_count"] == 81
    assert [name for name, _expression, _solution in hfss.create_output_variables] == [
        "Ltx_uH",
        "Lrx_uH",
        "M_uH",
        "k_ratio",
        "Qtx_ratio",
        "Qrx_ratio",
        "FOM_ratio",
        "re_Z11_ohm",
        "im_Z11_ohm",
        "re_Z22_ohm",
        "im_Z22_ohm",
        "re_Z12_ohm",
        "im_Z12_ohm",
        "M_over_Ltx_ratio",
        "M_over_Lrx_ratio",
        "eta_fom_max_ratio",
    ]
    assert hfss.create_output_variables[0] == (
        "Ltx_uH",
        "im(Zt(1_T1,1_T1))/2/pi/freq*1e6",
        "Setup1 : Sweep",
    )
    assert hfss.create_output_variables[11] == (
        "re_Z12_ohm",
        "re(Zt(1_T1,2_T1))",
        "Setup1 : Sweep",
    )
    assert hfss.create_output_variables[12] == (
        "im_Z12_ohm",
        "im(Zt(1_T1,2_T1))",
        "Setup1 : Sweep",
    )
    assert [call["plot_name"] for call in hfss.odesign.report_setup_module.create_report_calls] == [
        "Results1_Pass",
        "Results2_Last",
        "Results3_Freq",
    ]
    adaptive_components = cast(list[object], hfss.odesign.report_setup_module.create_report_calls[0]["components"])
    assert adaptive_components[adaptive_components.index("X Component:=") + 1] == "Pass"
    adaptive_traces = cast(list[str], adaptive_components[adaptive_components.index("Y Component:=") + 1])
    assert adaptive_traces[-2:] == ["SolvedElements", "MaxMagDeltaS"]
    solid_loss_reporter_calls = hfss.odesign.fields_reporter_module.calls
    solid_loss_names = [
        expression_name
        for operation, payload in solid_loss_reporter_calls
        if operation == "AddNamedExpression"
        for expression_name, field_type in [cast(tuple[str, str], payload)]
        if field_type == "Fields"
    ]
    assert set(solid_loss_names) == {
        "loss_W_rx_ssw_coil_coil_copper",
        "loss_W_tx_mull_ferrite_sheet",
        "loss_W_tx_ssw_coil_pcb_1_fr4",
        "loss_W_tx_ssw_coil_ssw_copper",
        "loss_W_Region_Abs_2000mm",
    }
    assert {cast(str, payload) for operation, payload in solid_loss_reporter_calls if operation == "EnterVol"} == {
        "rx_ssw_coil_coil_copper",
        "tx_mull_ferrite_sheet",
        "tx_ssw_coil_pcb_1_fr4",
        "tx_ssw_coil_ssw_copper",
        "Region_Abs_2000mm",
    }
    assert [payload for operation, payload in solid_loss_reporter_calls if operation == "CopyNamedExprToStack"] == [
        "Volume_Loss_Density",
        "Volume_Loss_Density",
        "Volume_Loss_Density",
        "Volume_Loss_Density",
        "Volume_Loss_Density",
    ]
    assert [payload for operation, payload in solid_loss_reporter_calls if operation == "CalcOp"] == [
        "Integrate",
        "Integrate",
        "Integrate",
        "Integrate",
        "Integrate",
    ]
    solid_loss_components = cast(list[object], hfss.odesign.report_setup_module.create_report_calls[1]["components"])
    assert solid_loss_components[solid_loss_components.index("X Component:=") + 1] == "Freq"
    assert solid_loss_components[solid_loss_components.index("Y Component:=") + 1] == solid_loss_names
    assert hfss.odesign.report_setup_module.create_report_calls[1]["report_category"] == "Fields"
    assert hfss.odesign.report_setup_module.create_report_calls[1]["setup_sweep_name"] == "Setup1 : LastAdaptive"
    diagnostic_components = cast(list[object], hfss.odesign.report_setup_module.create_report_calls[2]["components"])
    diagnostic_traces = cast(list[str], diagnostic_components[diagnostic_components.index("Y Component:=") + 1])
    assert "Volume(tv)" in diagnostic_traces
    assert "Volume(tx_mull_ferrite_sheet)" in diagnostic_traces
    assert "Volume(tx_ssw_coil_ssw_copper)" in diagnostic_traces
    assert "Volume(Region_Abs_2000mm)" in diagnostic_traces
    assert diagnostic_components[diagnostic_components.index("X Component:=") + 1] == "Freq"
    assert hfss.odesign.report_setup_module.create_report_calls[2]["setup_sweep_name"] == "Setup1 : Sweep"
    assert result["reports"]["report_names"] == ["Results1_Pass", "Results2_Last", "Results3_Freq"]
    assert result["reports"]["output_solution_name"] == "Setup1 : Sweep"
    assert result["reports"]["solid_loss_solution_name"] == "Setup1 : LastAdaptive"
    assert result["reports"]["output_variable_names"] == [
        name for name, _expression, _solution in hfss.create_output_variables
    ]
    assert result["reports"]["solid_loss_expression_names"] == solid_loss_names
    assert hfss.saved_paths == [str(tmp_path / "ssw_ports.aedt")]
    imported = json.loads((tmp_path / "ssw_imported.json").read_text(encoding="utf-8"))
    assert imported["design_id"] == ledger["design_id"]
    assert imported["aedt_filename"] == ledger["aedt_filename"]
    assert imported["dimension_count"] == ledger["dimension_count"]
    assert imported["design_space_hash"] == ledger["design_space_hash"]
    assert imported["source_port_ledger_path"] == str(ledger_path)
    assert imported["copper_body_names"] == ledger["copper_body_names"]
    assert imported["ferrite_body_names"] == ledger["ferrite_body_names"]
    assert imported["material_assignments"] == expected_material_assignments
    assert imported["mesh"] == result["mesh"]
    assert imported["boundary"] == result["boundary"]
    assert imported["analysis_setup"] == result["analysis_setup"]
    assert imported["frequency_sweep"] == result["frequency_sweep"]
    assert imported["sources"] == result["sources"]
    assert imported["reports"] == result["reports"]
    assert "port_sheet_names" not in imported
    assert "tx_aedt_port_sheet" not in imported["visual_assignments"]
    assert all(ledger["design_id"] not in object_name for object_name in imported["imported_object_names"])


def test_setup_ssw_aedt_ports_into_hfss_raises_on_missing_recorded_mesh_target(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger["copper_body_names"] = ["tx_ssw_coil_ssw_copper"]
    ledger_path = tmp_path / "ssw_aedt_port_ledger.json"
    write_ssw_aedt_port_ledger(ledger_path=ledger_path, ledger=ledger)
    Path(ledger["scene_step_path"]).write_text("placeholder", encoding="utf-8")

    with pytest.raises(ValueError, match="SSW mesh requires exactly one recorded RX copper target"):
        setup_ssw_aedt_ports_into_hfss(
            hfss=cast(HfssSession, _FakeHfss(ledger)),
            port_ledger_path=ledger_path,
            output_aedt_path=tmp_path / "ssw_ports.aedt",
            imported_ledger_path=tmp_path / "ssw_imported.json",
        )


def test_setup_ssw_aedt_ports_into_hfss_raises_on_mesh_assignment_false(tmp_path: Path) -> None:
    ledger_path = _ledger_path(tmp_path)
    hfss = _FakeHfss(_ledger(tmp_path))
    hfss.odesign.mesh_module.assign_result = False

    with pytest.raises(RuntimeError, match="AssignLengthOp"):
        setup_ssw_aedt_ports_into_hfss(
            hfss=cast(HfssSession, hfss),
            port_ledger_path=ledger_path,
            output_aedt_path=tmp_path / "ssw_ports.aedt",
            imported_ledger_path=tmp_path / "ssw_imported.json",
        )


def test_setup_ssw_aedt_ports_into_hfss_raises_on_setup_or_sweep_false(tmp_path: Path) -> None:
    ledger_path = _ledger_path(tmp_path)
    hfss = _FakeHfss(_ledger(tmp_path))
    hfss.odesign.analysis_setup_module.insert_setup_result = False

    with pytest.raises(RuntimeError, match="InsertSetup"):
        setup_ssw_aedt_ports_into_hfss(
            hfss=cast(HfssSession, hfss),
            port_ledger_path=ledger_path,
            output_aedt_path=tmp_path / "ssw_ports.aedt",
            imported_ledger_path=tmp_path / "ssw_imported.json",
        )

    hfss = _FakeHfss(_ledger(tmp_path))
    hfss.odesign.analysis_setup_module.insert_sweep_result = False

    with pytest.raises(RuntimeError, match="InsertFrequencySweep"):
        setup_ssw_aedt_ports_into_hfss(
            hfss=cast(HfssSession, hfss),
            port_ledger_path=ledger_path,
            output_aedt_path=tmp_path / "ssw_ports.aedt",
            imported_ledger_path=tmp_path / "ssw_imported.json",
        )


def test_setup_ssw_aedt_ports_into_hfss_raises_on_boundary_generation_failure(tmp_path: Path) -> None:
    ledger_path = _ledger_path(tmp_path)
    hfss = _FakeHfss(_ledger(tmp_path))
    hfss.modeler.create_region_result = False

    with pytest.raises(RuntimeError, match="create_region"):
        setup_ssw_aedt_ports_into_hfss(
            hfss=cast(HfssSession, hfss),
            port_ledger_path=ledger_path,
            output_aedt_path=tmp_path / "ssw_ports.aedt",
            imported_ledger_path=tmp_path / "ssw_imported.json",
        )

    hfss = _FakeHfss(_ledger(tmp_path))
    hfss.modeler.region_face_ids = [301, 302, 303, 304, 305]

    with pytest.raises(ValueError, match="does not expose 6 faces"):
        setup_ssw_aedt_ports_into_hfss(
            hfss=cast(HfssSession, hfss),
            port_ledger_path=ledger_path,
            output_aedt_path=tmp_path / "ssw_ports.aedt",
            imported_ledger_path=tmp_path / "ssw_imported.json",
        )

    hfss = _FakeHfss(_ledger(tmp_path))
    hfss.assign_radiation_result = False

    with pytest.raises(RuntimeError, match="assign_radiation_boundary_to_faces"):
        setup_ssw_aedt_ports_into_hfss(
            hfss=cast(HfssSession, hfss),
            port_ledger_path=ledger_path,
            output_aedt_path=tmp_path / "ssw_ports.aedt",
            imported_ledger_path=tmp_path / "ssw_imported.json",
        )


def test_setup_ssw_aedt_ports_into_hfss_raises_on_report_generation_false(tmp_path: Path) -> None:
    ledger_path = _ledger_path(tmp_path)
    hfss = _FakeHfss(_ledger(tmp_path))
    hfss.create_output_variable_result = False

    with pytest.raises(RuntimeError, match="create_output_variable"):
        setup_ssw_aedt_ports_into_hfss(
            hfss=cast(HfssSession, hfss),
            port_ledger_path=ledger_path,
            output_aedt_path=tmp_path / "ssw_ports.aedt",
            imported_ledger_path=tmp_path / "ssw_imported.json",
        )

    hfss = _FakeHfss(_ledger(tmp_path))
    hfss.odesign.report_setup_module.create_report_result = False

    with pytest.raises(RuntimeError, match="CreateReport"):
        setup_ssw_aedt_ports_into_hfss(
            hfss=cast(HfssSession, hfss),
            port_ledger_path=ledger_path,
            output_aedt_path=tmp_path / "ssw_ports.aedt",
            imported_ledger_path=tmp_path / "ssw_imported.json",
        )


def test_setup_ssw_aedt_ports_into_hfss_raises_when_report_is_not_registered(tmp_path: Path) -> None:
    ledger_path = _ledger_path(tmp_path)
    hfss = _FakeHfss(_ledger(tmp_path))
    hfss.odesign.report_setup_module.report_names_result = False

    with pytest.raises(ValueError, match="SSW report creation did not register required reports"):
        setup_ssw_aedt_ports_into_hfss(
            hfss=cast(HfssSession, hfss),
            port_ledger_path=ledger_path,
            output_aedt_path=tmp_path / "ssw_ports.aedt",
            imported_ledger_path=tmp_path / "ssw_imported.json",
        )


def test_setup_ssw_aedt_ports_into_hfss_raises_on_port_assignment_false(tmp_path: Path) -> None:
    ledger_path = _ledger_path(tmp_path)
    hfss = _FakeHfss(_ledger(tmp_path))
    hfss.oboundary.assign_result = False

    with pytest.raises(RuntimeError, match="AssignLumpedPort"):
        setup_ssw_aedt_ports_into_hfss(
            hfss=cast(HfssSession, hfss),
            port_ledger_path=ledger_path,
            output_aedt_path=tmp_path / "ssw_ports.aedt",
            imported_ledger_path=tmp_path / "ssw_imported.json",
        )


def test_setup_ssw_aedt_ports_into_hfss_raises_on_source_edit_false(tmp_path: Path) -> None:
    ledger_path = _ledger_path(tmp_path)
    hfss = _FakeHfss(_ledger(tmp_path))
    hfss.odesign.solutions_module.edit_sources_result = False

    with pytest.raises(RuntimeError, match="EditSources"):
        setup_ssw_aedt_ports_into_hfss(
            hfss=cast(HfssSession, hfss),
            port_ledger_path=ledger_path,
            output_aedt_path=tmp_path / "ssw_ports.aedt",
            imported_ledger_path=tmp_path / "ssw_imported.json",
        )


def test_setup_ssw_aedt_ports_into_hfss_raises_on_solid_loss_expression_false(tmp_path: Path) -> None:
    ledger_path = _ledger_path(tmp_path)
    hfss = _FakeHfss(_ledger(tmp_path))
    hfss.odesign.fields_reporter_module.add_named_expression_result = False

    with pytest.raises(RuntimeError, match="AddNamedExpression"):
        setup_ssw_aedt_ports_into_hfss(
            hfss=cast(HfssSession, hfss),
            port_ledger_path=ledger_path,
            output_aedt_path=tmp_path / "ssw_ports.aedt",
            imported_ledger_path=tmp_path / "ssw_imported.json",
        )


def test_setup_ssw_aedt_ports_can_leave_graphical_desktop_open(tmp_path: Path) -> None:
    ledger_path = _ledger_path(tmp_path)
    hfss = _FakeHfss(_ledger(tmp_path))

    def _factory(design_name: str) -> HfssSession:
        assert design_name == "ssw_gui_test"
        return cast(HfssSession, hfss)

    setup_ssw_aedt_ports(
        port_ledger_path=ledger_path,
        output_aedt_path=tmp_path / "ssw_ports.aedt",
        imported_ledger_path=tmp_path / "ssw_imported.json",
        design_name="ssw_gui_test",
        hfss_factory=_factory,
        release_desktop_on_exit=False,
    )

    assert hfss.desktop_class.release_calls == []


def test_solve_ssw_aedt_ports_exports_all_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fake_telemetry(monkeypatch)
    ledger_path = _ledger_path(tmp_path)
    hfss = _FakeHfss(_ledger(tmp_path))

    def _factory(design_name: str) -> HfssSession:
        assert design_name == "ssw_solve_test"
        return cast(HfssSession, hfss)

    result = solve_ssw_aedt_ports(
        port_ledger_path=ledger_path,
        output_aedt_path=tmp_path / "ssw_ports.aedt",
        imported_ledger_path=tmp_path / "ssw_imported.json",
        design_name="ssw_solve_test",
        csv_output_dir=tmp_path / "csv",
        hfss_factory=_factory,
    )

    assert result["setup"]["design_id"] == _ledger(tmp_path)["design_id"]
    assert hfss.analyze_setup_calls == [("Setup1", True)]
    assert hfss.odesign.report_setup_module.export_to_file_calls == [
        (report_name, str(tmp_path / "csv" / f"{report_name}.csv")) for report_name in SSW_REPORT_NAMES
    ]
    assert set(result["csv_paths"]) == set(SSW_REPORT_NAMES)
    assert result["solve_telemetry"]["aedt_process_id"] == os.getpid()
    assert result["solve_telemetry"]["reported_aedt_process_id"] == os.getpid()
    assert result["solve_telemetry"]["sample_interval_seconds"] == 2.0
    assert result["solve_telemetry"]["sample_count"] >= 1
    assert Path(result["solve_telemetry"]["samples_jsonl_path"]).is_file()
    assert result["solve_telemetry"]["elapsed_ms"] >= 0.0
    assert result["solve_telemetry"]["samples"][0]["aedt_process_id"] == os.getpid()
    assert result["solve_telemetry"]["samples"][0]["reported_aedt_process_id"] == os.getpid()
    for report_name in SSW_REPORT_NAMES:
        assert Path(result["csv_paths"][report_name]).is_file()
    assert hfss.desktop_class.release_calls == [(True, True)]


def test_solve_ssw_aedt_ports_supports_pass_count_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fake_telemetry(monkeypatch)
    ledger_path = _ledger_path(tmp_path)
    hfss = _FakeHfss(_ledger(tmp_path))

    def _factory(design_name: str) -> HfssSession:
        assert design_name == "ssw_pass_override_test"
        return cast(HfssSession, hfss)

    solve_ssw_aedt_ports(
        port_ledger_path=ledger_path,
        output_aedt_path=tmp_path / "ssw_ports.aedt",
        imported_ledger_path=tmp_path / "ssw_imported.json",
        design_name="ssw_pass_override_test",
        csv_output_dir=tmp_path / "csv",
        hfss_factory=_factory,
        setup_maximum_passes=5,
        setup_minimum_passes=1,
        setup_minimum_converged_passes=1,
    )

    setup_payload = hfss.odesign.analysis_setup_module.insert_setup_calls[0][1]
    assert setup_payload[setup_payload.index("MaximumPasses:=") + 1] == 5
    assert setup_payload[setup_payload.index("MinimumPasses:=") + 1] == 1
    assert setup_payload[setup_payload.index("MinimumConvergedPasses:=") + 1] == 1
    assert setup_payload[setup_payload.index("MaxPass:=") + 1] == 5
    assert setup_payload[setup_payload.index("MinPass:=") + 1] == 1
    assert setup_payload[setup_payload.index("MinConvPass:=") + 1] == 1


def test_solve_ssw_aedt_ports_raises_on_analyze_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fake_telemetry(monkeypatch)
    ledger_path = _ledger_path(tmp_path)
    hfss = _FakeHfss(_ledger(tmp_path))
    hfss.analyze_setup_result = False

    def _factory(design_name: str) -> HfssSession:
        assert design_name == "ssw_analyze_false_test"
        return cast(HfssSession, hfss)

    with pytest.raises(RuntimeError, match="analyze_setup"):
        solve_ssw_aedt_ports(
            port_ledger_path=ledger_path,
            output_aedt_path=tmp_path / "ssw_ports.aedt",
            imported_ledger_path=tmp_path / "ssw_imported.json",
            design_name="ssw_analyze_false_test",
            csv_output_dir=tmp_path / "csv",
            hfss_factory=_factory,
        )

    assert hfss.desktop_class.release_calls == [(True, True)]


def test_solve_ssw_aedt_ports_raises_on_export_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fake_telemetry(monkeypatch)
    ledger_path = _ledger_path(tmp_path)
    hfss = _FakeHfss(_ledger(tmp_path))
    hfss.odesign.report_setup_module.export_to_file_result = False

    def _factory(design_name: str) -> HfssSession:
        assert design_name == "ssw_export_false_test"
        return cast(HfssSession, hfss)

    with pytest.raises(RuntimeError, match="ReportSetup.ExportToFile"):
        solve_ssw_aedt_ports(
            port_ledger_path=ledger_path,
            output_aedt_path=tmp_path / "ssw_ports.aedt",
            imported_ledger_path=tmp_path / "ssw_imported.json",
            design_name="ssw_export_false_test",
            csv_output_dir=tmp_path / "csv",
            hfss_factory=_factory,
        )


def test_solve_ssw_aedt_ports_raises_when_exported_csv_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fake_telemetry(monkeypatch)
    ledger_path = _ledger_path(tmp_path)
    hfss = _FakeHfss(_ledger(tmp_path))
    hfss.odesign.report_setup_module.write_exported_file = False

    def _factory(design_name: str) -> HfssSession:
        assert design_name == "ssw_missing_csv_test"
        return cast(HfssSession, hfss)

    with pytest.raises(FileNotFoundError, match="SSW report export did not create CSV"):
        solve_ssw_aedt_ports(
            port_ledger_path=ledger_path,
            output_aedt_path=tmp_path / "ssw_ports.aedt",
            imported_ledger_path=tmp_path / "ssw_imported.json",
            design_name="ssw_missing_csv_test",
            csv_output_dir=tmp_path / "csv",
            hfss_factory=_factory,
        )


@pytest.mark.pyaedt_integration
def test_setup_ssw_aedt_ports_runs_real_headless_ansys() -> None:
    output_dir = RUN_DIR / "ssw_headless_ansys_test"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    ledger = export_ssw_aedt_port_artifacts(source_toml_path=SOURCE_TOML_PATH, output_dir=output_dir, seed=0)

    result = setup_ssw_aedt_ports(
        port_ledger_path=output_dir / AEDT_PORT_LEDGER_NAME,
        output_aedt_path=output_dir / ledger["aedt_filename"],
        imported_ledger_path=output_dir / AEDT_IMPORTED_LEDGER_NAME,
        design_name=ledger["design_id"],
    )

    assert result["ports"] == {"tx": ["1_T1"], "rx": ["2_T1"]}
    assert result["design_id"] == ledger["design_id"]
    assert result["aedt_filename"] == ledger["aedt_filename"]
    assert result["dimension_count"] == ledger["dimension_count"]
    assert result["design_space_hash"] == ledger["design_space_hash"]
    assert Path(result["aedt_path"]).is_file()
    assert Path(result["imported_ledger_path"]).is_file()
    imported = json.loads(Path(result["imported_ledger_path"]).read_text(encoding="utf-8"))
    assert imported["design_id"] == ledger["design_id"]
    assert imported["aedt_filename"] == ledger["aedt_filename"]
    assert imported["design_space_hash"] == ledger["design_space_hash"]
    assert "port_sheet_names" not in imported
    assert imported["copper_body_names"] == ledger["copper_body_names"]
    assert imported["fr4_body_names"] == ledger["fr4_body_names"]
    assert imported["mesh"]["objects"] == [
        "rx_ssw_coil_ssw_copper",
        "tx_ssw_coil_ssw_copper",
        *ledger["fr4_body_names"],
    ]
    assert imported["mesh"]["max_length"] == ledger.get("mesh_max_length")
    assert imported["mesh"]["num_max_elem"] == "20000"
    assert imported["boundary"]["region_name"] == "Region_Abs_2000mm"
    assert imported["boundary"]["face_count"] == "6"
    assert imported["analysis_setup"]["setup_name"] == "Setup1"
    assert imported["frequency_sweep"]["sweep_name"] == "Sweep"
    assert imported["reports"]["report_names"] == ["Results1_Pass", "Results2_Last", "Results3_Freq"]
    for copper_body_name in ledger["copper_body_names"]:
        assert f"loss_W_{copper_body_name}" in imported["reports"]["solid_loss_expression_names"]
    assert "loss_W_Region_Abs_2000mm" in imported["reports"]["solid_loss_expression_names"]
