from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

__all__ = [
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


class Object3dRef(Protocol):
    name: str


class BoundaryModuleSession(Protocol):
    def AssignLumpedPort(self, props: list[object]) -> object: ...

    def GetBoundaries(self) -> list[object] | tuple[object, ...]: ...


class DesktopSession(Protocol):
    aedt_process_id: int

    def GetMessages(self, project_name: str, design_name: str, level: int) -> list[str] | tuple[str, ...]: ...

    def release_desktop(self, close_projects: bool, close_on_exit: bool) -> object: ...


class MaterialsSession(Protocol):
    material_keys: Mapping[str, object]

    def exists_material(self, name: str) -> object: ...

    def add_material(self, name: str) -> object: ...


class AnalysisSetupModuleSession(Protocol):
    def InsertSetup(self, setup_type: str, props: list[object]) -> object: ...

    def InsertFrequencySweep(self, setup_name: str, props: list[object]) -> object: ...


class MeshModuleSession(Protocol):
    def AssignLengthOp(self, props: list[object]) -> object: ...


class ReportSetupModuleSession(Protocol):
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
    ) -> object: ...

    def ExportToFile(self, report_name: str, export_path: str) -> object: ...

    def GetAllReportNames(self) -> list[str] | tuple[str, ...]: ...


class SolutionsModuleSession(Protocol):
    def EditSources(self, payload: list[object]) -> object: ...

@runtime_checkable
class DesignSession(Protocol):
    def GetModule(self, name: str) -> object: ...

    def ValidateDesign(self) -> object: ...


class TraceProviderSession(Protocol):
    def get_traces_for_plot(
        self,
        get_self_terms: bool,
        get_mutual_terms: bool,
        first_element_filter: str,
        second_element_filter: str,
        category: str,
        differential_pairs: Sequence[object],
    ) -> list[str]: ...


class ModelerSession(Protocol):
    @property
    def object_names(self) -> Sequence[str]: ...

    def create_box(self, **kwargs: object) -> object: ...

    def create_coordinate_system(
        self,
        origin: list[float] | None = None,
        reference_cs: str = "Global",
        name: str | None = None,
        mode: str = "axis",
        view: str = "iso",
        x_pointing: list[float] | None = None,
        y_pointing: list[float] | None = None,
        psi: int = 0,
        theta: int = 0,
        phi: int = 0,
        u: list[float] | None = None,
    ) -> object: ...

    def create_cylinder(self, **kwargs: object) -> object: ...

    def create_group(self, *, objects: list[str], group_name: str) -> object: ...

    def create_polyline(self, **kwargs: object) -> object: ...

    def create_region(self, pad_value: int, pad_type: str, name: str) -> object: ...

    def cover_lines(self, assignment: str) -> object: ...

    def get_object_from_name(self, assignment: str) -> object: ...

    def get_edge_vertices(self, assignment: int) -> list[int]: ...

    def get_face_area(self, assignment: int) -> float: ...

    def get_face_center(self, assignment: int) -> list[float]: ...

    def get_face_edges(self, assignment: int) -> list[int]: ...

    def get_face_vertices(self, assignment: int) -> list[int]: ...

    def get_object_edges(self, assignment: str) -> list[int]: ...

    def get_object_faces(self, assignment: str) -> list[int]: ...

    def get_vertex_position(self, assignment: int) -> list[float]: ...

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
    ) -> bool: ...

    def move(self, assignment: object, vector: list[float]) -> object: ...

    def rotate(self, assignment: object, axis: str, angle: float = 90.0, units: str = "deg") -> object: ...

    def set_working_coordinate_system(self, name: str) -> object: ...

    def set_object_model_state(self, name: str, model: bool) -> object: ...

    def subtract(self, *, blank_list: list[str], tool_list: list[str], keep_originals: bool) -> object: ...

    def thicken_sheet(self, assignment: str, thickness: float) -> object: ...

    def unite(self, assignment: list[str]) -> object: ...


class HfssSession(TraceProviderSession, Protocol):
    @property
    def modeler(self) -> ModelerSession: ...

    @property
    def desktop_class(self) -> DesktopSession: ...

    @property
    def odesign(self) -> object: ...

    @property
    def materials(self) -> object: ...

    @property
    def oboundary(self) -> object: ...

    @property
    def excitation_names(self) -> Sequence[str]: ...

    @property
    def setup_names(self) -> Sequence[str]: ...

    def __setitem__(self, key: str, value: str) -> None: ...

    def assign_material(self, assignment: str | list[str], material: str) -> object: ...

    def assign_finite_conductivity(
        self,
        assignment: str | list[object],
        *,
        material: str,
        use_thickness: bool,
        thickness: str,
        is_two_side: bool,
        name: str,
    ) -> object: ...

    def assign_radiation_boundary_to_faces(self, assignment: object, name: str) -> object: ...

    def create_output_variable(self, variable: str, expression: str, solution: str) -> object: ...

    def change_validation_settings(
        self,
        entity_check_level: str = "Strict",
        ignore_unclassified: bool = False,
        skip_intersections: bool = False,
    ) -> object: ...

    def delete_setup(self, name: str) -> object: ...

    def save_project(self, path: str) -> object: ...

    def close_project(self, name: str, save: bool = True) -> object: ...

    @property
    def project_name(self) -> str: ...

    def analyze_setup(self, name: str, blocking: bool = True, cores: int = 0, gpus: int = 0) -> object: ...

    def stop_simulations(self, clean_stop: bool = True) -> object: ...


class AedtVersionsSession(Protocol):
    _list_installed_ansysem: object
    _installed_versions: object
    _stable_versions: object
    _current_version: object
    _current_student_version: object
    _latest_version: object

    def get_version_env_variable(self, version: str) -> str: ...
