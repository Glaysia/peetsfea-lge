from __future__ import annotations

from pathlib import Path

import pytest

import peetsfea.minimal_step as module_under_test
from peetsfea.minimal_spec import SCHEMA_ID, SPEC_VERSION
from peetsfea.minimal_step import export_minimal_step_artifacts, load_minimal_step_ledger


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

[[non_model_objects]]
id = "tv"
kind = "tv"
primitive = "box"
present = true
non_model = true
material = "vacuum"
plane = "YZ"
origin_xyz = [0.0, -921.0, 170.0]
size_xyz = [9.0, 1842.0, 1055.0]
""",
        encoding="utf-8",
    )
    return path


def test_export_minimal_step_artifacts_writes_fixed_body_contract(tmp_path: Path) -> None:
    artifacts = export_minimal_step_artifacts(source_toml_path=_write_spec(tmp_path), output_dir=tmp_path, seed=0)

    ledger = load_minimal_step_ledger(Path(artifacts["ledger_path"]))
    assert Path(artifacts["scene_step_path"]).is_file()
    assert ledger["body_names"] == [
        "air_context",
        "tv",
        "tx_signal_pad",
        "tx_reference_pad",
        "tx_port_sheet",
        "rx_signal_pad",
        "rx_reference_pad",
        "rx_port_sheet",
    ]
    assert ledger["non_model_body_names"] == ["air_context", "tv"]
    assert ledger["bodies"][1]["object_id"] == "tv"
    assert ledger["bodies"][1]["role"] == "non_model"
    assert ledger["bodies"][1]["canonical_coordinates"]["outer_bounds_min_xyz"] == [0.0, -921.0, 170.0]
    assert ledger["bodies"][1]["canonical_coordinates"]["outer_bounds_size_xyz"] == [9.0, 1842.0, 1055.0]
    assert ledger["copper_body_names"] == [
        "tx_signal_pad",
        "tx_reference_pad",
        "rx_signal_pad",
        "rx_reference_pad",
    ]
    assert ledger["port_sheet_names"] == ["tx_port_sheet", "rx_port_sheet"]
    assert [cell["role"] for cell in ledger["port_cells"]] == ["tx", "rx"]


def test_export_minimal_step_artifacts_raises_when_step_export_returns_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _false_export_step(*args: object, **kwargs: object) -> bool:
        del args, kwargs
        return False

    monkeypatch.setattr(module_under_test.bd, "export_step", _false_export_step)

    with pytest.raises(RuntimeError, match="build123d export_step returned False for minimal STEP"):
        export_minimal_step_artifacts(source_toml_path=_write_spec(tmp_path), output_dir=tmp_path, seed=0)
