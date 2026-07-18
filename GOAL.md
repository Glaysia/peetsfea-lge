# Goal: 0.3.8.x ferrite range and full-solve analysis hardening

이번 작업의 목표는 0.3.8.x SSW 정규 경로에서 두 변경을 한 번에 판단 가능한 상태로 닫는 것이다.

1. `ferrite.tx_mull_sheet_count`를 최대 5장까지 허용한다.
2. `semi_dry` solve 경로를 제거하고, 4-core full solve 해석 설정을 강화한다.

## 변경 계약

- TX MULL ferrite sheet count의 reference sweep은 `[true, 1, 5, 5]`다.
- 이 변경은 자유변수 개수를 늘리지 않는다. 기존 `ferrite.tx_mull_sheet_count` 1개 축의 후보 범위만 `1..5`로 넓힌다.
- canonical fixed point의 sheet count는 현재 값 2를 유지한다.
- runner-facing solve mode는 `full`만 허용한다. `semi_dry`는 public/random-sample report 경로에서 제거한다.
- full solve 해석 설정은 다음 값을 사용한다.
  - `MaxDeltaS = 0.003`
  - `MaximumPasses = 16`
  - `MinimumPasses = 13`
  - `MinimumConvergedPasses = 9`
  - `PercentRefinement = 30`
- AEDT payload 안의 `MaxPass`, `MinPass`, `MinConvPass` alias 값도 위 pass 값과 일치해야 한다.

## 후속 측정 계약

- solve 시간 비교는 이번 규약 커밋 이후 후속 작업으로 실행한다.
- 비교 기준은 0.3.8.0 baseline commit `eb7f18a`와 강화 설정 커밋이다.
- 두 측정은 같은 fixed TOML, 같은 seed, 같은 headless HFSS full solve 경로를 사용한다.
- 두 측정 모두 solver resource를 `cores=4`, `gpus=0`으로 고정한다.
- 가능하면 baseline과 변경 버전을 동시에 실행해 같은 시스템 부하에서 solve 시간을 비교한다.
- 비교 결과는 `docs/ssw-0.3.8.0-patch-plan.html`에 기록한다.
- 기록해야 할 최소 항목:
  - baseline 설정값
  - 변경 설정값
  - baseline elapsed/analyze time
  - 변경 elapsed/analyze time
  - 절대 증가 시간
  - 증가율
  - completed/hard-aborted 여부

## Acceptance Criteria

- `src/peetsfea/data/0.3.x_sweep.toml`에서 `ferrite.tx_mull_sheet_count`가 `[true, 1, 5, 5]`다.
- `build_ssw_body_boxes(load_ssw_fixed_spec(...))`가 TX ferrite 5장 fixed point를 생성할 수 있다.
- `semi_dry` mode는 public random-sample report API에서 거부된다.
- default full solve pass count는 `16/13/9`이고 `MaxDeltaS=0.003`, `PercentRefinement=30`이다.
- pure Python tests, pyright, HTML parser, diff check가 통과한다.
- AEDT/PyAEDT-affecting 변경이므로 real headless AEDT validation을 실행한다.
- solve 시간 비교는 후속 작업으로 남기며, 이번 커밋 완료 기준에는 포함하지 않는다.
