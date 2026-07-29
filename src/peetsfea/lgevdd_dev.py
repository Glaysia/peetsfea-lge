from __future__ import annotations

import argparse
from pathlib import Path
from typing import Literal, cast

from ocp_vscode import Camera, Collapse, show

from peetsfea.lgevdd_spec import DEFAULT_SOURCE_TOML_PATH
from peetsfea.lgevdd_step import (
    DEFAULT_BOTH_STEP_NAME,
    DEFAULT_SECONDARY_STEP_NAME,
    DEFAULT_STEP_NAME,
    LgeEvddBothArtifacts,
    LgeEvddPcbArtifacts,
    LgeEvddSecondaryArtifacts,
    export_lgevdd_both_step,
    export_lgevdd_pcb_step,
    export_lgevdd_secondary_step,
)

DEFAULT_OUTPUT_DIR = Path("run") / "lgevdd_pcb"
DEFAULT_OCP_PORT = 3939
FR4_OCP_COLOR = (39, 110, 54)
COPPER_OCP_COLOR = (184, 115, 51)
DevViewType = Literal["both", "primary", "secondary"]


def show_lgevdd_pcb_in_ocp(*, artifacts: LgeEvddPcbArtifacts, ocp_port: int) -> None:
    if not 1 <= ocp_port <= 65535:
        raise ValueError(f"OCP port must be in 1..65535 (actual={ocp_port})")
    try:
        show(
            artifacts.fr4_shape,
            artifacts.primary_shape,
            names=[
                artifacts.spec.fr4.object_id,
                artifacts.spec.primary.object_id,
            ],
            colors=[FR4_OCP_COLOR, COPPER_OCP_COLOR],
            alphas=[0.65, 1.0],
            axes=True,
            axes0=True,
            grid=True,
            collapse=Collapse.ROOT,
            reset_camera=Camera.RESET,
            port=ocp_port,
        )
    except Exception as exc:
        raise RuntimeError(
            f"failed to show LGE_EVDD PCB in OCP on port {ocp_port}; "
            "start the OCP CAD Viewer on that port and retry"
        ) from exc


def show_lgevdd_secondary_in_ocp(
    *,
    artifacts: LgeEvddSecondaryArtifacts,
    ocp_port: int,
) -> None:
    if not 1 <= ocp_port <= 65535:
        raise ValueError(f"OCP port must be in 1..65535 (actual={ocp_port})")
    try:
        show(
            *artifacts.secondary_shapes,
            names=list(artifacts.spec.secondary.body_ids),
            colors=[COPPER_OCP_COLOR, COPPER_OCP_COLOR],
            alphas=[1.0, 1.0],
            axes=True,
            axes0=True,
            grid=True,
            collapse=Collapse.ROOT,
            reset_camera=Camera.RESET,
            port=ocp_port,
        )
    except Exception as exc:
        raise RuntimeError(
            f"failed to show LGE_EVDD secondary in OCP on port {ocp_port}; "
            "start the OCP CAD Viewer on that port and retry"
        ) from exc


def show_lgevdd_both_in_ocp(
    *,
    artifacts: LgeEvddBothArtifacts,
    ocp_port: int,
) -> None:
    if not 1 <= ocp_port <= 65535:
        raise ValueError(f"OCP port must be in 1..65535 (actual={ocp_port})")
    try:
        show(
            artifacts.fr4_shape,
            artifacts.primary_shape,
            *artifacts.secondary_shapes,
            names=[
                artifacts.spec.fr4.object_id,
                artifacts.spec.primary.object_id,
                *artifacts.spec.secondary.body_ids,
            ],
            colors=[
                FR4_OCP_COLOR,
                COPPER_OCP_COLOR,
                COPPER_OCP_COLOR,
                COPPER_OCP_COLOR,
            ],
            alphas=[0.65, 1.0, 1.0, 1.0],
            axes=True,
            axes0=True,
            grid=True,
            collapse=Collapse.ROOT,
            reset_camera=Camera.RESET,
            port=ocp_port,
        )
    except Exception as exc:
        raise RuntimeError(
            f"failed to show LGE_EVDD both scene in OCP on port {ocp_port}; "
            "start the OCP CAD Viewer on that port and retry"
        ) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export a selected LGE_EVDD planar winding view to STEP and OCP."
    )
    parser.add_argument(
        "--type",
        dest="view_type",
        choices=("both", "primary", "secondary"),
        default="primary",
        help=(
            "primary shows FR4/primary; secondary shows only Rx1/Rx2; "
            "both shows FR4 and all three windings"
        ),
    )
    parser.add_argument(
        "--toml",
        type=Path,
        default=DEFAULT_SOURCE_TOML_PATH,
        help="LGE_EVDD fixed TOML source",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="directory receiving the selected LGE_EVDD STEP file",
    )
    parser.add_argument(
        "--ocp-port",
        type=int,
        default=DEFAULT_OCP_PORT,
        help="OCP CAD Viewer port",
    )
    return parser


def main() -> None:
    raw_args = vars(_parser().parse_args())
    for key in ("view_type", "toml", "output_dir", "ocp_port"):
        assert key in raw_args

    raw_view_type = raw_args["view_type"]
    assert isinstance(raw_view_type, str)
    if raw_view_type not in ("both", "primary", "secondary"):
        raise ValueError(
            f"view_type must be 'both', 'primary', or 'secondary' "
            f"(actual={raw_view_type!r})"
        )
    view_type = cast(DevViewType, raw_view_type)
    raw_toml_path = raw_args["toml"]
    assert isinstance(raw_toml_path, Path)
    toml_path = raw_toml_path.resolve()
    raw_output_dir = raw_args["output_dir"]
    assert isinstance(raw_output_dir, Path)
    output_dir = raw_output_dir.resolve()
    raw_ocp_port = raw_args["ocp_port"]
    assert isinstance(raw_ocp_port, int)
    ocp_port = raw_ocp_port

    if view_type == "primary":
        primary_artifacts = export_lgevdd_pcb_step(
            source_toml_path=toml_path,
            step_path=output_dir / DEFAULT_STEP_NAME,
        )
        print(
            "LGE_EVDD PCB STEP exported: "
            f"{primary_artifacts.step_path} "
            f"(FR4={primary_artifacts.spec.fr4.size_x_mm:g} x "
            f"{primary_artifacts.spec.fr4.size_y_mm:g} x "
            f"{primary_artifacts.spec.fr4.thickness_mm:g} "
            f"{primary_artifacts.spec.units}, "
            f"primary_turns={primary_artifacts.spec.primary.turns}, "
            f"top={primary_artifacts.primary_geometry.top_turns}, "
            f"bottom={primary_artifacts.primary_geometry.bottom_turns})"
        )
        show_lgevdd_pcb_in_ocp(
            artifacts=primary_artifacts,
            ocp_port=ocp_port,
        )
        print(f"LGE_EVDD PCB sent to OCP CAD Viewer: port={ocp_port}")
    elif view_type == "secondary":
        secondary_artifacts = export_lgevdd_secondary_step(
            source_toml_path=toml_path,
            step_path=output_dir / DEFAULT_SECONDARY_STEP_NAME,
        )
        print(
            "LGE_EVDD secondary STEP exported: "
            f"{secondary_artifacts.step_path} "
            f"(bodies={secondary_artifacts.spec.secondary.body_count}, "
            f"turns_per_body={secondary_artifacts.spec.secondary.turns}, "
            f"first_layer={secondary_artifacts.secondary_geometry.first_layer_turns}, "
            f"second_layer={secondary_artifacts.secondary_geometry.second_layer_turns})"
        )
        show_lgevdd_secondary_in_ocp(
            artifacts=secondary_artifacts,
            ocp_port=ocp_port,
        )
        print(f"LGE_EVDD secondary sent to OCP CAD Viewer: port={ocp_port}")
    else:
        both_artifacts = export_lgevdd_both_step(
            source_toml_path=toml_path,
            step_path=output_dir / DEFAULT_BOTH_STEP_NAME,
        )
        print(
            "LGE_EVDD both STEP exported: "
            f"{both_artifacts.step_path} "
            f"(solids=4, primary_turns={both_artifacts.spec.primary.turns}, "
            f"secondary_bodies={both_artifacts.spec.secondary.body_count}, "
            f"secondary_turns_per_body={both_artifacts.spec.secondary.turns})"
        )
        show_lgevdd_both_in_ocp(
            artifacts=both_artifacts,
            ocp_port=ocp_port,
        )
        print(f"LGE_EVDD both scene sent to OCP CAD Viewer: port={ocp_port}")


__all__ = [
    "COPPER_OCP_COLOR",
    "DEFAULT_OCP_PORT",
    "DEFAULT_OUTPUT_DIR",
    "DevViewType",
    "FR4_OCP_COLOR",
    "main",
    "show_lgevdd_both_in_ocp",
    "show_lgevdd_pcb_in_ocp",
    "show_lgevdd_secondary_in_ocp",
]
