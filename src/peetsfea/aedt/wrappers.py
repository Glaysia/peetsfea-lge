from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import cast, overload

from ansys.aedt.core import Hfss as RawHfss
from ansys.aedt.core.modeler.cad.object_3d import Object3d as RawObject3d
from ansys.aedt.core.modeler.modeler_3d import Modeler3D as RawModeler3D

from peetsfea.aedt.failfast import raise_on_false, validate_aedt_name

__all__ = ["FORCED_SOLVE_CORES", "Hfss", "Modeler3D", "Object3d"]

# 0.3.7.1: every HFSS solve is pinned to this fixed core count. With AEDT's auto HPC settings (the
# default whenever a caller leaves cores=0, e.g. minimal_em), a single solve grabs all of the node's
# cores, so concurrent solves overcommit the CPU and thrash. Pinning each solve to a bounded core
# count is what makes N concurrent solves sustainable.
FORCED_SOLVE_CORES = 6

_RAW_UNSET = object()


def _require_attr(raw: object, name: str, *, owner: str) -> object:
    assert hasattr(raw, name), f"Raw {owner} is missing required attribute {name}"
    return getattr(raw, name)


def _require_callable_attr(raw: object, name: str, *, owner: str) -> Callable[..., object]:
    raw_attr = _require_attr(raw, name, owner=owner)
    assert callable(raw_attr), f"Raw {owner}.{name} must be callable"
    return cast(Callable[..., object], raw_attr)


def _require_not_none(value: object, *, context: str) -> object:
    assert not isinstance(value, type(None)), f"{context} must not be None"
    return value


def _require_int_attr(raw: object, name: str, *, owner: str) -> int:
    raw_value = _require_attr(raw, name, owner=owner)
    assert isinstance(raw_value, int), f"Raw {owner}.{name} must be int (actual={type(raw_value).__name__})"
    return raw_value


def _require_str_attr(raw: object, name: str, *, owner: str) -> str:
    raw_value = _require_attr(raw, name, owner=owner)
    assert isinstance(raw_value, str), f"Raw {owner}.{name} must be str (actual={type(raw_value).__name__})"
    assert raw_value, f"Raw {owner}.{name} must not be empty"
    return raw_value


def _require_mapping_attr(raw: object, name: str, *, owner: str) -> Mapping[str, object]:
    raw_value = _require_attr(raw, name, owner=owner)
    assert isinstance(raw_value, Mapping), (
        f"Raw {owner}.{name} must be Mapping (actual={type(raw_value).__name__})"
    )
    return cast(Mapping[str, object], raw_value)


def _require_str_sequence_result(
    raw_value: object,
    *,
    owner: str,
    method_name: str,
) -> list[str] | tuple[str, ...]:
    assert isinstance(raw_value, Sequence), (
        f"Raw {owner}.{method_name} result must be Sequence (actual={type(raw_value).__name__})"
    )
    assert not isinstance(raw_value, (str, bytes)), (
        f"Raw {owner}.{method_name} result must not be str/bytes (actual={type(raw_value).__name__})"
    )
    for item in raw_value:
        assert isinstance(item, str), (
            f"Raw {owner}.{method_name} items must be str (actual={type(item).__name__})"
        )
    return cast(list[str] | tuple[str, ...], raw_value)


def _extract_name_value(payload: list[object], *, prefix: str, field: str) -> str:
    for item in payload:
        if isinstance(item, str) and item.startswith(prefix):
            return item.removeprefix(prefix)
    raise ValueError(f"AEDT payload is missing required {field} entry with prefix {prefix!r}")


def _extract_boundary_name(payload: list[object]) -> str:
    for item in payload:
        if isinstance(item, str) and item.startswith("NAME:"):
            return item.removeprefix("NAME:")
    raise ValueError("AEDT boundary payload is missing required NAME entry")


def _extract_edit_source_names(payload: list[object]) -> list[str]:
    source_names: list[str] = []
    for item in payload:
        if not isinstance(item, list):
            continue
        for index, value in enumerate(item[:-1]):
            if value != "Name:=":
                continue
            candidate = item[index + 1]
            if isinstance(candidate, str) and candidate:
                source_names.append(candidate)
    return source_names


def _wrap_value(value: object) -> object:
    if isinstance(value, RawObject3d):
        return Object3d(_raw=value)
    if isinstance(value, list):
        return [_wrap_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_wrap_value(item) for item in value)
    return value


class _WrappedAccess:
    _raw: object
    _blocked_type_name: str
    _allowed_names: frozenset[str]

    def __getattribute__(self, name: str) -> object:
        if name in {
            "_raw",
            "_blocked_type_name",
            "_allowed_names",
            "__class__",
            "__dict__",
            "__getattribute__",
            "__setattr__",
            "__repr__",
        }:
            return object.__getattribute__(self, name)
        allowed_names = cast(frozenset[str], object.__getattribute__(self, "_allowed_names"))
        if name in allowed_names:
            return object.__getattribute__(self, name)
        raw = object.__getattribute__(self, "_raw")
        blocked_type_name = cast(str, object.__getattribute__(self, "_blocked_type_name"))
        raw_attr = _require_attr(raw, name, owner=blocked_type_name)
        if callable(raw_attr):
            raise AttributeError(f"Raw {blocked_type_name} method access is blocked: {name}")
        return raw_attr

    def __setattr__(self, name: str, value: object) -> None:
        if name in {"_raw", "_blocked_type_name", "_allowed_names"}:
            object.__setattr__(self, name, value)
            return
        raw = object.__getattribute__(self, "_raw")
        assert hasattr(raw, name), f"Raw {type(raw).__name__} is missing required attribute {name}"
        setattr(raw, name, value)

    def __repr__(self) -> str:
        return repr(object.__getattribute__(self, "_raw"))


class Object3d(RawObject3d, _WrappedAccess):
    _blocked_type_name = "Object3d"
    _allowed_names = frozenset({"name", "bbox", "bounding_box", "edges"})

    def __init__(self, *, _raw: object) -> None:
        object.__setattr__(self, "_raw", _raw)

    @property
    def name(self) -> str:
        return _require_str_attr(object.__getattribute__(self, "_raw"), "name", owner="Object3d")

    @property
    def bounding_box(self) -> object:
        return _require_attr(object.__getattribute__(self, "_raw"), "bounding_box", owner="Object3d")

    @property
    def edges(self) -> object:
        return _require_attr(object.__getattribute__(self, "_raw"), "edges", owner="Object3d")

    def bbox(self) -> object:
        raw_bbox = _require_attr(object.__getattribute__(self, "_raw"), "bbox", owner="Object3d")
        assert callable(raw_bbox), "Raw Object3d.bbox must be callable"
        return raw_bbox()


class BoundaryModule(_WrappedAccess):
    _blocked_type_name = "BoundaryModule"
    _allowed_names = frozenset({"AssignLumpedPort", "GetBoundaries"})

    def __init__(self, *, _raw: object) -> None:
        object.__setattr__(self, "_raw", _raw)

    def AssignLumpedPort(self, props: list[object]) -> object:
        boundary_name = _extract_boundary_name(props)
        validate_aedt_name(boundary_name, field="boundary_name")
        return raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "AssignLumpedPort", owner="BoundaryModule")(props),
            operation="AssignLumpedPort",
            context={"boundary_name": boundary_name},
        )

    def GetBoundaries(self) -> list[object] | tuple[object, ...]:
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "GetBoundaries", owner="BoundaryModule")(),
            operation="GetBoundaries",
        )
        return cast(list[object] | tuple[object, ...], raw_result)


class Desktop(_WrappedAccess):
    _blocked_type_name = "Desktop"
    _allowed_names = frozenset({"aedt_process_id", "GetMessages", "release_desktop"})

    def __init__(self, *, _raw: object) -> None:
        object.__setattr__(self, "_raw", _raw)

    @property
    def aedt_process_id(self) -> int:
        return _require_int_attr(object.__getattribute__(self, "_raw"), "aedt_process_id", owner="Desktop")

    def GetMessages(self, project_name: str, design_name: str, level: int) -> list[str] | tuple[str, ...]:
        raw_odesktop = _require_attr(object.__getattribute__(self, "_raw"), "odesktop", owner="Desktop")
        raw_result = _require_callable_attr(raw_odesktop, "GetMessages", owner="Desktop.odesktop")(
            project_name,
            design_name,
            level,
        )
        return _require_str_sequence_result(raw_result, owner="Desktop", method_name="GetMessages")

    def release_desktop(self, close_projects: bool, close_on_exit: bool) -> object:
        return raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "release_desktop", owner="Desktop")(
                close_projects=close_projects,
                close_on_exit=close_on_exit,
            ),
            operation="release_desktop",
            context={"close_projects": close_projects, "close_on_exit": close_on_exit},
        )


class Materials(_WrappedAccess):
    _blocked_type_name = "Materials"
    _allowed_names = frozenset({"material_keys", "exists_material", "add_material"})

    def __init__(self, *, _raw: object) -> None:
        object.__setattr__(self, "_raw", _raw)

    @property
    def material_keys(self) -> Mapping[str, object]:
        return _require_mapping_attr(object.__getattribute__(self, "_raw"), "material_keys", owner="Materials")

    def exists_material(self, name: str) -> object:
        return _require_callable_attr(object.__getattribute__(self, "_raw"), "exists_material", owner="Materials")(name)

    def add_material(self, name: str) -> object:
        validate_aedt_name(name, field="material_name")
        return raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "add_material", owner="Materials")(name),
            operation="add_material",
            context={"name": name},
        )


class AnalysisSetupModule(_WrappedAccess):
    _blocked_type_name = "AnalysisSetupModule"
    _allowed_names = frozenset({"InsertSetup", "InsertFrequencySweep"})

    def __init__(self, *, _raw: object) -> None:
        object.__setattr__(self, "_raw", _raw)

    def InsertSetup(self, setup_type: str, props: list[object]) -> object:
        setup_name = _extract_name_value(props, prefix="NAME:", field="setup_name")
        validate_aedt_name(setup_name, field="setup_name")
        return raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "InsertSetup", owner="AnalysisSetupModule")(setup_type, props),
            operation="InsertSetup",
            context={"setup_type": setup_type, "setup_name": setup_name},
        )

    def InsertFrequencySweep(self, setup_name: str, props: list[object]) -> object:
        validate_aedt_name(setup_name, field="setup_name")
        sweep_name = _extract_name_value(props, prefix="NAME:", field="sweep_name")
        validate_aedt_name(sweep_name, field="sweep_name")
        return raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "InsertFrequencySweep", owner="AnalysisSetupModule")(
                setup_name,
                props,
            ),
            operation="InsertFrequencySweep",
            context={"setup_name": setup_name, "sweep_name": sweep_name},
        )


class ReportSetupModule(_WrappedAccess):
    _blocked_type_name = "ReportSetupModule"
    _allowed_names = frozenset({"CreateReport", "ExportToFile", "GetAllReportNames"})

    def __init__(self, *, _raw: object) -> None:
        object.__setattr__(self, "_raw", _raw)

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
        validate_aedt_name(plot_name, field="plot_name")
        return raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "CreateReport", owner="ReportSetupModule")(
                plot_name,
                report_category,
                plot_type,
                setup_sweep_name,
                context,
                variations,
                components,
                options,
            ),
            operation="CreateReport",
            context={
                "plot_name": plot_name,
                "report_category": report_category,
                "plot_type": plot_type,
                "setup_sweep_name": setup_sweep_name,
            },
        )

    def GetAllReportNames(self) -> list[str] | tuple[str, ...]:
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "GetAllReportNames", owner="ReportSetupModule")(),
            operation="GetAllReportNames",
        )
        return cast(list[str] | tuple[str, ...], raw_result)

    def ExportToFile(self, report_name: str, export_path: str) -> object:
        validate_aedt_name(report_name, field="report_name")
        if export_path == "":
            raise ValueError("export_path must not be empty")
        return raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "ExportToFile", owner="ReportSetupModule")(
                report_name,
                export_path,
            ),
            operation="ReportSetup.ExportToFile",
            context={"report_name": report_name, "path": export_path},
        )


class SolutionsModule(_WrappedAccess):
    _blocked_type_name = "SolutionsModule"
    _allowed_names = frozenset({"EditSources"})

    def __init__(self, *, _raw: object) -> None:
        object.__setattr__(self, "_raw", _raw)

    def EditSources(self, payload: list[object]) -> object:
        return raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "EditSources", owner="SolutionsModule")(payload),
            operation="EditSources",
            context={"source_names": _extract_edit_source_names(payload)},
        )


class Design(_WrappedAccess):
    _blocked_type_name = "Design"
    _allowed_names = frozenset({"GetModule", "ValidateDesign"})

    def __init__(self, *, _raw: object) -> None:
        object.__setattr__(self, "_raw", _raw)

    def GetModule(self, name: str) -> object:
        validate_aedt_name(name, field="module_name")
        raw_module = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "GetModule", owner="Design")(name),
            operation="GetModule",
            context={"module_name": name},
        )
        if name == "AnalysisSetup":
            return AnalysisSetupModule(_raw=raw_module)
        if name == "ReportSetup":
            return ReportSetupModule(_raw=raw_module)
        if name == "Solutions":
            return SolutionsModule(_raw=raw_module)
        return raw_module

    def ValidateDesign(self) -> object:
        return raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "ValidateDesign", owner="Design")(),
            operation="ValidateDesign",
        )


class Modeler3D(RawModeler3D, _WrappedAccess):
    _blocked_type_name = "Modeler3D"
    _allowed_names = frozenset(
        {
            "create_box",
            "create_coordinate_system",
            "create_cylinder",
            "create_group",
            "create_polyline",
            "create_region",
            "cover_lines",
            "get_object_from_name",
            "get_edge_vertices",
            "get_face_area",
            "get_face_center",
            "get_face_edges",
            "get_face_vertices",
            "get_object_edges",
            "get_object_faces",
            "get_vertex_position",
            "import_3d_cad",
            "move",
            "object_names",
            "rotate",
            "set_working_coordinate_system",
            "set_object_model_state",
            "subtract",
            "thicken_sheet",
            "unite",
        }
    )

    def __init__(self, *, _raw: object) -> None:
        object.__setattr__(self, "_raw", _raw)

    @property
    def object_names(self) -> list[str]:
        raw_names = _require_str_sequence_result(
            _require_attr(object.__getattribute__(self, "_raw"), "object_names", owner="Modeler3D"),
            owner="Modeler3D",
            method_name="object_names",
        )
        names: list[str] = []
        for index, name in enumerate(raw_names):
            assert name, f"Raw Modeler3D.object_names[{index}] must not be empty"
            validate_aedt_name(name, field=f"object_names[{index}]")
            names.append(name)
        return names

    def create_box(self, **kwargs: object) -> object:
        name = kwargs.get("name")
        assert isinstance(name, str), "Raw Modeler3D.create_box requires a string name"
        validate_aedt_name(name, field="name")
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "create_box", owner="Modeler3D")(**kwargs),
            operation="create_box",
            context={"name": name},
        )
        return _wrap_value(raw_result)

    def create_coordinate_system(
        self,
        origin=None,
        reference_cs: str = "Global",
        name: str | None = None,
        mode: str = "axis",
        view: str = "iso",
        x_pointing=None,
        y_pointing=None,
        psi: int = 0,
        theta: int = 0,
        phi: int = 0,
        u=None,
    ) -> object:
        if name is not None:
            validate_aedt_name(name, field="name")
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "create_coordinate_system", owner="Modeler3D")(
                origin=origin,
                reference_cs=reference_cs,
                name=name,
                mode=mode,
                view=view,
                x_pointing=x_pointing,
                y_pointing=y_pointing,
                psi=psi,
                theta=theta,
                phi=phi,
                u=u,
            ),
            operation="create_coordinate_system",
            context={"name": name, "reference_cs": reference_cs},
        )
        return _wrap_value(raw_result)

    def create_cylinder(self, **kwargs: object) -> object:
        name = kwargs.get("name")
        assert isinstance(name, str), "Raw Modeler3D.create_cylinder requires a string name"
        validate_aedt_name(name, field="name")
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "create_cylinder", owner="Modeler3D")(**kwargs),
            operation="create_cylinder",
            context={"name": name},
        )
        return _wrap_value(raw_result)

    def create_group(self, *, objects: list[str], group_name: str) -> object:
        validate_aedt_name(group_name, field="group_name")
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "create_group", owner="Modeler3D")(
                objects=objects,
                group_name=group_name,
            ),
            operation="create_group",
            context={"group_name": group_name, "objects": list(objects)},
        )
        return _wrap_value(raw_result)

    def create_polyline(self, **kwargs: object) -> object:
        name = kwargs.get("name")
        assert isinstance(name, str), "Raw Modeler3D.create_polyline requires a string name"
        validate_aedt_name(name, field="name")
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "create_polyline", owner="Modeler3D")(**kwargs),
            operation="create_polyline",
            context={"name": name},
        )
        return _wrap_value(raw_result)

    def create_region(self, pad_value: int, pad_type: str, name: str) -> object:
        validate_aedt_name(name, field="name")
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "create_region", owner="Modeler3D")(
                pad_value=pad_value,
                pad_type=pad_type,
                name=name,
            ),
            operation="create_region",
            context={"pad_value": pad_value, "pad_type": pad_type, "name": name},
        )
        return _wrap_value(raw_result)

    def cover_lines(self, assignment: str) -> object:
        validate_aedt_name(assignment, field="assignment")
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "cover_lines", owner="Modeler3D")(assignment=assignment),
            operation="cover_lines",
            context={"assignment": assignment},
        )
        return _wrap_value(raw_result)

    def get_object_from_name(self, assignment: str) -> object:
        validate_aedt_name(assignment, field="assignment")
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "get_object_from_name", owner="Modeler3D")(assignment),
            operation="get_object_from_name",
            context={"assignment": assignment},
        )
        return _wrap_value(raw_result)

    def get_edge_vertices(self, assignment: int) -> list[int]:
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "get_edge_vertices", owner="Modeler3D")(assignment),
            operation="get_edge_vertices",
            context={"assignment": assignment},
        )
        return cast(list[int], raw_result)

    def get_face_area(self, assignment: int) -> float:
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "get_face_area", owner="Modeler3D")(assignment),
            operation="get_face_area",
            context={"assignment": assignment},
        )
        assert isinstance(raw_result, (int, float)), "Modeler3D.get_face_area must return a numeric value"
        return float(raw_result)

    def get_face_center(self, assignment: int) -> list[float]:
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "get_face_center", owner="Modeler3D")(assignment),
            operation="get_face_center",
            context={"assignment": assignment},
        )
        return cast(list[float], raw_result)

    def get_face_edges(self, assignment: int) -> list[int]:
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "get_face_edges", owner="Modeler3D")(assignment),
            operation="get_face_edges",
            context={"assignment": assignment},
        )
        return cast(list[int], raw_result)

    def get_face_vertices(self, assignment: int) -> list[int]:
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "get_face_vertices", owner="Modeler3D")(assignment),
            operation="get_face_vertices",
            context={"assignment": assignment},
        )
        return cast(list[int], raw_result)

    def get_object_edges(self, assignment: str) -> list[int]:
        validate_aedt_name(assignment, field="assignment")
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "get_object_edges", owner="Modeler3D")(assignment),
            operation="get_object_edges",
            context={"assignment": assignment},
        )
        return cast(list[int], raw_result)

    def get_object_faces(self, assignment: str) -> list[int]:
        validate_aedt_name(assignment, field="assignment")
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "get_object_faces", owner="Modeler3D")(assignment),
            operation="get_object_faces",
            context={"assignment": assignment},
        )
        return cast(list[int], raw_result)

    def get_vertex_position(self, assignment: int) -> list[float]:
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "get_vertex_position", owner="Modeler3D")(assignment),
            operation="get_vertex_position",
            context={"assignment": assignment},
        )
        return cast(list[float], raw_result)

    def import_3d_cad(
        self,
        input_file: str | Path,
        healing: bool = False,
        refresh_all_ids: bool = True,
        import_materials: bool = False,
        create_lightweight_part: bool = False,
        group_by_assembly: bool = False,
        create_group: bool = True,
        separate_disjoints_lumped_object: bool = False,
        import_free_surfaces: bool = False,
        point_coincidence_tolerance: float = 1e-6,
        reduce_stl: bool = False,
        reduce_percentage: int = 0,
        reduce_error: int = 0,
        merge_planar_faces: bool = True,
        merge_angle: float = 0.02,
    ) -> bool:
        input_file_path = Path(input_file)
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "import_3d_cad", owner="Modeler3D")(
                input_file=input_file_path,
                healing=healing,
                refresh_all_ids=refresh_all_ids,
                import_materials=import_materials,
                create_lightweight_part=create_lightweight_part,
                group_by_assembly=group_by_assembly,
                create_group=create_group,
                separate_disjoints_lumped_object=separate_disjoints_lumped_object,
                import_free_surfaces=import_free_surfaces,
                point_coincidence_tolerance=point_coincidence_tolerance,
                reduce_stl=reduce_stl,
                reduce_percentage=reduce_percentage,
                reduce_error=reduce_error,
                merge_planar_faces=merge_planar_faces,
                merge_angle=merge_angle,
            ),
            operation="import_3d_cad",
            context={
                "input_file": str(input_file_path),
                "healing": healing,
                "refresh_all_ids": refresh_all_ids,
                "import_materials": import_materials,
                "create_lightweight_part": create_lightweight_part,
                "group_by_assembly": group_by_assembly,
                "create_group": create_group,
                "separate_disjoints_lumped_object": separate_disjoints_lumped_object,
                "import_free_surfaces": import_free_surfaces,
                "point_coincidence_tolerance": point_coincidence_tolerance,
                "reduce_stl": reduce_stl,
                "reduce_percentage": reduce_percentage,
                "reduce_error": reduce_error,
                "merge_planar_faces": merge_planar_faces,
                "merge_angle": merge_angle,
            },
        )
        assert isinstance(raw_result, bool), (
            f"Modeler3D.import_3d_cad must return bool (actual={type(raw_result).__name__})"
        )
        return raw_result

    def move(self, assignment: object, vector: list[float]) -> object:
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "move", owner="Modeler3D")(
                assignment=assignment,
                vector=vector,
            ),
            operation="move",
            context={"assignment": assignment, "vector": list(vector)},
        )
        return _wrap_value(raw_result)

    def rotate(self, assignment: object, axis: str, angle: float = 90.0, units: str = "deg") -> object:
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "rotate", owner="Modeler3D")(
                assignment=assignment,
                axis=axis,
                angle=angle,
                units=units,
            ),
            operation="rotate",
            context={"assignment": assignment, "axis": axis, "angle": angle, "units": units},
        )
        return _wrap_value(raw_result)

    def set_working_coordinate_system(self, name: str) -> object:
        validate_aedt_name(name, field="name")
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "set_working_coordinate_system", owner="Modeler3D")(name),
            operation="set_working_coordinate_system",
            context={"name": name},
        )
        return _wrap_value(raw_result)

    def set_object_model_state(self, name: str, model: bool) -> object:
        validate_aedt_name(name, field="name")
        raw_setter = _require_callable_attr(object.__getattribute__(self, "_raw"), "set_object_model_state", owner="Modeler3D")
        return raise_on_false(
            raw_setter(name, model),
            operation="set_object_model_state",
            context={"name": name, "model": model},
        )

    def subtract(self, *, blank_list: list[str], tool_list: list[str], keep_originals: bool) -> object:
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "subtract", owner="Modeler3D")(
                blank_list=blank_list,
                tool_list=tool_list,
                keep_originals=keep_originals,
            ),
            operation="subtract",
            context={"blank_list": list(blank_list), "tool_list": list(tool_list), "keep_originals": keep_originals},
        )
        return _wrap_value(raw_result)

    def thicken_sheet(self, assignment: str, thickness: float) -> object:
        validate_aedt_name(assignment, field="assignment")
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "thicken_sheet", owner="Modeler3D")(
                assignment=assignment,
                thickness=thickness,
            ),
            operation="thicken_sheet",
            context={"assignment": assignment, "thickness": thickness},
        )
        return _wrap_value(raw_result)

    def unite(self, assignment: list[str]) -> object:
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "unite", owner="Modeler3D")(assignment=assignment),
            operation="unite",
            context={"assignment": list(assignment)},
        )
        return _wrap_value(raw_result)


class Hfss(RawHfss, _WrappedAccess):
    _blocked_type_name = "Hfss"
    _allowed_names = frozenset(
        {
            "__setitem__",
            "assign_finite_conductivity",
            "assign_material",
            "assign_radiation_boundary_to_faces",
            "analyze_setup",
            "change_validation_settings",
            "close_project",
            "create_output_variable",
            "delete_setup",
            "desktop_class",
            "excitation_names",
            "get_traces_for_plot",
            "materials",
            "modeler",
            "oboundary",
            "odesign",
            "project_name",
            "save_project",
            "setup_names",
            "stop_simulations",
        }
    )

    @overload
    def __init__(self, *, _raw: RawHfss) -> None: ...

    @overload
    def __init__(self, *args: object, **kwargs: object) -> None: ...

    def __init__(self, *args: object, _raw: RawHfss | object = _RAW_UNSET, **kwargs: object) -> None:
        raw_hfss: RawHfss
        if _raw is _RAW_UNSET:
            raw_hfss = cast(Callable[..., RawHfss], RawHfss)(*args, **kwargs)
        else:
            raw_hfss = cast(RawHfss, _raw)
        object.__setattr__(self, "_raw", raw_hfss)

    @property
    def modeler(self) -> Modeler3D:
        return Modeler3D(_raw=_require_attr(object.__getattribute__(self, "_raw"), "modeler", owner="Hfss"))

    @property
    def desktop_class(self) -> Desktop:
        return Desktop(_raw=_require_attr(object.__getattribute__(self, "_raw"), "desktop_class", owner="Hfss"))

    @property
    def odesign(self) -> Design:
        raw_design = _require_not_none(
            _require_attr(object.__getattribute__(self, "_raw"), "odesign", owner="Hfss"),
            context="Hfss.odesign",
        )
        assert not isinstance(raw_design, str), "Hfss.odesign must not be a string placeholder"
        return Design(_raw=raw_design)

    @property
    def materials(self) -> Materials:
        raw_materials = _require_not_none(
            _require_attr(object.__getattribute__(self, "_raw"), "materials", owner="Hfss"),
            context="Hfss.materials",
        )
        return Materials(_raw=raw_materials)

    @property
    def oboundary(self) -> BoundaryModule:
        raw_boundary = _require_not_none(
            _require_attr(object.__getattribute__(self, "_raw"), "oboundary", owner="Hfss"),
            context="Hfss.oboundary",
        )
        return BoundaryModule(_raw=raw_boundary)

    @property
    def excitation_names(self) -> list[str]:
        raw_names = raise_on_false(
            _require_attr(object.__getattribute__(self, "_raw"), "excitation_names", owner="Hfss"),
            operation="excitation_names",
        )
        return [str(name) for name in cast(Sequence[object], raw_names) if isinstance(name, str) and str(name).strip()]

    @property
    def setup_names(self) -> list[str]:
        raw_names = _require_attr(object.__getattribute__(self, "_raw"), "setup_names", owner="Hfss")
        return [str(name) for name in cast(Sequence[object], raw_names) if isinstance(name, str)]

    def __setitem__(self, key: str, value: str) -> None:
        _require_callable_attr(object.__getattribute__(self, "_raw"), "__setitem__", owner="Hfss")(key, value)

    def assign_material(self, assignment: str | list[str], material: str) -> object:
        validate_aedt_name(material, field="material")
        if isinstance(assignment, str):
            validate_aedt_name(assignment, field="assignment")
        else:
            if len(assignment) == 0:
                raise ValueError("assignment must not be empty")
            for index, object_name in enumerate(assignment):
                validate_aedt_name(object_name, field=f"assignment[{index}]")
        return raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "assign_material", owner="Hfss")(
                assignment=assignment,
                material=material,
            ),
            operation="assign_material",
            context={"assignment": assignment, "material": material},
        )

    def assign_finite_conductivity(
        self,
        assignment: str | list[object],
        *,
        material: str,
        use_thickness: bool,
        thickness: str,
        is_two_side: bool,
        name: str,
    ) -> object:
        validate_aedt_name(material, field="material")
        validate_aedt_name(name, field="boundary_name")
        if isinstance(assignment, str):
            validate_aedt_name(assignment, field="assignment")
        return raise_on_false(
            _require_callable_attr(
                object.__getattribute__(self, "_raw"),
                "assign_finite_conductivity",
                owner="Hfss",
            )(
                assignment=assignment,
                material=material,
                use_thickness=use_thickness,
                thickness=thickness,
                is_two_side=is_two_side,
                name=name,
            ),
            operation="assign_finite_conductivity",
            context={
                "assignment": assignment,
                "material": material,
                "use_thickness": use_thickness,
                "thickness": thickness,
                "is_two_side": is_two_side,
                "name": name,
            },
        )

    def assign_radiation_boundary_to_faces(self, assignment: object, name: str) -> object:
        validate_aedt_name(name, field="boundary_name")
        return raise_on_false(
            _require_callable_attr(
                object.__getattribute__(self, "_raw"),
                "assign_radiation_boundary_to_faces",
                owner="Hfss",
            )(assignment, name=name),
            operation="assign_radiation_boundary_to_faces",
            context={"assignment": assignment, "name": name},
        )

    def analyze_setup(self, name: str, blocking: bool = True, cores: int = 0, gpus: int = 0) -> object:
        validate_aedt_name(name, field="setup_name")
        # 0.3.7.1: force every solve onto a fixed core count (FORCED_SOLVE_CORES) regardless of the
        # caller's value. AEDT's auto HPC settings otherwise consume all node cores, so concurrent
        # solves thrash. Manual NumCores only takes effect with UseAutoSettings off, so disable it.
        cores = FORCED_SOLVE_CORES
        use_auto_settings = False
        return raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "analyze_setup", owner="Hfss")(
                name,
                cores=cores,
                gpus=gpus,
                use_auto_settings=use_auto_settings,
                blocking=blocking,
            ),
            operation="analyze_setup",
            context={"setup_name": name, "blocking": blocking, "cores": cores, "gpus": gpus},
        )

    def stop_simulations(self, clean_stop: bool = True) -> object:
        return _require_callable_attr(object.__getattribute__(self, "_raw"), "stop_simulations", owner="Hfss")(
            clean_stop=clean_stop,
        )

    def create_output_variable(self, variable: str, expression: str, solution: str) -> object:
        validate_aedt_name(variable, field="variable")
        return raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "create_output_variable", owner="Hfss")(
                variable=variable,
                expression=expression,
                solution=solution,
            ),
            operation="create_output_variable",
            context={"variable": variable, "solution": solution, "expression": expression},
        )

    def change_validation_settings(
        self,
        entity_check_level: str = "Strict",
        ignore_unclassified: bool = False,
        skip_intersections: bool = False,
    ) -> object:
        if entity_check_level not in ("Strict", "Basic", "Warning Only", "None"):
            raise ValueError(
                "Hfss.change_validation_settings entity_check_level must be one of "
                "['Strict', 'Basic', 'Warning Only', 'None'] "
                f"(actual={entity_check_level!r})"
            )
        return raise_on_false(
            _require_callable_attr(
                object.__getattribute__(self, "_raw"),
                "change_validation_settings",
                owner="Hfss",
            )(
                entity_check_level=entity_check_level,
                ignore_unclassified=ignore_unclassified,
                skip_intersections=skip_intersections,
            ),
            operation="change_validation_settings",
            context={
                "entity_check_level": entity_check_level,
                "ignore_unclassified": ignore_unclassified,
                "skip_intersections": skip_intersections,
            },
        )

    def delete_setup(self, name: str) -> object:
        validate_aedt_name(name, field="setup_name")
        return raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "delete_setup", owner="Hfss")(name),
            operation="delete_setup",
            context={"name": name},
        )

    def get_traces_for_plot(
        self,
        get_self_terms: bool,
        get_mutual_terms: bool,
        first_element_filter: str,
        second_element_filter: str,
        category: str,
        differential_pairs: Sequence[object],
    ) -> list[str]:
        raw_result = raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "get_traces_for_plot", owner="Hfss")(
                get_self_terms=get_self_terms,
                get_mutual_terms=get_mutual_terms,
                first_element_filter=first_element_filter,
                second_element_filter=second_element_filter,
                category=category,
                differential_pairs=list(differential_pairs),
            ),
            operation="get_traces_for_plot",
            context={"category": category},
        )
        return [str(name) for name in cast(Sequence[object], raw_result) if isinstance(name, str)]

    def save_project(self, path: str) -> object:
        return raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "save_project", owner="Hfss")(path),
            operation="save_project",
            context={"path": path},
        )

    def close_project(self, name: str, save: bool = True) -> object:
        validate_aedt_name(name, field="project_name")
        return raise_on_false(
            _require_callable_attr(object.__getattribute__(self, "_raw"), "close_project", owner="Hfss")(
                name=name,
                save=save,
            ),
            operation="close_project",
            context={"name": name, "save": save},
        )

    @property
    def project_name(self) -> str:
        return _require_str_attr(object.__getattribute__(self, "_raw"), "project_name", owner="Hfss")
