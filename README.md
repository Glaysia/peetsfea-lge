---
title: peetsfea
created: 2026-04-17 @ 09:09
updated: 2026-06-16 @ 00:00
tags:
  - governance
---

# peetsfea

peetsfea는 TOML 명세에서 SSW 코일 설계를 결정적으로 생성하고, headless HFSS(AEDT)로 setup/solve/report까지 잇는 Python 프로젝트입니다. `peetsfea-runner`가 의존하는 공개 API를 제공합니다(아래 *runner 통합* 참고).

영문 문서는 [README.en.md](README.en.md)를 참고하세요.

## 현재 계약
- LGE 릴리스 라벨: `0.5.0-lge.0` (`project.version = "0.5.0+lge.0"`는 동일 라벨의 PEP 440 호환 표기)
- 설계 공간 SSOT: 패키지 데이터 `src/peetsfea/data/0.3.x_sweep.toml` (`DEFAULT_REFERENCE_TOML_PATH`). 정규 fixed 점은 `src/peetsfea/data/0.3.x_fixed.toml` (`DEFAULT_SOURCE_TOML_PATH`). 둘 다 wheel에 동봉되어 설치 환경에서도 해석됩니다.
- TOML surface: `[design]` · `[backend]` · `[fixed_dimensions]` · `[[modeled_objects]]`(tx/rx/under coil) · `[ferrite]` · `[constraints]`.
- 제약: TX/RX SSW coil은 enabled 고정이며 `gcd(turn_n_int, twist_factor) == 1`, RX `turn_n_int > 1`, TX/RX `void_profile`은 scaled void profile `1`로 고정.
- 설계 자유변수는 18개입니다. 0.3.8.x부터 RX `is_ssw_enabled`, `no_ssw_qturn_start_int`, `no_ssw_qturn_n_int`는 고정되어 자유변수에 포함되지 않습니다.
- `tx_under_coil`은 TX main coil과 별도인 두 번째 TX coil이며, `tx_region_max`의 global X-min 면 바깥에 붙는 YZ 평면 normal spiral입니다([GOAL.md](GOAL.md)).
- MULL ferrite 위치는 TX Z축 `ferrite.tx_mull_position_ratio`와 RX X축 `ferrite.rx_mull_position_ratio`로 따로 제어합니다. TX MULL ferrite sheet count는 0.3.8.x 기준 `1..5` 범위의 단일 자유변수입니다.
- EM surface: Tx 포트 1개(`1_T1`), Rx 포트 1개(`2_T1`), copper pad mesh, radiation boundary, `Setup1`, `Sweep`, report 테이블.
- 기본 실행과 AEDT/PyAEDT 변경 검증은 headless이며 PyAEDT `False` return은 즉시 raise합니다. AEDT/PyAEDT 코드를 수정한 agent는 실제 headless AEDT 검증을 직접 실행해야 하며, 실행 불가 시 완료로 보고하지 않습니다.

## 실행
테스트는 `run/`에서 실행합니다.

프로젝트 환경은 Miniconda와 분리된 `uv` 프로젝트 `.venv`에서 시스템 CPython
`3.14.4` 및 PyAEDT `1.3.0`을 사용합니다. 배포 버전 `0.5.0+lge.0`은 요청한
릴리스 라벨 `0.5.0-lge.0`의 PEP 440 호환 표기이며,
`peetsfea.__version__`은 원래 라벨을 그대로 반환합니다.

```bash
uv sync --extra all
cd run
../.venv/bin/pytest -q ../tests -m "not pyaedt_integration"   # 순수 Python
../.venv/bin/pyright ../src ../entry ../tests
```

LGE_EVDD의 현재 `0.2.0` CAD 범위는 FR4, 2층 일차 플라나 권선, 센터탭용 이차 반권선
2개입니다. 저장소 루트에서 다음 명령은
`src/peetsfea/data/lgevdd_0.2.0_fixed.toml`의 고정 range를 읽어
`run/lgevdd_pcb/lgevdd_pcb.step`을 생성합니다. STEP에는 connector hole이
있고 중앙 `146 × 7 mm` 영역이 페라이트 중심 다리용으로 관통된 FR4와, 위·아래층
및 내부 connector가 fuse된 일차 구리 권선이 별도 body로 들어갑니다. 중앙 구멍은
별도 숨은 치수가 아니라 일차 권선의 `center_keepout_width_x_mm` 및
`center_keepout_height_y_mm`를 그대로 사용합니다.

```bash
uv run dev --ocp-port 3940
```

이차측만 확인할 때는 다음 명령을 사용합니다.

```bash
uv run dev --ocp-port 3940 --type=secondary
```

이 명령은 FR4와 일차측을 제외하고 `secondary_planar_coil_1`,
`secondary_planar_coil_2`만 포함한
`run/lgevdd_pcb/lgevdd_secondary.step`을 생성해 OCP에 표시합니다. 두 body는
레거시처럼 각각 두 직사각형 루프를 직사각형 Z 브리지로 연결하며 서로 fuse하지
않습니다. 센터탭 전기 접속도 CAD에는 만들지 않고 외부 회로의 책임으로 남깁니다.

FR4, 일차측, 이차측을 한 번에 확인할 때는 다음 명령을 사용합니다.

```bash
uv run dev --ocp-port 3940 --type=both
```

이 명령은 네 body를 `run/lgevdd_pcb/lgevdd_both.step`에 저장합니다. 원래 장치는
PCB planar transformer지만 레거시 CAD는 `Tx_preg/Rx_preg`를 간격으로만 사용하고
FR4 solid를 생성하지 않았습니다. 현재 초록색 `fr4_board`는 일차측 두 구리층
사이의 중앙 dielectric 한 장이며 전체 다층 PCB laminate를 재현한 것은 아닙니다.

생성 직후 STEP을 다시 읽어 body 이름·solid 수·bbox·부피를 검증하고, OCP에는
FR4를 반투명 초록색, 일차 권선을 구리색으로 표시합니다. OCP CAD Viewer는 명령에
넘긴 포트와 같은 포트에서 먼저 실행 중이어야 합니다. 다른 입력이나 출력 위치는
각각 `--toml`, `--output-dir`로 지정합니다.

현재 고정점은 FR4 `240 × 40 × 0.02 mm`, 총 14턴(위 7턴·아래 7턴),
중앙 FR4 관통구멍 `146 × 7 mm`, 트레이스 `1.5 × 0.175 mm`입니다. 모든 수치는 TOML에
`[정수여부, 시작, 끝, 갯수]` 형식으로 명시되어 있습니다. 생성기는 2층을
고정하고 2 이상의 임의 총 턴수를 지원하며, 홀수 턴의 추가 한 턴은 위층에 둡니다.
이차측 fixed point는 반권선당 2턴, 트레이스 `7.7 × 0.105 mm`, X/Y 내부 여유
`2.8/3.3 mm`, preg `0.06 mm`입니다. 이차측 생성기는 1턴 이상의 턴수를 지원하고
홀수 턴의 추가 턴은 첫 레이어에 둡니다.
제약식은 `path/value/func/op` 구조를 whitelist 기반으로 평가하고 임의 문자열
코드를 실행하지 않습니다. 이 vertical slice의 영구 산출물은 STEP 하나이며
별도 ledger는 생성하지 않습니다.

설계 공간 안에서 seed 범위로 랜덤 SSW STEP 파일을 생성하고(`entry/sample.py`), 그중 한 seed를 OCP로 봅니다(`entry/view.py`).

```bash
cd run
# 생성만: seed 0..99를 워커 10개로 병렬 생성
../.venv/bin/python ../entry/sample.py --seed-start 0 --seed-end 99 --jobs 10
# 생성 후 seed 3을 OCP에 표시
../.venv/bin/python ../entry/view.py --seed-start 0 --seed-end 9 --view-seed 3
# 이미 생성된 결과를 재생성 없이 보기만
../.venv/bin/python ../entry/view.py --view-seed 3 --no-sample
# 정규 fixed 점(data/0.3.x_fixed.toml)을 생성·표시
../.venv/bin/python ../entry/view.py --fixed
```

- 생성물은 gitignored `run/ssw_step_samples/seed_<NNNNN>/`(또는 `--fixed`는 `fixed/`)에 들어갑니다.
- `--jobs N`은 seed별 생성을 N개 프로세스로 병렬 처리합니다(각 seed는 독립 디렉토리라 안전하며 결과는 결정적). 실패 seed는 예외 메시지에 seed 번호가 찍힙니다.
- `view.py`는 STEP re-import가 아니라 sampled spec으로 재구성한 `cq.Assembly`를 표시하므로 역할별 색상·투명도가 유지됩니다.
- `--debug`는 각 스크립트 상단 `DEBUG_*` 상수로 인자를 제어합니다(VS Code launch.json은 `view.py --debug`를 실행).

Headless AEDT setup/solve/report 경로는 패키지 공개 API(`peetsfea.run_ssw_random_sample_reports_from_toml_text`)와 `tests/backend_em`의 headless AEDT 통합 테스트로 실행합니다.

## 산출물
`entry/sample.py`의 기본 출력 위치는 gitignored `run/ssw_step_samples/seed_<NNNNN>/`이며 seed마다 다음을 생성합니다.

- `<design_id>.toml` (sampled fixed point)
- `ssw_scene.step`
- `ssw_step_ledger.json`
- `coil_making_token.toml`

SSW headless AEDT 솔브 산출물(`<design_id>.aedt`, report CSV 등)은 공개 API 결과의 `output_dir` 아래에 생성됩니다.

## runner 통합 (0.3.8.0)
peetsfea-runner가 의존하는 공개 표면입니다. peetsfea는 ansysedt를 직접 기동/종료하거나 라이선스를 관리하지 않습니다. 전체 계약은 [docs/runner-integration.md](docs/runner-integration.md)를 보세요.

- `peetsfea.__version__ == "0.3.8.0"`, 패키지에 `py.typed` 동봉.
- `peetsfea.validate_sweep_toml_text(text)` — sweep의 모든 swept range가 기준 sweep design space(상하한 + 정수/실수 플래그 + count>0) 이내인지 검사, 벗어나면 `PeetsfeaStageError`.
- `peetsfea.sample_fixed_candidates_from_toml_text(text, count, seed) -> list[str]` — 결정론적, scratch는 `TMPDIR` 준수.
- `peetsfea.run_ssw_random_sample_reports_from_toml_text(..., grpc_port, aedt_pid=None)` — warm ansysedt에 attach(자체 기동 금지), full solve 후 프로젝트만 닫고 AEDT는 살린 채 구조화 결과 반환. solve는 60분 hard-abort watchdog 포함. `semi_dry` 경로는 제거되었습니다.
- **자동 GPU 가속(0.3.5):** solve 직전 `nvidia-smi`로 GPU 감지 → 가능하면 AEDT analyze에 GPU 활성(고정 `cores=4`), 실패 시 조용히 CPU 폴백. API 변경 없음. `solve_telemetry`에 `gpu_used`·`gpu_device_name`·`solver_cores` 기록.
- 모든 실패는 `peetsfea.PeetsfeaStageError`(`stage`/`error_type`/`message`, `RuntimeError` 하위).

## 규칙
- `python -O`는 지원하지 않습니다. assertion은 runtime contract의 일부입니다.
- `src/` runtime state는 nullable/fallback 기반으로 다루지 않습니다([CODE_COMMANDMENTS.md](CODE_COMMANDMENTS.md)).
- GUI AEDT 확인은 보조 진단일 뿐이며, headless AEDT 검증을 대체하지 않습니다.

## 문서
- 목표: [GOAL.md](GOAL.md)
- runner 통합 계약: [docs/runner-integration.md](docs/runner-integration.md)
- Palace 세컨드 백엔드 로드맵: [docs/palace-second-backend-roadmap.md](docs/palace-second-backend-roadmap.md)
- 작업 규칙: [AGENTS.md](AGENTS.md) · 코드 계명: [CODE_COMMANDMENTS.md](CODE_COMMANDMENTS.md)

## 호환성 정책
장기 backward compatibility는 보장하지 않습니다. Minor release도 spec path, artifact contract, runtime entrypoint를 변경할 수 있습니다.
