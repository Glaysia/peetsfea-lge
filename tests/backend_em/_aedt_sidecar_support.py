from __future__ import annotations
# ruff: noqa: E402

import subprocess
import sys
import types
from pathlib import Path
from typing import cast

import pytest

TEST_PEETSFEA_PACKAGE_ROOT = (Path(__file__).resolve().parents[2] / "src" / "peetsfea").resolve()
_CACHE_RESET = object()


def _assert_bootstrapped_peetsfea_submodule_root(module: types.ModuleType, *, package_root: Path) -> None:
    module_file = getattr(module, "__file__", None)
    if module_file is not None:
        resolved_file = Path(module_file).resolve()
        if package_root not in resolved_file.parents:
            raise RuntimeError(
                "existing peetsfea submodule points outside the expected package root "
                f"{package_root}: {resolved_file}"
            )
        return
    module_paths = getattr(module, "__path__", None)
    if module_paths is None:
        raise RuntimeError("existing peetsfea submodule has neither __file__ nor __path__")
    normalized_paths = {Path(path).resolve() for path in cast(list[str], list(module_paths))}
    if not any(package_root == path or package_root in path.parents for path in normalized_paths):
        raise RuntimeError(
            "existing peetsfea submodule points to unexpected roots "
            f"{sorted(str(path) for path in normalized_paths)}; expected under {package_root}"
        )


def _assert_bootstrapped_peetsfea_package_root(package: types.ModuleType, *, package_root: Path) -> None:
    package_paths = getattr(package, "__path__", None)
    if package_paths is None:
        raise RuntimeError("existing peetsfea module is not a package")
    normalized_paths = {str(Path(path).resolve()) for path in cast(list[str], list(package_paths))}
    expected_path = str(package_root)
    if expected_path not in normalized_paths:
        raise RuntimeError(
            "existing peetsfea package points to unexpected roots "
            f"{sorted(normalized_paths)}; expected {expected_path}"
        )


def _bootstrap_peetsfea_test_package() -> None:
    package_root = TEST_PEETSFEA_PACKAGE_ROOT
    for module_name, existing_module in list(sys.modules.items()):
        if not module_name.startswith("peetsfea"):
            continue
        if not isinstance(existing_module, types.ModuleType):
            raise RuntimeError(f"existing {module_name} entry is not a module")
        _assert_bootstrapped_peetsfea_submodule_root(existing_module, package_root=package_root)
    if "peetsfea" in sys.modules:
        existing_package = sys.modules["peetsfea"]
        if not isinstance(existing_package, types.ModuleType):
            raise RuntimeError("existing peetsfea entry is not a module")
        _assert_bootstrapped_peetsfea_package_root(existing_package, package_root=package_root)
        return
    if not package_root.is_dir():
        raise RuntimeError(f"expected peetsfea package root at {package_root}")
    package = types.ModuleType("peetsfea")
    package.__file__ = str(package_root / "__init__.py")
    package.__package__ = "peetsfea"
    package.__path__ = [str(package_root)]  # type: ignore[attr-defined]
    sys.modules["peetsfea"] = package


_bootstrap_peetsfea_test_package()

import peetsfea.aedt as aedt_package
import peetsfea.aedt.protocols as aedt_protocols
import peetsfea.aedt.proxies as aedt_proxies
from peetsfea.aedt import Hfss, Modeler3D, Object3d, aedt_versions
from peetsfea.aedt.core import Hfss as package_hfss
from peetsfea.aedt.core.internal import aedt_versions as package_aedt_versions
from peetsfea.aedt.core.modeler import Modeler3D as package_modeler_3d
from peetsfea.aedt.core.modeler.cad import Object3d as package_object_3d
from peetsfea.aedt.core.modeler.cad.object_3d import Object3d as module_object_3d
from peetsfea.aedt.core.modeler.modeler_3d import Modeler3D as module_modeler_3d
from peetsfea.aedt.failfast import MAX_AEDT_NAME_LENGTH, raise_on_false, validate_aedt_name
from peetsfea.aedt.protocols import AedtVersionsSession, HfssSession, ModelerSession, Object3dRef
from peetsfea.aedt.proxies import (
    assign_lumped_port,
    assign_radiation_boundary_to_faces,
    cover_lines,
    create_box,
    create_cylinder,
    create_group,
    create_output_variable,
    create_polyline,
    create_region,
    create_report,
    delete_setup,
    edit_sources,
    ensure_ferrite_material,
    get_boundary_names,
    get_design_module,
    get_report_names,
    get_supported_traces,
    get_version_env_variable,
    insert_frequency_sweep,
    insert_setup,
    list_excitation_names,
    object_bbox,
    object_edge_samples_xy,
    object_name,
    point_xy,
    release_desktop_session,
    reset_aedt_versions_cache,
    save_project,
    set_object_color,
    set_object_transparency,
    set_object_model_state,
    subtract,
    thicken_sheet,
    unite,
    wrap_aedt_versions,
    wrap_hfss,
)


class _FakePoint:
    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y


class _FakeEdge:
    def __init__(self, midpoint: object | None = None, vertices: list[object] | None = None) -> None:
        self.midpoint = midpoint
        self.center = None
        self.start = None
        self.end = None
        self.vertices = [] if vertices is None else list(vertices)


class _FakeObject:
    def __init__(self, name: str, bbox: list[float], *, callable_bbox: bool = False) -> None:
        self.name = name
        self.color: tuple[int, int, int] | None = None
        self.transparency: float | None = None
        self.edges = [_FakeEdge(midpoint=(1.0, 2.0)), _FakeEdge(vertices=[_FakePoint(3.0, 4.0)])]
        if callable_bbox:
            self._bbox = list(bbox)
        else:
            self.bounding_box = list(bbox)

    def bbox(self) -> list[float]:
        return list(self._bbox)


class _FakeBoundaryModule:
    def __init__(self, *, assign_result: object = None, boundaries: list[object] | None = None) -> None:
        self.assign_result = assign_result
        self.boundaries = [] if boundaries is None else list(boundaries)
        self.get_boundaries_result: object | None = None
        self.get_boundaries_error: Exception | None = None
        self.assign_calls: list[list[object]] = []

    def AssignLumpedPort(self, props: list[object]) -> object:
        self.assign_calls.append(list(props))
        return self.assign_result

    def GetBoundaries(self) -> object:
        if self.get_boundaries_error is not None:
            raise self.get_boundaries_error
        if self.get_boundaries_result is not None:
            return self.get_boundaries_result
        return list(self.boundaries)


class _FakeDesktop:
    def __init__(self, *, result: object = True, error: Exception | None = None, pid: int = 1234) -> None:
        self.result = result
        self.error = error
        self.aedt_process_id = pid
        self.calls: list[tuple[bool, bool]] = []

    def release_desktop(self, close_projects: bool = True, close_on_exit: bool = True) -> object:
        self.calls.append((close_projects, close_on_exit))
        if self.error is not None:
            raise self.error
        return self.result


class _FakeMaterial:
    def __init__(self, *, fail_attr_name: str | None = None) -> None:
        self._fail_attr_name = fail_attr_name

    def __setattr__(self, name: str, value: object) -> None:
        if name != "_fail_attr_name" and getattr(self, "_fail_attr_name", None) == name:
            raise RuntimeError(f"failed to set {name}")
        super().__setattr__(name, value)


class _FakeMaterials:
    def __init__(self) -> None:
        self.material_keys: dict[str, object] = {}
        self.add_result: object | None = None
        self.fail_attr_name: str | None = None

    def exists_material(self, name: str) -> bool:
        return name in self.material_keys

    def add_material(self, name: str) -> object:
        if self.add_result is False:
            return False
        material = _FakeMaterial(fail_attr_name=self.fail_attr_name)
        self.material_keys[name] = material
        return material


class _FakeModeler:
    def __init__(self) -> None:
        self.create_box_calls: list[dict[str, object]] = []
        self.create_cylinder_calls: list[dict[str, object]] = []
        self.create_group_calls: list[tuple[list[str], str]] = []
        self.create_polyline_calls: list[dict[str, object]] = []
        self.create_region_calls: list[tuple[int, str, str]] = []
        self.cover_lines_calls: list[object] = []
        self.subtract_calls: list[tuple[list[str], list[str], bool]] = []
        self.thicken_sheet_calls: list[tuple[object, float]] = []
        self.unite_calls: list[list[str]] = []
        self.set_model_state_calls: list[tuple[str, bool]] = []
        self.raise_non_model_type_error = False
        self.cover_keyword_unsupported = False
        self.thicken_keyword_unsupported = False
        self.unite_keyword_unsupported = False
        self.create_box_result: object = _FakeObject("box", [0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
        self.create_cylinder_result: object = _FakeObject("cylinder", [0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
        self.create_region_result: object = _FakeObject("Region", [0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
        self.create_group_result: object = "group_ok"
        self.create_polyline_result: object = _FakeObject("polyline", [0.0, 0.0, 0.0, 1.0, 1.0, 1.0], callable_bbox=True)
        self.cover_result: object = "covered"
        self.thicken_result: object = "thickened"
        self.unite_result: object = "united"
        self.subtract_result: object = True

    def create_box(self, **kwargs: object) -> object:
        self.create_box_calls.append(dict(kwargs))
        if self.raise_non_model_type_error and "non_model" in kwargs:
            raise TypeError("non_model unsupported")
        if self.create_box_result is False:
            return False
        return _FakeObject(str(kwargs["name"]), [0.0, 0.0, 0.0, 1.0, 1.0, 1.0])

    def create_cylinder(self, **kwargs: object) -> object:
        self.create_cylinder_calls.append(dict(kwargs))
        if self.create_cylinder_result is False:
            return False
        return _FakeObject(str(kwargs["name"]), [0.0, 0.0, 0.0, 1.0, 1.0, 1.0])

    def create_group(self, *, objects: list[str], group_name: str) -> object:
        self.create_group_calls.append((list(objects), group_name))
        return self.create_group_result

    def create_polyline(self, **kwargs: object) -> object:
        self.create_polyline_calls.append(dict(kwargs))
        if self.create_polyline_result is False:
            return False
        return _FakeObject(str(kwargs["name"]), [0.0, 0.0, 0.0, 1.0, 1.0, 1.0], callable_bbox=True)

    def create_region(self, pad_value: int, pad_type: str, name: str) -> object:
        self.create_region_calls.append((pad_value, pad_type, name))
        return self.create_region_result

    def cover_lines(self, *args: object, **kwargs: object) -> object:
        if self.cover_keyword_unsupported and "assignment" in kwargs:
            raise TypeError("assignment unsupported")
        assignment = kwargs.get("assignment", args[0] if args else None)
        self.cover_lines_calls.append(assignment)
        return self.cover_result

    def get_edge_vertices(self, assignment: int) -> list[int]:
        _ = assignment
        return [1, 2]

    def get_object_edges(self, assignment: str) -> list[int]:
        _ = assignment
        return [10, 11]

    def get_object_faces(self, assignment: str) -> list[int]:
        _ = assignment
        return [1, 2, 3, 4, 5, 6]

    def get_vertex_position(self, assignment: int) -> list[float]:
        if assignment == 1:
            return [0.0, 0.0, 0.0]
        return [1.0, 0.0, 0.0]

    def subtract(self, *, blank_list: list[str], tool_list: list[str], keep_originals: bool) -> object:
        self.subtract_calls.append((list(blank_list), list(tool_list), keep_originals))
        return self.subtract_result

    def thicken_sheet(self, *args: object, **kwargs: object) -> object:
        if self.thicken_keyword_unsupported and "assignment" in kwargs:
            raise TypeError("assignment unsupported")
        assignment = kwargs.get("assignment", args[0] if args else None)
        thickness = kwargs.get("thickness", args[1] if len(args) > 1 else None)
        self.thicken_sheet_calls.append((assignment, cast(float, thickness)))
        return self.thicken_result

    def unite(self, *args: object, **kwargs: object) -> object:
        if self.unite_keyword_unsupported and "assignment" in kwargs:
            raise TypeError("assignment unsupported")
        assignment = kwargs.get("assignment", args[0] if args else [])
        self.unite_calls.append(list(cast(list[str], assignment)))
        return self.unite_result

    def set_object_model_state(self, name: str, model: bool) -> None:
        self.set_model_state_calls.append((name, model))


class _FakeAnalysisSetup:
    def __init__(self) -> None:
        self.setup_calls: list[tuple[str, list[object]]] = []
        self.sweep_calls: list[tuple[str, list[object]]] = []
        self.setup_result: object = True
        self.sweep_result: object = True

    def InsertSetup(self, setup_type: str, props: list[object]) -> object:
        self.setup_calls.append((setup_type, list(props)))
        return self.setup_result

    def InsertFrequencySweep(self, setup_name: str, props: list[object]) -> object:
        self.sweep_calls.append((setup_name, list(props)))
        return self.sweep_result


class _FakeReportSetup:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.raise_without_legacy = False
        self.create_report_result: object = True
        self.report_names_result: object = _CACHE_RESET

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
        if self.raise_without_legacy:
            raise TypeError("legacy signature only")
        if self.create_report_result is False:
            return False
        self.calls.append(
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
        if self.report_names_result is not _CACHE_RESET:
            return self.report_names_result
        return [str(call["plot_name"]) for call in self.calls]


class _FakeSolutions:
    def __init__(self) -> None:
        self.payloads: list[list[object]] = []
        self.edit_sources_result: object = True

    def EditSources(self, payload: list[object]) -> object:
        self.payloads.append(payload)
        return self.edit_sources_result


class _FakeHfss:
    def __init__(self) -> None:
        self.modeler = _FakeModeler()
        self.desktop_class = _FakeDesktop()
        self.materials = _FakeMaterials()
        self.oboundary = _FakeBoundaryModule(boundaries=["P1", "Lumped Port"])
        self.setup_names = ["Setup1"]
        self._excitation_names: list[str] = ["TX_TML", "RX_TML"]
        self.excitation_names_result: object = _CACHE_RESET
        self.raise_excitation_access = False
        self.assign_boundary_result: object = True
        self.output_variable_result: object = True
        self.save_project_result: object = True
        self.delete_setup_result: object = True
        self.deleted_setup_names: list[str] = []
        self.assigned_boundaries: list[tuple[object, str]] = []
        self.output_variables: list[tuple[str, str, str]] = []
        self.saved_paths: list[str] = []
        self.trace_raise_categories: set[str] = set()
        self.trace_false_categories: set[str] = set()
        self.available_traces = ["S(TX_TML,RX_TML)"]
        self.analysis_setup = _FakeAnalysisSetup()
        self.report_setup = _FakeReportSetup()
        self.solutions = _FakeSolutions()
        self.odesign = self

    @property
    def excitation_names(self) -> list[str]:
        if self.raise_excitation_access:
            raise RuntimeError("no excitation access")
        if self.excitation_names_result is not _CACHE_RESET:
            return cast(list[str], self.excitation_names_result)
        return list(self._excitation_names)

    def __setitem__(self, key: str, value: str) -> None:
        _ = key, value

    def assign_radiation_boundary_to_faces(self, assignment: object, name: str) -> object:
        self.assigned_boundaries.append((assignment, name))
        return self.assign_boundary_result

    def create_output_variable(self, variable: str, expression: str, solution: str) -> object:
        self.output_variables.append((variable, expression, solution))
        return self.output_variable_result

    def delete_setup(self, name: str) -> object:
        self.deleted_setup_names.append(name)
        return self.delete_setup_result

    def get_traces_for_plot(
        self,
        get_self_terms: bool,
        get_mutual_terms: bool,
        first_element_filter: str,
        second_element_filter: str,
        category: str,
        differential_pairs: list[object],
    ) -> list[str]:
        _ = (get_self_terms, get_mutual_terms, first_element_filter, second_element_filter, differential_pairs)
        if category in self.trace_raise_categories:
            raise RuntimeError(f"unsupported {category}")
        if category in self.trace_false_categories:
            return cast(list[str], False)
        return list(self.available_traces)

    def GetModule(self, name: str) -> object:
        if name == "AnalysisSetup":
            return self.analysis_setup
        if name == "ReportSetup":
            return self.report_setup
        if name == "Solutions":
            return self.solutions
        raise ValueError(name)

    def save_project(self, path: str) -> object:
        self.saved_paths.append(path)
        return self.save_project_result


class _FakeVersions:
    def __init__(self) -> None:
        self._list_installed_ansysem = object()
        self._installed_versions = object()
        self._stable_versions = object()
        self._current_version = object()
        self._current_student_version = object()
        self._latest_version = object()

    def get_version_env_variable(self, version: str) -> str | None:
        return f"ANSYSEM_ROOT_{version}"


def test_top_level_reexports_match_aedt_submodules() -> None:
    assert aedt_package.Hfss is Hfss
    assert Hfss is package_hfss
    assert aedt_package.aedt_versions is aedt_versions
    assert aedt_versions is package_aedt_versions
    assert aedt_package.Modeler3D is Modeler3D
    assert Modeler3D is package_modeler_3d
    assert Modeler3D is module_modeler_3d
    assert aedt_package.Object3d is Object3d
    assert Object3d is package_object_3d
    assert Object3d is module_object_3d


def test_failfast_helpers_enforce_name_limit() -> None:
    assert validate_aedt_name("a" * MAX_AEDT_NAME_LENGTH) == ("a" * MAX_AEDT_NAME_LENGTH)
    with pytest.raises(ValueError, match=rf"must be <= {MAX_AEDT_NAME_LENGTH} characters"):
        validate_aedt_name("a" * (MAX_AEDT_NAME_LENGTH + 1))
    with pytest.raises(RuntimeError, match=r"PyAEDT operation returned False: demo"):
        raise_on_false(False, operation="demo")


def test_create_box_raises_when_non_model_keyword_is_unsupported() -> None:
    modeler = _FakeModeler()
    modeler.raise_non_model_type_error = True

    with pytest.raises(TypeError, match="non_model unsupported"):
        create_box(
            cast(ModelerSession, modeler),
            origin=[0.0, 0.0, 0.0],
            sizes=[1.0, 1.0, 1.0],
            name="box_ok",
            material="vacuum",
            non_model=True,
        )
    assert modeler.create_box_calls == [
        {
            "origin": [0.0, 0.0, 0.0],
            "sizes": [1.0, 1.0, 1.0],
            "name": "box_ok",
            "material": "vacuum",
            "non_model": True,
        }
    ]
    with pytest.raises(ValueError, match=rf"must be <= {MAX_AEDT_NAME_LENGTH} characters"):
        create_box(
            cast(ModelerSession, modeler),
            origin=[0.0, 0.0, 0.0],
            sizes=[1.0, 1.0, 1.0],
            name="n" * (MAX_AEDT_NAME_LENGTH + 1),
            material="vacuum",
        )


def test_set_object_color_sets_rgb_tuple() -> None:
    obj = _FakeObject("box_ok", [0.0, 0.0, 0.0, 1.0, 1.0, 1.0])

    set_object_color(cast(Object3dRef, obj), color=(0, 128, 0))

    assert obj.color == (0, 128, 0)


def test_set_object_transparency_sets_float() -> None:
    obj = _FakeObject("box_ok", [0.0, 0.0, 0.0, 1.0, 1.0, 1.0])

    set_object_transparency(cast(Object3dRef, obj), transparency=0.85)

    assert obj.transparency == 0.85


def test_cover_lines_thicken_sheet_and_unite_raise_when_legacy_signatures_are_unsupported() -> None:
    modeler = _FakeModeler()
    modeler.cover_keyword_unsupported = True
    modeler.thicken_keyword_unsupported = True
    modeler.unite_keyword_unsupported = True
    modeler.unite_result = [_FakeObject("merged_name", [0.0, 0.0, 0.0, 1.0, 1.0, 1.0])]

    with pytest.raises(TypeError, match="assignment unsupported"):
        cover_lines(cast(ModelerSession, modeler), assignment="sheet_a")
    with pytest.raises(TypeError, match="assignment unsupported"):
        thicken_sheet(cast(ModelerSession, modeler), assignment="sheet_a", thickness=0.2)
    with pytest.raises(TypeError, match="assignment unsupported"):
        unite(
            cast(ModelerSession, modeler),
            targets=["a", "b"],
            error_context="merge",
        )


def test_sidecar_protocol_and_proxy_exports_are_explicit() -> None:
    assert aedt_protocols.__all__ == [
        "AedtVersionsSession",
        "AnalysisSetupModuleSession",
        "BoundaryModuleSession",
        "DesktopSession",
        "DesignSession",
        "HfssSession",
        "MaterialsSession",
        "MeshModuleSession",
        "ModelerSession",
        "Object3dRef",
        "ReportSetupModuleSession",
        "SolutionsModuleSession",
        "TraceProviderSession",
    ]
    assert aedt_proxies.__all__ == [
        "assign_lumped_port",
        "assign_radiation_boundary_to_faces",
        "cover_lines",
        "create_box",
        "create_cylinder",
        "create_group",
        "create_output_variable",
        "create_polyline",
        "create_region",
        "create_report",
        "delete_setup",
        "edit_sources",
        "ensure_ferrite_material",
        "get_boundary_names",
        "get_design_module",
        "get_report_names",
        "get_supported_traces",
        "get_version_env_variable",
        "insert_frequency_sweep",
        "insert_setup",
        "list_excitation_names",
        "object_bbox",
        "object_edge_samples_xy",
        "object_name",
        "point_xy",
        "release_desktop_session",
        "reset_aedt_versions_cache",
        "save_project",
        "set_object_color",
        "set_object_transparency",
        "set_object_model_state",
        "subtract",
        "thicken_sheet",
        "unite",
        "wrap_aedt_versions",
        "wrap_boundary_module",
        "wrap_design",
        "wrap_desktop",
        "wrap_hfss",
        "wrap_materials",
        "wrap_modeler",
        "wrap_object3d",
    ]


def test_modeler_geometry_helpers_raise_on_false() -> None:
    modeler = _FakeModeler()
    modeler.create_box_result = False
    modeler.create_cylinder_result = False
    modeler.create_polyline_result = False
    modeler.cover_result = False
    modeler.thicken_result = False
    modeler.unite_result = False
    modeler.subtract_result = False

    with pytest.raises(RuntimeError, match=r"create_box"):
        create_box(
            cast(ModelerSession, modeler),
            origin=[0.0, 0.0, 0.0],
            sizes=[1.0, 1.0, 1.0],
            name="box_a",
            material="vacuum",
        )
    with pytest.raises(RuntimeError, match=r"create_cylinder"):
        create_cylinder(
            cast(ModelerSession, modeler),
            cs_axis="Z",
            origin=[0.0, 0.0, 0.0],
            radius=1.0,
            height=2.0,
            name="cyl_a",
            material="vacuum",
        )
    with pytest.raises(RuntimeError, match=r"create_polyline"):
        create_polyline(
            cast(ModelerSession, modeler),
            points=[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
            name="line_a",
            cover_surface=False,
            close_surface=False,
        )
    with pytest.raises(RuntimeError, match=r"cover_lines"):
        cover_lines(cast(ModelerSession, modeler), assignment="sheet_a")
    with pytest.raises(RuntimeError, match=r"thicken_sheet"):
        thicken_sheet(cast(ModelerSession, modeler), assignment="sheet_a", thickness=0.2)
    with pytest.raises(RuntimeError, match=r"unite"):
        unite(
            cast(ModelerSession, modeler),
            targets=["a", "b"],
            error_context="merge",
        )
    with pytest.raises(RuntimeError, match=r"subtract"):
        subtract(
            cast(ModelerSession, modeler),
            blank_list=["blank_a"],
            tool_list=["tool_a"],
            keep_originals=True,
            context={"region": "blank_a"},
        )


def test_modeler_geometry_name_validators_cover_mutation_surfaces() -> None:
    modeler = _FakeModeler()
    too_long = "n" * (MAX_AEDT_NAME_LENGTH + 1)

    with pytest.raises(ValueError, match=rf"must be <= {MAX_AEDT_NAME_LENGTH} characters"):
        create_group(cast(ModelerSession, modeler), objects=[too_long], group_name="group_a")
    with pytest.raises(ValueError, match=rf"must be <= {MAX_AEDT_NAME_LENGTH} characters"):
        cover_lines(cast(ModelerSession, modeler), assignment=too_long)
    with pytest.raises(ValueError, match=rf"must be <= {MAX_AEDT_NAME_LENGTH} characters"):
        thicken_sheet(cast(ModelerSession, modeler), assignment=too_long, thickness=0.2)
    with pytest.raises(ValueError, match=rf"must be <= {MAX_AEDT_NAME_LENGTH} characters"):
        unite(
            cast(ModelerSession, modeler),
            targets=["a", too_long],
            error_context="merge",
        )
    with pytest.raises(ValueError, match=rf"must be <= {MAX_AEDT_NAME_LENGTH} characters"):
        subtract(
            cast(ModelerSession, modeler),
            blank_list=["blank_a"],
            tool_list=[too_long],
            keep_originals=True,
        )


def test_unite_short_circuits_single_target_and_rejects_empty_targets() -> None:
    modeler = _FakeModeler()

    assert unite(
        cast(ModelerSession, modeler),
        targets=["solo"],
        error_context="solo merge",
    ) == "solo"
    assert modeler.unite_calls == []

    with pytest.raises(ValueError, match=r"requires at least one target"):
        unite(
            cast(ModelerSession, modeler),
            targets=[],
            error_context="empty merge",
        )


def test_false_return_helpers_raise_and_validate_names() -> None:
    hfss = _FakeHfss()
    modeler = hfss.modeler
    boundary = _FakeBoundaryModule(assign_result=False)
    hfss.assign_boundary_result = False
    hfss.output_variable_result = False
    hfss.save_project_result = False
    hfss.delete_setup_result = False
    modeler.create_group_result = False
    modeler.create_region_result = False

    with pytest.raises(RuntimeError, match=r"create_group"):
        create_group(cast(ModelerSession, modeler), objects=["a"], group_name="group_a")
    with pytest.raises(RuntimeError, match=r"create_region"):
        create_region(cast(ModelerSession, modeler), pad_value=1, pad_type="abs", name="region_a")
    with pytest.raises(RuntimeError, match=r"assign_radiation_boundary_to_faces"):
        assign_radiation_boundary_to_faces(cast(HfssSession, hfss), [1], name="rad_a")
    with pytest.raises(RuntimeError, match=r"create_output_variable"):
        create_output_variable(cast(HfssSession, hfss), variable="var_a", expression="S(1,1)", solution="Setup1 : LastAdaptive")
    with pytest.raises(RuntimeError, match=r"save_project"):
        save_project(cast(HfssSession, hfss), path="/tmp/demo.aedt")
    with pytest.raises(RuntimeError, match=r"delete_setup"):
        delete_setup(cast(HfssSession, hfss), name="Setup1")
    with pytest.raises(RuntimeError, match=r"AssignLumpedPort"):
        assign_lumped_port(
            boundary,
            ["NAME:port_a", "Edges:=", [1, 2]],
            context="boundary",
        )
    with pytest.raises(ValueError, match=rf"must be <= {MAX_AEDT_NAME_LENGTH} characters"):
        create_group(cast(ModelerSession, modeler), objects=["a"], group_name=("g" * (MAX_AEDT_NAME_LENGTH + 6)))


def test_create_report_edit_sources_and_insert_helpers_validate_names() -> None:
    hfss = _FakeHfss()
    report_setup = hfss.report_setup

    create_report(
        report_setup,
        plot_name="plot_a",
        report_category="cat",
        plot_type="rect",
        setup_sweep_name="Setup1",
        context=[],
        variations=[],
        components=[],
        options=[],
    )
    assert get_report_names(report_setup) == ["plot_a"]
    assert report_setup.calls[0]["options"] == []

    solutions = hfss.solutions
    edit_sources(
        solutions,
        payload=[
            ["UseIncidentVoltage:=", True],
            ["Name:=", "TX_TML", "Magnitude:=", "1V"],
            ["Name:=", "RX_TML", "Magnitude:=", "1V"],
        ],
    )
    assert len(solutions.payloads) == 1

    insert_setup(hfss.analysis_setup, setup_type="HfssDriven", props=["NAME:Setup1"])
    insert_frequency_sweep(hfss.analysis_setup, setup_name="Setup1", props=["NAME:Sweep1"])
    assert hfss.analysis_setup.setup_calls == [("HfssDriven", ["NAME:Setup1"])]
    assert hfss.analysis_setup.sweep_calls == [("Setup1", ["NAME:Sweep1"])]

    with pytest.raises(ValueError, match=rf"must be <= {MAX_AEDT_NAME_LENGTH} characters"):
        create_report(
            report_setup,
            plot_name="p" * (MAX_AEDT_NAME_LENGTH + 1),
            report_category="cat",
            plot_type="rect",
            setup_sweep_name="Setup1",
            context=[],
            variations=[],
            components=[],
            options=[],
        )
    with pytest.raises(ValueError, match=rf"must be <= {MAX_AEDT_NAME_LENGTH} characters"):
        edit_sources(solutions, payload=[["Name:=", "s" * (MAX_AEDT_NAME_LENGTH + 1)]])
    with pytest.raises(ValueError, match=rf"must be <= {MAX_AEDT_NAME_LENGTH} characters"):
        insert_setup(hfss.analysis_setup, setup_type="HfssDriven", props=[f"NAME:{'s' * (MAX_AEDT_NAME_LENGTH + 1)}"])
    with pytest.raises(ValueError, match=rf"must be <= {MAX_AEDT_NAME_LENGTH} characters"):
        insert_frequency_sweep(
            hfss.analysis_setup,
            setup_name=("s" * (MAX_AEDT_NAME_LENGTH + 1)),
            props=["NAME:Sweep1"],
        )


def test_hfss_session_helpers_raise_on_false_for_report_source_setup_and_discovery() -> None:
    hfss = _FakeHfss()
    hfss.report_setup.create_report_result = False
    hfss.report_setup.report_names_result = False
    hfss.solutions.edit_sources_result = False
    hfss.analysis_setup.setup_result = False
    hfss.analysis_setup.sweep_result = False
    hfss.oboundary.get_boundaries_result = False
    hfss.excitation_names_result = False
    hfss.trace_false_categories = {"St("}

    with pytest.raises(RuntimeError, match=r"CreateReport"):
        create_report(
            hfss.report_setup,
            plot_name="plot_b",
            report_category="cat",
            plot_type="rect",
            setup_sweep_name="Setup1",
            context=[],
            variations=[],
            components=[],
            options=[],
        )
    with pytest.raises(RuntimeError, match=r"GetAllReportNames"):
        get_report_names(hfss.report_setup)
    with pytest.raises(RuntimeError, match=r"EditSources"):
        edit_sources(hfss.solutions, payload=[["Name:=", "TX_TML", "Magnitude:=", "1V"]])
    with pytest.raises(RuntimeError, match=r"InsertSetup"):
        insert_setup(hfss.analysis_setup, setup_type="HfssDriven", props=["NAME:Setup1"])
    with pytest.raises(RuntimeError, match=r"InsertFrequencySweep"):
        insert_frequency_sweep(hfss.analysis_setup, setup_name="Setup1", props=["NAME:Sweep1"])
    with pytest.raises(RuntimeError, match=r"GetBoundaries"):
        get_boundary_names(cast(HfssSession, hfss))
    with pytest.raises(RuntimeError, match=r"excitation_names"):
        list_excitation_names(cast(HfssSession, hfss))
    with pytest.raises(RuntimeError, match=r"get_traces_for_plot"):
        get_supported_traces(cast(HfssSession, hfss), categories=("St(",))


def test_remaining_name_validated_wrappers_enforce_limit() -> None:
    hfss = _FakeHfss()
    modeler = hfss.modeler
    too_long = "n" * (MAX_AEDT_NAME_LENGTH + 1)

    with pytest.raises(ValueError, match=rf"must be <= {MAX_AEDT_NAME_LENGTH} characters"):
        assign_lumped_port(hfss.oboundary, [f"NAME:{too_long}", "Edges:=", [1, 2]], context="boundary")
    with pytest.raises(ValueError, match=rf"must be <= {MAX_AEDT_NAME_LENGTH} characters"):
        create_cylinder(
            cast(ModelerSession, modeler),
            cs_axis="Z",
            origin=[0.0, 0.0, 0.0],
            radius=1.0,
            height=2.0,
            name=too_long,
            material="vacuum",
        )
    with pytest.raises(ValueError, match=rf"must be <= {MAX_AEDT_NAME_LENGTH} characters"):
        create_polyline(
            cast(ModelerSession, modeler),
            points=[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
            name=too_long,
            cover_surface=False,
            close_surface=False,
        )
    with pytest.raises(ValueError, match=rf"must be <= {MAX_AEDT_NAME_LENGTH} characters"):
        ensure_ferrite_material(cast(HfssSession, hfss), name=too_long, relative_permeability=500.0)
    with pytest.raises(ValueError, match=rf"must be <= {MAX_AEDT_NAME_LENGTH} characters"):
        get_design_module(hfss.odesign, too_long)
    with pytest.raises(ValueError, match=rf"must be <= {MAX_AEDT_NAME_LENGTH} characters"):
        insert_frequency_sweep(hfss.analysis_setup, setup_name="Setup1", props=[f"NAME:{too_long}"])


def test_capability_helpers_raise_when_required_features_are_missing() -> None:
    hfss = _FakeHfss()
    hfss.raise_excitation_access = True
    hfss.trace_raise_categories = {"S("}
    obj = _FakeObject("obj_a", [0.0, 0.0, 0.0, 2.0, 3.0, 4.0], callable_bbox=False)

    with pytest.raises(RuntimeError, match="no excitation access"):
        list_excitation_names(cast(HfssSession, hfss))
    with pytest.raises(RuntimeError, match="unsupported S\\("):
        get_supported_traces(cast(HfssSession, hfss), categories=("S(", "St("))
    assert object_bbox(obj) == [0.0, 0.0, 0.0, 2.0, 3.0, 4.0]
    assert object_edge_samples_xy(obj) == [(1.0, 2.0), (3.0, 4.0)]
    assert object_name(obj) == "obj_a"
    assert point_xy((9.0, 8.0, 7.0)) == (9.0, 8.0)
    assert point_xy(_FakePoint(5.0, 6.0)) == (5.0, 6.0)


def test_probe_helpers_raise_for_missing_geometry_and_boundary_capabilities() -> None:
    hfss = _FakeHfss()
    hfss.oboundary.get_boundaries_error = RuntimeError("no boundary module")

    class _SparseObject:
        name = ""
        edges = [object()]
        bounding_box = [0.0, 0.0, 0.0]

        def bbox(self) -> object:
            raise RuntimeError("bbox unavailable")

    sparse_object = _SparseObject()

    with pytest.raises(RuntimeError, match="no boundary module"):
        get_boundary_names(cast(HfssSession, hfss))
    with pytest.raises(ValueError, match="valid 6-value bbox"):
        object_bbox(cast(Object3dRef, sparse_object))
    with pytest.raises(AssertionError, match="midpoint"):
        object_edge_samples_xy(cast(Object3dRef, sparse_object))
    with pytest.raises(AssertionError, match="must not be empty"):
        object_name(cast(Object3dRef, sparse_object))
    with pytest.raises(AssertionError, match="required attribute x"):
        point_xy(object())


def test_release_desktop_session_kills_process_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    hfss = _FakeHfss()
    hfss.desktop_class = _FakeDesktop(result=False, pid=4321)
    kill_calls: list[list[str]] = []

    monkeypatch.setattr(subprocess, "run", lambda args, check=False: kill_calls.append(list(cast(list[str], args))))

    with pytest.raises(RuntimeError, match=r"release_desktop"):
        release_desktop_session(cast(HfssSession, hfss), close_projects=True, close_on_exit=True)

    assert kill_calls == [["kill", "-9", "4321"]]


def test_release_desktop_session_kills_process_when_release_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    hfss = _FakeHfss()
    hfss.desktop_class = _FakeDesktop(error=RuntimeError("desktop crash"), pid=9876)
    kill_calls: list[list[str]] = []

    monkeypatch.setattr(subprocess, "run", lambda args, check=False: kill_calls.append(list(cast(list[str], args))))

    with pytest.raises(RuntimeError, match=r"desktop crash"):
        release_desktop_session(cast(HfssSession, hfss), close_projects=False, close_on_exit=True)

    assert kill_calls == [["kill", "-9", "9876"]]


def test_material_and_version_helpers_work() -> None:
    hfss = _FakeHfss()
    material_name = ensure_ferrite_material(cast(HfssSession, hfss), name="ferrite_a", relative_permeability=500.0)
    assert material_name == "ferrite_a"
    material = hfss.materials.material_keys["ferrite_a"]
    assert getattr(material, "permeability") == "500.0"
    assert getattr(material, "permittivity") == "1.0"

    versions = _FakeVersions()
    wrapped_versions = wrap_aedt_versions(cast(AedtVersionsSession, versions))
    assert get_version_env_variable(wrapped_versions, "2025.2") == "ANSYSEM_ROOT_2025.2"
    reset_aedt_versions_cache(wrapped_versions)
    assert versions._list_installed_ansysem is None
    assert versions._latest_version is None


def test_ensure_ferrite_material_raises_on_material_creation_or_property_failure() -> None:
    hfss = _FakeHfss()
    hfss.materials.add_result = False

    with pytest.raises(RuntimeError, match=r"add_material"):
        ensure_ferrite_material(cast(HfssSession, hfss), name="ferrite_b", relative_permeability=500.0)

    hfss = _FakeHfss()
    hfss.materials.fail_attr_name = "permeability"

    with pytest.raises(RuntimeError, match=r"Failed to configure AEDT material property"):
        ensure_ferrite_material(cast(HfssSession, hfss), name="ferrite_c", relative_permeability=500.0)


def test_wrap_hfss_and_other_helpers_expose_proxy_views() -> None:
    hfss = _FakeHfss()
    proxy = wrap_hfss(cast(HfssSession, hfss))

    assert get_boundary_names(proxy) == ["P1", "Lumped Port"]
    set_object_model_state(proxy.modeler, _FakeObject("obj_a", [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]), model=False)
    assert hfss.modeler.set_model_state_calls == [("obj_a", False)]


def test_wrap_hfss_proxy_properties_support_downstream_helpers() -> None:
    hfss = _FakeHfss()
    proxy = wrap_hfss(cast(HfssSession, hfss))

    analysis_setup = get_design_module(proxy.odesign, "AnalysisSetup")
    assert analysis_setup is hfss.analysis_setup

    material_name = ensure_ferrite_material(proxy, name="ferrite_proxy", relative_permeability=275.0)
    assert material_name == "ferrite_proxy"
    assert getattr(hfss.materials.material_keys["ferrite_proxy"], "permeability") == "275.0"

    release_desktop_session(proxy, close_projects=False, close_on_exit=True)
    assert hfss.desktop_class.calls == [(False, True)]
