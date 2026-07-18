from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping, Sequence
from typing import cast

from peetsfea.aedt.failfast import raise_on_false, validate_aedt_name
from peetsfea.aedt.protocols import (
    AedtVersionsSession,
    AnalysisSetupModuleSession,
    BoundaryModuleSession,
    DesktopSession,
    DesignSession,
    HfssSession,
    MaterialsSession,
    ModelerSession,
    Object3dRef,
    ReportSetupModuleSession,
    SolutionsModuleSession,
    TraceProviderSession,
)

__all__ = [
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

_CACHE_RESET = object()
_EMPTY_CONTEXT: Mapping[str, object] = {}


class _ProxyBase:
    def __init__(self, raw: object) -> None:
        self.raw = raw

    def __getattr__(self, name: str) -> object:
        return getattr(self.raw, name)


def _require_attr(raw: object, name: str, *, owner: str) -> object:
    assert hasattr(raw, name), f"Raw {owner} is missing required attribute {name}"
    return getattr(raw, name)


def _require_callable_attr(raw: object, name: str, *, owner: str) -> Callable[..., object]:
    attr = _require_attr(raw, name, owner=owner)
    assert callable(attr), f"Raw {owner}.{name} must be callable"
    return cast(Callable[..., object], attr)


def _require_str_attr(raw: object, name: str, *, owner: str) -> str:
    attr = _require_attr(raw, name, owner=owner)
    assert isinstance(attr, str), f"Raw {owner}.{name} must be str (actual={type(attr).__name__})"
    assert attr, f"Raw {owner}.{name} must not be empty"
    return attr


def _require_int_attr(raw: object, name: str, *, owner: str) -> int:
    attr = _require_attr(raw, name, owner=owner)
    assert isinstance(attr, int), f"Raw {owner}.{name} must be int (actual={type(attr).__name__})"
    return attr


def _require_sequence_attr(raw: object, name: str, *, owner: str) -> Sequence[object]:
    attr = _require_attr(raw, name, owner=owner)
    assert isinstance(attr, Sequence), f"Raw {owner}.{name} must be a sequence (actual={type(attr).__name__})"
    return cast(Sequence[object], attr)


def _require_mapping_attr(raw: object, name: str, *, owner: str) -> Mapping[str, object]:
    attr = _require_attr(raw, name, owner=owner)
    assert isinstance(attr, Mapping), f"Raw {owner}.{name} must be a mapping (actual={type(attr).__name__})"
    return cast(Mapping[str, object], attr)


class AedtVersionsProxy(_ProxyBase):
    pass


class BoundaryModuleProxy(_ProxyBase):
    pass


class DesktopProxy(_ProxyBase):
    def GetMessages(self, project_name: str, design_name: str, level: int) -> list[str] | tuple[str, ...]:
        raw_odesktop = _require_attr(self.raw, "odesktop", owner="Desktop")
        raw_result = _require_callable_attr(raw_odesktop, "GetMessages", owner="Desktop.odesktop")(
            project_name,
            design_name,
            level,
        )
        assert isinstance(raw_result, Sequence), (
            f"Raw Desktop.odesktop.GetMessages result must be Sequence (actual={type(raw_result).__name__})"
        )
        assert not isinstance(raw_result, (str, bytes)), (
            f"Raw Desktop.odesktop.GetMessages result must not be str/bytes (actual={type(raw_result).__name__})"
        )
        for item in raw_result:
            assert isinstance(item, str), (
                f"Raw Desktop.odesktop.GetMessages items must be str (actual={type(item).__name__})"
            )
        return cast(list[str] | tuple[str, ...], raw_result)


class DesignProxy(_ProxyBase):
    pass


class MaterialsProxy(_ProxyBase):
    pass


class ModelerProxy(_ProxyBase):
    pass


class Object3dProxy(_ProxyBase):
    pass


class HfssProxy(_ProxyBase):
    @property
    def modeler(self) -> ModelerSession:
        raw_modeler = _require_attr(self.raw, "modeler", owner="Hfss")
        return wrap_modeler(cast(ModelerSession, raw_modeler))

    @property
    def desktop_class(self) -> DesktopSession:
        raw_desktop = _require_attr(self.raw, "desktop_class", owner="Hfss")
        return wrap_desktop(cast(DesktopSession, raw_desktop))

    @property
    def odesign(self) -> DesignSession:
        raw_design = _require_attr(self.raw, "odesign", owner="Hfss")
        assert not isinstance(raw_design, str), "Raw Hfss.odesign must not be a string placeholder"
        return wrap_design(cast(DesignSession, raw_design))

    @property
    def materials(self) -> MaterialsSession:
        raw_materials = _require_attr(self.raw, "materials", owner="Hfss")
        return wrap_materials(cast(MaterialsSession, raw_materials))

    @property
    def oboundary(self) -> BoundaryModuleSession:
        raw_boundary = _require_attr(self.raw, "oboundary", owner="Hfss")
        return wrap_boundary_module(cast(BoundaryModuleSession, raw_boundary))


def wrap_aedt_versions(raw: AedtVersionsSession) -> AedtVersionsSession:
    return cast(AedtVersionsSession, AedtVersionsProxy(raw))


def wrap_boundary_module(raw: BoundaryModuleSession) -> BoundaryModuleSession:
    return cast(BoundaryModuleSession, BoundaryModuleProxy(raw))


def wrap_design(raw: DesignSession) -> DesignSession:
    return cast(DesignSession, DesignProxy(raw))


def wrap_desktop(raw: DesktopSession) -> DesktopSession:
    return cast(DesktopSession, DesktopProxy(raw))


def wrap_hfss(raw: HfssSession) -> HfssSession:
    return cast(HfssSession, HfssProxy(raw))


def wrap_materials(raw: MaterialsSession) -> MaterialsSession:
    return cast(MaterialsSession, MaterialsProxy(raw))


def wrap_modeler(raw: ModelerSession) -> ModelerSession:
    return cast(ModelerSession, ModelerProxy(raw))


def wrap_object3d(raw: Object3dRef) -> Object3dRef:
    return cast(Object3dRef, Object3dProxy(raw))


def _unwrap(value: object) -> object:
    if isinstance(value, _ProxyBase):
        return value.raw
    if hasattr(value, "_raw"):
        raw_value = getattr(value, "_raw")
        assert raw_value is not None, f"Object of type {type(value).__name__} has null _raw"
        return raw_value
    return value


def _unwrap_boundary_module(boundary_module: object) -> BoundaryModuleSession:
    return cast(BoundaryModuleSession, _unwrap(boundary_module))


def _unwrap_desktop(hfss: HfssSession) -> DesktopSession:
    return cast(DesktopSession, _unwrap(_require_attr(hfss, "desktop_class", owner="Hfss")))


def _unwrap_design(design: object) -> DesignSession:
    assert not isinstance(design, str), "AEDT design placeholder must not be a string"
    return cast(DesignSession, _unwrap(design))


def _unwrap_materials(materials: object) -> MaterialsSession:
    return cast(MaterialsSession, _unwrap(materials))


def _unwrap_modeler(modeler: ModelerSession) -> ModelerSession:
    return cast(ModelerSession, _unwrap(modeler))


def _unwrap_object(obj: Object3dRef) -> object:
    return _unwrap(obj)


def _unwrap_report_setup(report_setup: object) -> ReportSetupModuleSession:
    return cast(ReportSetupModuleSession, _unwrap(report_setup))


def _unwrap_analysis_setup(analysis_setup: object) -> AnalysisSetupModuleSession:
    return cast(AnalysisSetupModuleSession, _unwrap(analysis_setup))


def _unwrap_solutions(solutions: object) -> SolutionsModuleSession:
    return cast(SolutionsModuleSession, _unwrap(solutions))


def _normalize_name_result(result: object) -> str:
    if isinstance(result, list):
        assert result, "AEDT name result list must not be empty"
        first = result[0]
        if isinstance(first, str):
            assert first, "AEDT name result must not be empty"
            return first
        return object_name(cast(Object3dRef, first))
    if isinstance(result, str):
        assert result, "AEDT name result must not be empty"
        return result
    return object_name(cast(Object3dRef, result))


def _extract_name_value(payload: list[object], *, prefix: str, field: str) -> str:
    for item in payload:
        if isinstance(item, str) and item.startswith(prefix):
            name = item.removeprefix(prefix)
            validate_aedt_name(name, field=field)
            return name
    raise ValueError(f"AEDT payload is missing required {field} entry with prefix {prefix!r}")


def _validate_edit_sources_payload(payload: list[object]) -> None:
    for item in payload:
        if not isinstance(item, list):
            continue
        for index, value in enumerate(item[:-1]):
            if value != "Name:=":
                continue
            candidate = item[index + 1]
            if isinstance(candidate, str) and candidate:
                validate_aedt_name(candidate, field="source_name")


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


def _validate_name_list(names: Sequence[str], *, field: str) -> None:
    for index, name in enumerate(names):
        validate_aedt_name(name, field=f"{field}[{index}]")


def _set_material_property(material: object, *, material_name: str, attr_name: str, attr_value: str) -> None:
    try:
        setattr(material, attr_name, attr_value)
    except Exception as exc:
        raise RuntimeError(
            "Failed to configure AEDT material property "
            f"(material={material_name}, property={attr_name}, value={attr_value!r})"
        ) from exc


def assign_lumped_port(boundary_module: object, payload: list[object], *, context: str) -> None:
    raw_boundary_module = cast(BoundaryModuleSession, _unwrap(boundary_module))
    boundary_name = _extract_name_value(payload, prefix="NAME:", field="boundary_name")
    result = raw_boundary_module.AssignLumpedPort(payload)
    raise_on_false(
        result,
        operation="AssignLumpedPort",
        context={"context": context, "boundary_name": boundary_name},
    )


def assign_radiation_boundary_to_faces(
    hfss: HfssSession,
    assignment: object,
    *,
    name: str,
) -> None:
    validate_aedt_name(name, field="boundary_name")
    raw_hfss = cast(HfssSession, _unwrap(hfss))
    raise_on_false(
        raw_hfss.assign_radiation_boundary_to_faces(assignment, name=name),
        operation="assign_radiation_boundary_to_faces",
        context={"name": name, "assignment": assignment},
    )


def cover_lines(modeler: ModelerSession, *, assignment: str) -> object:
    validate_aedt_name(assignment, field="assignment")
    raw_modeler = _unwrap_modeler(modeler)
    try:
        return raise_on_false(
            raw_modeler.cover_lines(assignment=assignment),
            operation="cover_lines",
            context={"assignment": assignment},
        )
    except TypeError:
        raise


def create_box(
    modeler: ModelerSession,
    *,
    origin: list[float],
    sizes: list[float],
    name: str,
    material: str,
    non_model: bool = False,
) -> Object3dRef:
    validate_aedt_name(name, field="name")
    raw_modeler = _unwrap_modeler(modeler)
    result = raise_on_false(
        raw_modeler.create_box(
            origin=origin,
            sizes=sizes,
            name=name,
            material=material,
            non_model=non_model,
        ),
        operation="create_box",
        context={"name": name, "material": material, "non_model": non_model},
    )
    return cast(Object3dRef, result)


def create_cylinder(modeler: ModelerSession, **kwargs: object) -> Object3dRef:
    raw_modeler = _unwrap_modeler(modeler)
    assert "name" in kwargs, "create_cylinder requires name"
    name = kwargs["name"]
    assert isinstance(name, str), f"create_cylinder name must be str (actual={type(name).__name__})"
    validate_aedt_name(name, field="name")
    result = raise_on_false(
        raw_modeler.create_cylinder(**kwargs),
        operation="create_cylinder",
        context={"name": name},
    )
    return cast(Object3dRef, result)


def set_object_color(obj: object, *, color: tuple[int, int, int]) -> None:
    if len(color) != 3:
        raise ValueError(f"object color must be a 3-tuple (actual={color})")
    validated: list[int] = []
    for component in color:
        if isinstance(component, bool) or not isinstance(component, int):
            raise ValueError(f"object color components must be ints in [0,255] (actual={color})")
        if component < 0 or component > 255:
            raise ValueError(f"object color components must be ints in [0,255] (actual={color})")
        validated.append(component)
    raw_obj = _unwrap_object(cast(Object3dRef, obj))
    assert hasattr(raw_obj, "color"), f"Object {type(raw_obj).__name__} is missing required color attribute"
    setattr(raw_obj, "color", (validated[0], validated[1], validated[2]))


def set_object_transparency(obj: object, *, transparency: float) -> None:
    if transparency < 0.0 or transparency > 1.0:
        raise ValueError(f"object transparency must be in [0,1] (actual={transparency})")
    raw_obj = _unwrap_object(cast(Object3dRef, obj))
    assert hasattr(raw_obj, "transparency"), f"Object {type(raw_obj).__name__} is missing required transparency attribute"
    setattr(raw_obj, "transparency", transparency)


def create_group(modeler: ModelerSession, *, objects: list[str], group_name: str) -> str:
    validate_aedt_name(group_name, field="group_name")
    _validate_name_list(objects, field="objects")
    raw_modeler = _unwrap_modeler(modeler)
    result = raise_on_false(
        raw_modeler.create_group(objects=objects, group_name=group_name),
        operation="create_group",
        context={"group_name": group_name, "objects": list(objects)},
    )
    return str(result)


def delete_setup(hfss: HfssSession, *, name: str) -> None:
    validate_aedt_name(name, field="name")
    raw_hfss = cast(HfssSession, _unwrap(hfss))
    raise_on_false(
        raw_hfss.delete_setup(name),
        operation="delete_setup",
        context={"name": name},
    )


def create_output_variable(
    hfss: HfssSession,
    *,
    variable: str,
    expression: str,
    solution: str,
) -> None:
    validate_aedt_name(variable, field="variable")
    raw_hfss = cast(HfssSession, _unwrap(hfss))
    raise_on_false(
        raw_hfss.create_output_variable(variable=variable, expression=expression, solution=solution),
        operation="create_output_variable",
        context={"variable": variable, "solution": solution, "expression": expression},
    )


def create_polyline(modeler: ModelerSession, **kwargs: object) -> Object3dRef:
    raw_modeler = _unwrap_modeler(modeler)
    assert "name" in kwargs, "create_polyline requires name"
    name = kwargs["name"]
    assert isinstance(name, str), f"create_polyline name must be str (actual={type(name).__name__})"
    validate_aedt_name(name, field="name")
    result = raise_on_false(
        raw_modeler.create_polyline(**kwargs),
        operation="create_polyline",
        context={"name": name},
    )
    return cast(Object3dRef, result)


def create_region(modeler: ModelerSession, *, pad_value: int, pad_type: str, name: str) -> object:
    validate_aedt_name(name, field="name")
    raw_modeler = _unwrap_modeler(modeler)
    return raise_on_false(
        raw_modeler.create_region(pad_value=pad_value, pad_type=pad_type, name=name),
        operation="create_region",
        context={"pad_value": pad_value, "pad_type": pad_type, "name": name},
    )


def create_report(
    report_setup: object,
    *,
    plot_name: str,
    report_category: str,
    plot_type: str,
    setup_sweep_name: str,
    context: list[object],
    variations: list[object],
    components: list[object],
    options: list[object],
) -> None:
    validate_aedt_name(plot_name, field="plot_name")
    raw_report_setup = _unwrap_report_setup(report_setup)
    result = raw_report_setup.CreateReport(
        plot_name,
        report_category,
        plot_type,
        setup_sweep_name,
        context,
        variations,
        components,
        options,
    )
    raise_on_false(
        result,
        operation="CreateReport",
        context={
            "plot_name": plot_name,
            "report_category": report_category,
            "plot_type": plot_type,
            "setup_sweep_name": setup_sweep_name,
        },
    )


def edit_sources(solutions: object, *, payload: list[object]) -> None:
    _validate_edit_sources_payload(payload)
    raw_solutions = _unwrap_solutions(solutions)
    raise_on_false(
        raw_solutions.EditSources(payload),
        operation="EditSources",
        context={"source_names": _extract_edit_source_names(payload)},
    )


def ensure_ferrite_material(
    hfss: HfssSession,
    *,
    name: str,
    relative_permeability: float,
    permittivity: str = "1.0",
    conductivity: str = "0",
    dielectric_loss_tangent: str = "0",
    magnetic_loss_tangent: str = "0",
) -> str:
    validate_aedt_name(name, field="name")
    materials = _unwrap_materials(_require_attr(hfss, "materials", owner="Hfss"))
    exists = bool(materials.exists_material(name))
    if exists:
        material_keys = materials.material_keys
        assert name in material_keys, f"AEDT material_keys must contain {name} after exists_material(name)=True"
        material = material_keys[name]
    else:
        material = raise_on_false(
            materials.add_material(name),
            operation="add_material",
            context={"name": name},
        )
    for attr_name, attr_value in (
        ("permeability", str(float(relative_permeability))),
        ("permittivity", permittivity),
        ("conductivity", conductivity),
        ("dielectric_loss_tangent", dielectric_loss_tangent),
        ("magnetic_loss_tangent", magnetic_loss_tangent),
    ):
        _set_material_property(
            material,
            material_name=name,
            attr_name=attr_name,
            attr_value=attr_value,
        )
    return name


def get_boundary_names(hfss: HfssSession) -> list[str]:
    boundary_module = _unwrap_boundary_module(_require_attr(hfss, "oboundary", owner="Hfss"))
    try:
        raw_result = boundary_module.GetBoundaries()
    except Exception:
        raise
    raw_names = list(
        cast(
            list[object] | tuple[object, ...],
            raise_on_false(raw_result, operation="GetBoundaries"),
        )
    )
    return [str(name) for name in raw_names if isinstance(name, str) and str(name).strip()]


def get_design_module(design: object, name: str) -> object:
    validate_aedt_name(name, field="module_name")
    raw_design = _unwrap_design(design)
    return raise_on_false(
        raw_design.GetModule(name),
        operation="GetModule",
        context={"module_name": name},
    )


def get_report_names(report_setup: object) -> list[str]:
    raw_report_setup = _unwrap_report_setup(report_setup)
    raw_names = raise_on_false(
        raw_report_setup.GetAllReportNames(),
        operation="GetAllReportNames",
    )
    return [str(name) for name in raw_names if isinstance(name, str)]


def insert_frequency_sweep(analysis_setup: object, *, setup_name: str, props: list[object]) -> None:
    validate_aedt_name(setup_name, field="setup_name")
    raw_analysis_setup = _unwrap_analysis_setup(analysis_setup)
    sweep_name = _extract_name_value(props, prefix="NAME:", field="sweep_name")
    raise_on_false(
        raw_analysis_setup.InsertFrequencySweep(setup_name, props),
        operation="InsertFrequencySweep",
        context={"setup_name": setup_name, "sweep_name": sweep_name},
    )


def insert_setup(analysis_setup: object, *, setup_type: str, props: list[object]) -> None:
    raw_analysis_setup = _unwrap_analysis_setup(analysis_setup)
    setup_name = _extract_name_value(props, prefix="NAME:", field="setup_name")
    raise_on_false(
        raw_analysis_setup.InsertSetup(setup_type, props),
        operation="InsertSetup",
        context={"setup_type": setup_type, "setup_name": setup_name},
    )


def get_supported_traces(
    provider: TraceProviderSession,
    *,
    categories: Sequence[str],
) -> list[str]:
    raw_provider = cast(TraceProviderSession, _unwrap(provider))
    traces: list[str] = []
    for category in categories:
        try:
            raw_result = raw_provider.get_traces_for_plot(
                get_self_terms=True,
                get_mutual_terms=True,
                first_element_filter="",
                second_element_filter="",
                category=category,
                differential_pairs=(),
            )
        except Exception:
            raise
        trace_names = raise_on_false(
            raw_result,
            operation="get_traces_for_plot",
            context={"category": category},
        )
        traces.extend([str(name) for name in trace_names if isinstance(name, str) and str(name).strip()])
    return traces


def get_version_env_variable(aedt_versions: AedtVersionsSession | AedtVersionsProxy, version: str) -> str:
    raw_versions = cast(AedtVersionsSession, _unwrap(aedt_versions))
    return raw_versions.get_version_env_variable(version)


def list_excitation_names(hfss: HfssSession) -> list[str]:
    raw_hfss = cast(HfssSession, _unwrap(hfss))
    raw_names_obj = _require_attr(raw_hfss, "excitation_names", owner="Hfss")
    raw_names = list(
        cast(
            Sequence[object],
            raise_on_false(raw_names_obj, operation="excitation_names"),
        )
    )
    return [str(name) for name in raw_names if isinstance(name, str) and str(name).strip()]


def object_bbox(obj: Object3dRef) -> list[float]:
    raw_obj = _unwrap_object(obj)
    attr = _require_attr(raw_obj, "bounding_box", owner=type(raw_obj).__name__)
    raw_bbox = attr() if callable(attr) else attr
    if isinstance(raw_bbox, (tuple, list)) and len(raw_bbox) >= 6:
        values: list[float] = []
        for item in raw_bbox[:6]:
            if isinstance(item, (int, float)):
                values.append(float(item))
        if len(values) == 6:
            return values
    raise ValueError(f"Object {type(raw_obj).__name__} is missing a valid 6-value bbox")


def object_edge_samples_xy(obj: Object3dRef, *, limit: int = 8) -> list[tuple[float, float]]:
    raw_obj = _unwrap_object(obj)
    samples: list[tuple[float, float]] = []
    edges = _require_attr(raw_obj, "edges", owner=type(raw_obj).__name__)
    assert isinstance(edges, list), f"Object edges must be list (actual={type(edges).__name__})"
    for edge in edges[:limit]:
        candidates = [
            _require_attr(edge, "midpoint", owner=type(edge).__name__),
            _require_attr(edge, "center", owner=type(edge).__name__),
            _require_attr(edge, "start", owner=type(edge).__name__),
            _require_attr(edge, "end", owner=type(edge).__name__),
        ]
        for candidate in candidates:
            try:
                samples.append(point_xy(candidate))
                break
            except (AssertionError, ValueError):
                continue
        else:
            vertices = _require_attr(edge, "vertices", owner=type(edge).__name__)
            assert isinstance(vertices, list), f"Edge vertices must be list (actual={type(vertices).__name__})"
            assert vertices, "Edge vertices must not be empty when midpoint/center/start/end are unusable"
            samples.append(point_xy(vertices[0]))
    return samples


def object_name(obj: Object3dRef) -> str:
    return _require_str_attr(_unwrap_object(obj), "name", owner=type(_unwrap_object(obj)).__name__)


def point_xy(value: object) -> tuple[float, float]:
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        x = value[0]
        y = value[1]
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            return (float(x), float(y))
    x_attr = _require_attr(value, "x", owner=type(value).__name__)
    y_attr = _require_attr(value, "y", owner=type(value).__name__)
    if isinstance(x_attr, (int, float)) and isinstance(y_attr, (int, float)):
        return (float(x_attr), float(y_attr))
    raise ValueError(f"Value of type {type(value).__name__} cannot be interpreted as XY point")


def release_desktop_session(
    hfss: HfssSession,
    *,
    close_projects: bool,
    close_on_exit: bool,
) -> None:
    desktop = _unwrap_desktop(hfss)
    aedt_pid = _require_int_attr(desktop, "aedt_process_id", owner="Desktop")
    try:
        result = desktop.release_desktop(close_projects=close_projects, close_on_exit=close_on_exit)
        raise_on_false(
            result,
            operation="release_desktop",
            context={
                "close_projects": close_projects,
                "close_on_exit": close_on_exit,
                "aedt_pid": aedt_pid,
            },
        )
    except Exception:
        subprocess.run(["kill", "-9", str(aedt_pid)], check=False)
        raise


def reset_aedt_versions_cache(aedt_versions: AedtVersionsSession | AedtVersionsProxy) -> None:
    raw_versions = cast(AedtVersionsSession, _unwrap(aedt_versions))
    raw_versions._list_installed_ansysem = None
    raw_versions._installed_versions = None
    raw_versions._stable_versions = None
    raw_versions._current_version = None
    raw_versions._current_student_version = None
    raw_versions._latest_version = None


def save_project(hfss: HfssSession, *, path: str) -> None:
    raw_hfss = cast(HfssSession, _unwrap(hfss))
    raise_on_false(
        raw_hfss.save_project(path),
        operation="save_project",
        context={"path": path},
    )


def set_object_model_state(modeler: ModelerSession, obj: Object3dRef, *, model: bool) -> None:
    raw_modeler = _unwrap_modeler(modeler)
    raw_obj = _unwrap_object(obj)
    object_name_for_state = object_name(cast(Object3dRef, raw_obj))
    try:
        setattr(raw_obj, "model", model)
    except Exception:
        raise
    set_model_state = cast(Callable[[str, bool], object], _require_callable_attr(raw_modeler, "set_object_model_state", owner="Modeler"))
    try:
        set_model_state(object_name_for_state, model)
    except Exception:
        raise


def subtract(
    modeler: ModelerSession,
    *,
    blank_list: list[str],
    tool_list: list[str],
    keep_originals: bool,
    context: Mapping[str, object] = _EMPTY_CONTEXT,
) -> None:
    _validate_name_list(blank_list, field="blank_list")
    _validate_name_list(tool_list, field="tool_list")
    raw_modeler = _unwrap_modeler(modeler)
    raise_on_false(
        raw_modeler.subtract(blank_list=blank_list, tool_list=tool_list, keep_originals=keep_originals),
        operation="subtract",
        context=context,
    )


def thicken_sheet(modeler: ModelerSession, *, assignment: str, thickness: float) -> object:
    validate_aedt_name(assignment, field="assignment")
    raw_modeler = _unwrap_modeler(modeler)
    try:
        return raise_on_false(
            raw_modeler.thicken_sheet(assignment=assignment, thickness=thickness),
            operation="thicken_sheet",
            context={"assignment": assignment, "thickness": thickness},
        )
    except TypeError:
        raise


def unite(modeler: ModelerSession, *, targets: list[str], error_context: str) -> str:
    if not targets:
        raise ValueError(f"unite requires at least one target ({error_context})")
    _validate_name_list(targets, field="targets")
    if len(targets) == 1:
        return targets[0]
    raw_modeler = _unwrap_modeler(modeler)
    try:
        result = raw_modeler.unite(assignment=targets)
    except TypeError:
        raise
    normalized = raise_on_false(
        result,
        operation="unite",
        context={"error_context": error_context, "targets": list(targets)},
    )
    return _normalize_name_result(normalized)
