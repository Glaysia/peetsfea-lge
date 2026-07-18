from __future__ import annotations

import time
from typing import cast

import pytest

from peetsfea.aedt.protocols import HfssSession
from peetsfea.backend.pyaedt.ssw_ports import (
    _analyze_with_hard_abort,
    make_attached_hfss_factory,
)
from peetsfea.errors import PeetsfeaStageError


class _FakeAnalyzeHfss:
    """Minimal stand-in exposing only what the hard-abort watchdog touches."""

    def __init__(
        self,
        *,
        analyze_sleep_seconds: float = 0.0,
        analyze_returns: bool = True,
        fail_on_gpu: bool = False,
    ) -> None:
        self._analyze_sleep_seconds = analyze_sleep_seconds
        self._analyze_returns = analyze_returns
        self._fail_on_gpu = fail_on_gpu
        self.stop_calls = 0
        self.analyze_calls: list[tuple[int, int]] = []

    def analyze_setup(self, name: str, blocking: bool = True, cores: int = 0, gpus: int = 0) -> object:
        self.analyze_calls.append((cores, gpus))
        if self._analyze_sleep_seconds > 0.0:
            time.sleep(self._analyze_sleep_seconds)
        if self._fail_on_gpu and gpus > 0:
            return False
        return self._analyze_returns

    def stop_simulations(self, clean_stop: bool = True) -> object:
        self.stop_calls += 1
        return "stopped"


def test_hard_abort_completes_within_budget() -> None:
    raw = _FakeAnalyzeHfss()
    outcome, gpu_used = _analyze_with_hard_abort(
        hfss=cast(HfssSession, raw), setup_name="Setup1", hard_abort_seconds=10.0, cores=4, gpus=0
    )
    assert outcome["completed"] is True
    assert outcome["hard_aborted"] is False
    assert gpu_used is False
    assert raw.analyze_calls == [(4, 0)]
    assert raw.stop_calls == 0


def test_hard_abort_triggers_clean_stop_and_reports_abort() -> None:
    raw = _FakeAnalyzeHfss(analyze_sleep_seconds=5.0)
    outcome, _gpu_used = _analyze_with_hard_abort(
        hfss=cast(HfssSession, raw),
        setup_name="Setup1",
        hard_abort_seconds=0.2,
        cores=4,
        gpus=1,
        abort_grace_seconds=0.2,
    )
    assert outcome["hard_aborted"] is True
    assert outcome["completed"] is False
    assert raw.stop_calls == 1


def test_analyze_failure_raises_structured_solve_error() -> None:
    raw = _FakeAnalyzeHfss(analyze_returns=False)
    with pytest.raises(PeetsfeaStageError) as excinfo:
        _analyze_with_hard_abort(
            hfss=cast(HfssSession, raw), setup_name="Setup1", hard_abort_seconds=10.0, cores=4, gpus=0
        )
    assert excinfo.value.stage == "solve"
    assert excinfo.value.error_type == "analyze_failed"
    assert raw.stop_calls == 0


def test_gpu_failure_falls_back_to_cpu() -> None:
    raw = _FakeAnalyzeHfss(fail_on_gpu=True)
    outcome, gpu_used = _analyze_with_hard_abort(
        hfss=cast(HfssSession, raw), setup_name="Setup1", hard_abort_seconds=10.0, cores=4, gpus=1
    )
    assert outcome["completed"] is True
    assert gpu_used is False
    # first GPU attempt fails, then a CPU (gpus=0) attempt succeeds
    assert raw.analyze_calls == [(4, 1), (4, 0)]


def test_attach_factory_requires_a_target() -> None:
    with pytest.raises(PeetsfeaStageError) as excinfo:
        make_attached_hfss_factory(grpc_port=None, aedt_pid=None)
    assert excinfo.value.stage == "attach"
    assert excinfo.value.error_type == "missing_attach_target"


def test_attach_factory_rejects_invalid_port() -> None:
    with pytest.raises(PeetsfeaStageError) as excinfo:
        make_attached_hfss_factory(grpc_port=0)
    assert excinfo.value.error_type == "invalid_grpc_port"


def test_attach_factory_rejects_invalid_pid() -> None:
    with pytest.raises(PeetsfeaStageError) as excinfo:
        make_attached_hfss_factory(grpc_port=None, aedt_pid=-3)
    assert excinfo.value.error_type == "invalid_aedt_pid"


def test_attach_factory_raises_when_unreachable() -> None:
    # Build succeeds (validation only); attaching fails because nothing is listening / no such pid.
    factory = make_attached_hfss_factory(grpc_port=59997, aedt_pid=2_000_000_000)
    with pytest.raises(PeetsfeaStageError) as excinfo:
        factory("ssw_unreachable_design")
    assert excinfo.value.stage == "attach"
    assert excinfo.value.error_type == "aedt_unreachable"
