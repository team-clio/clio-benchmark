# Clio Benchmark 구현 계획

## 1. 문서 정보

상태: 초안 · 독자: Benchmark/Agent/Server 개발자 · 수정: 2026-09-14 · 리뷰 필요 · 범위: 구현의 단계와 완료 기준

## 2. 구현 목표

여러 벤치마크 저장소를 동일한 Clio 환경에서 실행하고, 사례별 처리 기록과 평가 결과를 재현 가능한 형태로 남기는 CLI 도구를 만든다.

첫 번째 MVP는 다음 한 가지 흐름의 완성을 목표로 한다.

> Clio 환경 준비 → 단일 테스트 저장소 등록 → 단일 버그 리포트 처리 → 종료 대기 → 원시 기록 저장

MVP에서는 정교한 점수, 병렬 실행, 대시보드를 다루지 않는다. 먼저 실제 시스템을 통과하는 최소 수직 흐름과 서비스 간 계약을 검증한다.

## 3. 작업 흐름

| 작업 영역 | 책임 |
|---|---|
| Benchmark Core | CLI, 설정, 실행 상태와 결과 디렉터리 관리 |
| Runtime | Agent·Server clone, Docker 실행, health check와 종료 |
| Server 연동 | 프로젝트·저장소·버그 생성과 작업 상태 조회 |
| Agent 연동 | trace, 모델, 토큰 및 도구 사용 기록 조회 |
| Test Suite | `cases.json`, `bugs.json`, 테스트 저장소와 Ground Truth 격리 관리 |
| Evaluation | 결정적 평가, LLM judge와 결과 집계 |

Clio-Server와 Clio-Agent에 필요한 API 변경은 각 저장소에서 구현하되, 요청·응답 계약은 Clio Benchmark 문서에서 기준을 관리한다.

## 4. 단계별 계획

### 단계 0. 계약과 기준 확정

목표: 구현을 시작하기 위해 필요한 최소 경계를 합의한다.

- 확정한 Python CLI 패키지 골격을 구성한다.
- Server·Agent의 health, 상태 조회, 기록 수집 가능 여부를 조사한다.
- 기존 API를 우선 사용하고 부족한 API와 `BENCHMARK_MODE` 동작을 정의한다.
- 테스트 저장소가 없어도 가능한 계약·통합 테스트 범위를 정한다.

완료 기준: MVP 흐름에 필요한 API와 입력·출력 소유자가 정해지고 미지원 기능이 식별된다.

### 단계 1. 프로젝트 기반 구성

목표: 이후 기능이 같은 규칙으로 추가될 수 있는 실행 골격을 만든다.

- CLI 진입점과 `setup`, `run`, `status`, `down` 명령 골격을 만든다.
- 설정 로드·검증과 공통 오류 모델을 만든다.
- `.benchmark/` 작업 공간과 실행 manifest 생성을 구현한다.
- 단위 테스트, 정적 검사와 CI의 최소 기준을 구성한다.

완료 기준: 빈 설정과 예제 설정에 대한 CLI 동작 및 검증 테스트가 통과한다.

### 단계 2. 로컬 환경 자동화

목표: 한 명령으로 벤치마크용 Clio 환경을 준비하고 정리한다.

- Agent·Server 저장소 clone 및 revision 고정을 구현한다.
- Docker 이미지 빌드와 전용 network·container 관리를 구현한다.
- `BENCHMARK_MODE=true` 전달과 health check를 구현한다.
- 반복 setup과 down이 안전하게 동작하도록 한다.

완료 기준: 깨끗한 로컬 환경에서 `setup` 후 두 서비스가 준비되고 `down`으로 정리된다.

### 단계 3. 단일 사례 수직 구현

목표: 실제 리포트 하나를 Clio 처리 경로 끝까지 통과시킨다.

- 테스트 저장소 clone과 `cases.json`/`bugs.json` 검증을 구현한다.
- Server 프로젝트 생성, 저장소 등록과 동기화 대기를 구현한다.
- 리포트 생성과 종료 상태 polling을 구현한다.
- Server·Agent 원시 기록을 실행 디렉터리에 저장한다.

완료 기준: 한 명령으로 단일 사례가 실행되고 입력, 상태 변화, 최종 결과와 환경 정보가 보존된다. 이 시점을 MVP 완료로 본다.

### 단계 4. 다중 사례와 복구 가능성

목표: 여러 리포트와 저장소를 연속 실행해도 사례 간 결과가 섞이지 않게 한다.

- 다중 리포트와 다중 suite 순차 실행을 구현한다.
- `run_id`, `case_id`, `correlation_id` 추적을 검증한다.
- timeout, 제한적 retry, 부분 실패와 재실행 정책을 구현한다.
- 사례 사이의 데이터 초기화 또는 격리를 적용한다.

완료 기준: 일부 사례가 실패해도 나머지가 실행되고 각 결과와 실패 원인을 독립적으로 확인할 수 있다.

### 단계 5. 평가와 보고

목표: 수집한 기록을 반복 가능한 점수와 비교 자료로 변환한다.

- Ground Truth 계약과 결정적 평가기를 먼저 구현한다.
- 의미 평가가 필요한 항목에 한해 LLM judge를 추가한다.
- 품질 점수와 토큰·시간·비용 지표를 분리해 집계한다.
- 사례별 결과, `summary.json`, `report.md`를 생성한다.

완료 기준: 같은 기록을 다시 평가하면 같은 결정적 점수가 나오고 LLM 평가의 설정과 근거가 남는다.

### 단계 6. 안정화와 자동화

목표: 반복 실행과 회귀 비교에 사용할 수 있는 운영 수준으로 다듬는다.

- 대표 suite의 end-to-end 테스트와 실패 진단 정보를 보강한다.
- 버전·환경 차이를 비교할 수 있는 리포트를 추가한다.
- CI 또는 정기 실행 방식을 결정하고 문서화한다.
- 격리가 검증된 범위에서 제한적인 병렬 실행을 도입한다.

완료 기준: 새 버전의 Clio를 동일 suite로 반복 평가하고 이전 결과와 신뢰할 수 있게 비교할 수 있다.

## 5. 단계 의존 관계

```text
계약 확정 -> 프로젝트 기반 -> 로컬 환경 -> 단일 사례(MVP)
                                      -> 다중 사례 -> 평가·보고 -> 안정화
```

Runtime과 서비스 API 조사는 병행할 수 있지만, 단일 사례 구현 전에 API 계약을 고정해야 한다. 평가기는 기록 형식이 안정된 뒤 구현한다.

## 6. 검증 전략

| 수준 | 검증 대상 |
|---|---|
| 단위 테스트 | 설정, manifest, 상태 전이, 점수 계산 |
| 계약 테스트 | Benchmark와 Server·Agent 사이의 요청·응답 |
| 통합 테스트 | Docker 환경, 상태 polling, 기록 수집 |
| End-to-end | 실제 테스트 저장소의 전체 MVP 흐름 |

실제 LLM 호출이 필요한 테스트와 그렇지 않은 테스트를 분리한다. 일반 CI는 빠르고 결정적인 검사를 수행하고, 비용이 드는 벤치마크 실행은 별도 작업으로 운영한다.

## 7. 초기 구현에서 미루는 항목

- 웹 UI와 실시간 대시보드
- 분산 실행과 대규모 병렬 처리
- 자동 프롬프트·모델 튜닝
- 여러 LLM judge의 합의 평가
- 장기 결과 저장용 별도 데이터베이스

필요성이 검증되기 전까지 결과는 파일 기반으로 관리한다.

## 8. 주요 위험과 대응 방향

| 위험 | 대응 방향 |
|---|---|
| Server·Agent API 부족 | 단계 0에서 gap을 식별하고 서비스별 선행 작업으로 분리 |
| 테스트 정답 노출 | 입력 저장소와 oracle 접근 경로 분리 |
| 사례 간 상태 오염 | 초기 순차 실행과 명시적 초기화 적용 |
| LLM 비결정성 | 실행 조건 기록, 반복 실행, 결정적 평가 우선 |
| 인프라 실패가 오답으로 집계 | `INFRA_ERROR`를 별도 상태로 관리 |
| 버전 변화로 비교 불가 | commit SHA, 이미지 digest, 모델·평가 설정 기록 |

## 9. 구현 결정

패키징과 설정:

- Python 3.11+, `src` layout, hatchling build backend와 `clio-benchmark` console script를 사용한다.
- 개발·잠금·실행 도구는 `uv`를 사용하고 일반 `pip install`도 가능한 표준 `pyproject.toml`을 유지한다.
- 첫 suite는 `team-clio/clio-benchmark-fixture-feature-flags`이며 이후 같은 계약으로 추가한다.
- 키는 gitignore 대상인 로컬 설정 파일로 받아 컨테이너 환경변수에 전달한다. manifest에는 값 대신 키 이름만 기록한다.

기존 Clio에서 재사용할 기능:

- Server의 프로젝트 생성·삭제, 저장소 등록·목록, 버그 생성·목록과 최신 분석 결과 API를 사용한다.
- 저장소 목록의 `syncStatus`로 `SYNCED` 또는 `FAILED`까지 기다린다.
- Agent workflow의 `PENDING/RUNNING/COMPLETED/FAILED` 상태와 `resultSnapshot`을 완료 판정에 사용한다.
- Server는 `/actuator/health`, Agent는 LangGraph health endpoint로 준비 상태를 확인한다.

추가할 기능:

- Server에 `request_id`로 workflow run을 조회하는 read-only API를 추가한다. 버그 ID로 만든 `process-bug-{bugId}` 요청의 완료 상태와 결과를 찾는 용도다.
- Agent에 모델 호출 수, 입력·출력 토큰, 도구 호출과 소요 시간을 집계해 workflow 결과에 포함하는 계측을 추가한다.
- Agent 저장소에는 Dockerfile이 없으므로 추가하고, Benchmark가 두 서비스와 의존 컨테이너를 묶는 Compose 구성을 소유한다.

`BENCHMARK_MODE`는 위 계측 활성화와 외부 알림 차단에만 사용한다. 데이터 초기화 전용 API는 만들지 않는다. 하나의 benchmark run이 하나의 Docker Compose project와 새 데이터 volume을 사용하고, 같은 run 안의 suite는 서로 다른 Clio 프로젝트로 격리한다.

## 10. 보류 사항

- 첫 suite의 Server·Agent 실제 처리와 원인 탐지는 검증했다. oracle 자동 채점은 미정이다.
- Agent·Server Docker 실행과 격리 DB 준비를 Benchmark `setup`/`down`에 통합해야 한다.
- workflow 실패를 timeout 전에 감지할 `request_id` 조회 API의 경로와 응답을 확정해야 한다.
