# Clio Benchmark 설계

## 1. 문서 정보

상태: 초안 · 독자: Benchmark/Agent/Server 개발자 · 수정: 2026-09-11 · 리뷰 필요 · 목적: 실행 절차와 시스템 계약 정의

## 2. 목표와 범위

Clio Benchmark는 여러 테스트 저장소를 같은 조건으로 실행하고 Clio의 버그 처리 품질과 실행 효율을 평가하는 오케스트레이터다.

- 포함: Agent·Server 로컬 환경 구성, 테스트 프로젝트·리포트 등록, 완료 대기, 기록 수집, 평가와 보고
- 제외: 테스트 버그 자동 생성, 운영 배포, 결과를 이용한 모델·프롬프트 자동 변경

## 3. 설계 원칙

1. 저장소 revision, 이미지, 모델 및 평가 설정을 기록해 실행을 재현한다.
2. 실행과 평가를 분리하고 결정적 검증을 우선한다.
3. 입력은 시스템에 제공하되 채점용 정답은 접근할 수 없게 한다.
4. 의미 판단이 필요한 항목에만 LLM judge를 사용한다.
5. 모든 요청과 기록을 `run_id`, `case_id`, `correlation_id`로 추적한다.
6. 일부 사례가 실패해도 나머지를 실행하고 실패 원인을 보존한다.

## 4. 구성 요소

| 구성 요소 | 책임 |
|---|---|
| CLI | setup, run, status, report, down 명령 제공 |
| Repository Manager | 저장소 clone, revision 고정, 작업 공간 관리 |
| Runtime Manager | Docker 이미지·네트워크·컨테이너 관리 |
| Clio Client | Server와 Agent API 호출 |
| Workflow Poller | 상태 조회, timeout, retry 처리 |
| Record Collector | trace, 토큰, 모델 및 도구 사용 기록 수집 |
| Evaluator | 결정적 검사와 LLM judge 실행 |
| Reporter | 사례별 결과와 전체 요약 생성 |

구현 언어는 미정이다. 초기에는 단일 프로세스 CLI로 만들고 필요할 때 구성 요소를 분리한다.

## 5. 전체 흐름

```text
setup -> Agent/Server checkout -> Docker 실행(BENCHMARK_MODE=true) -> health check
run   -> 테스트 저장소 checkout -> 프로젝트·리포트 등록 -> 종료 대기
      -> Server/Agent 기록 수집 -> 평가 및 결과 저장
```

실행 상태는 `PENDING -> PROJECT_READY -> REPORTS_SUBMITTED -> PROCESSING -> RECORDS_COLLECTED -> SCORED -> COMPLETED` 순서다. 복구할 수 없는 오류는 단계와 원인을 기록하고 `FAILED`로 종료한다.

## 6. setup 과정

`clio-benchmark setup`은 다음 작업을 멱등하게 수행한다.

1. 설정된 URL에서 Clio-Agent와 Clio-Server를 clone하고 지정 revision을 checkout한다.
2. 각 Docker 이미지를 빌드하고 전용 network에서 두 컨테이너를 실행한다.
3. 두 컨테이너에 `BENCHMARK_MODE=true`를 전달한다.
4. health endpoint가 준비될 때까지 기다린다.
5. commit SHA, 이미지 digest, port와 시작 시간을 저장한다.

권장 작업 구조:

```text
.benchmark/
  sources/{clio-agent,clio-server}/  suites/<suite-id>/  runs/<run-id>/
```

`BENCHMARK_MODE`는 상세 trace 제공, correlation ID 전파, 외부 알림 차단, 사례 데이터 초기화를 지원해야 한다. 실제 처리 경로를 우회하거나 정답을 노출하면 안 된다. 서비스별 세부 동작은 담당자 협의 필요다.

## 7. 실행 설정

```yaml
clio:
  agent:
    repository: https://github.com/team-clio/clio-agent-graph.git
    revision: main
  server:
    repository: https://github.com/team-clio/clio-server.git
    revision: main
runtime:
  startup_timeout_seconds: 300
  case_timeout_seconds: 1800
  poll_interval_seconds: 5
suites: [] # 테스트 저장소 URL을 전달받은 뒤 추가
```

공식 실행에서는 branch 대신 commit SHA 또는 tag를 사용한다.

## 8. 벤치마크 저장소 계약

각 테스트 저장소 루트의 `benchmark.json`에는 시스템 입력만 둔다. 정답과 버그 삽입 위치는 포함하지 않는다.

```json
{
  "schemaVersion": 1,
  "suite": {"id": "sample-suite", "name": "Sample benchmark"},
  "reports": [{
    "id": "BUG-001", "title": "로그인 후 세션이 간헐적으로 사라진다",
    "description": "재현 상황과 관찰된 증상",
    "stepsToReproduce": ["첫 번째 단계", "두 번째 단계"],
    "expectedBehavior": "기대 동작", "observedBehavior": "실제 동작"
  }]
}
```

필수 필드는 `schemaVersion`, `suite.id`, `reports[].id`, `title`, `description`으로 제안한다. Clio-Server Bug API에 맞춘 최종 필드는 확인 필요다.

채점용 oracle은 별도 저장소 또는 실행자 전용 경로에 둔다. 평가 대상 컨테이너에는 해당 경로를 mount하거나 API로 전달하지 않는다.

## 9. 사례 실행

1. 테스트 저장소를 지정 revision으로 checkout한다.
2. 고유한 `run_id`와 사례별 `case_id`를 생성한다.
3. Server에 프로젝트를 생성하고 저장소를 등록한다.
4. 저장소 동기화 완료를 기다린다.
5. `benchmark.json`을 검증하고 리포트를 Server API로 등록한다.
6. 반환된 작업 ID와 correlation ID를 저장한다.
7. 모든 작업이 성공·실패·검토 필요 등 종료 상태가 될 때까지 polling한다.
8. Server와 Agent에서 관련 기록을 수집한다.
9. 기록과 oracle을 평가기에 전달하고 결과를 보존한다.

초기 버전은 사례 간 영향을 막기 위해 순차 실행한다. 병렬 실행은 격리 기준이 정해진 뒤 도입한다.

## 10. 필요한 서비스 계약

| 서비스 | 필요한 기능 |
|---|---|
| Server | 프로젝트 생성, 저장소 등록, 동기화 상태 조회 |
| Server | 리포트 생성, 처리 상태 및 최종 분석 조회 |
| Server | run 또는 correlation ID 기준 작업 기록 조회 |
| Agent | correlation ID 기준 trace와 모델·도구 사용량 조회 |
| 공통 | health check와 벤치마크 데이터 초기화 |

API 경로와 payload는 확인 필요다. 상태 API는 명시적인 종료 상태를 반환해야 하며 로그 문자열로 완료를 추측하지 않는다.

## 11. 수집 기록

- 입력 리포트, 실행 ID, 저장소와 서비스 commit SHA
- 요청·작업·trace ID와 상태 변경 시각
- 최종 판정, 원인, 코드 위치, 근거 및 confidence
- 모델, 프롬프트·완료 토큰, 도구 호출 횟수
- 전체 시간, 대기 시간, 오류와 retry 횟수

환경변수의 비밀 값과 인증 토큰은 저장 전에 제거한다.

## 12. 평가와 점수

초기 점수안은 다음과 같으며 실험 전에 확정해야 한다.

| 항목 | 배점 | 평가 방식 |
|---|---:|---|
| 버그 유효성 판정 | 20 | oracle 일치 여부 |
| 근본 원인 | 35 | 규칙 검사와 LLM judge |
| 코드 위치 | 15 | 파일·범위 일치도 |
| 근거 품질 | 15 | LLM judge와 인용 검증 |
| 재현·검증 | 10 | 실행 테스트 |
| 불확실성 처리 | 5 | 정보 부족 사례 판정 |

토큰, 비용, 처리 시간은 품질과 별도 지표로 보고하고 품질 하한을 통과한 실행끼리 비교한다. LLM judge의 모델, 버전, 프롬프트, temperature와 판단 근거를 저장하고 표본을 사람이 블라인드 리뷰해야 한다.

## 13. 결과와 오류 정책

```text
runs/<run-id>/
  manifest.json
  environment.json
  cases/<case-id>/{input,records,score}.json
  summary.json
  report.md
```

- 일시적인 통신 오류만 제한적으로 retry한다.
- timeout은 오답과 구분해 `INFRA_ERROR`로 기록한다.
- 같은 `run_id` 요청은 프로젝트나 리포트를 중복 생성하지 않는다.
- 일부 실패 시 계속 실행하고 최종 상태를 `COMPLETED_WITH_ERRORS`로 남긴다.
- 재실행은 새 `run_id`를 사용하고 이전 결과를 덮어쓰지 않는다.

## 14. 주요 결정과 근거

- Docker: 두 서비스를 같은 조건으로 격리하고 환경을 기록하기 쉽다.
- 입력과 oracle 분리: Agent가 정답을 읽는 데이터 누출을 막는다.
- 초기 순차 실행: 동시성보다 사례별 추적과 격리를 먼저 검증한다.
- 제한적 LLM 평가: 점수 재현성과 감사 가능성을 높인다.

## 15. 확인 필요 사항

- Server·Agent API 경로, payload, 종료 상태와 timeout
- 사례 데이터 초기화 범위와 `benchmark.json`의 최종 Bug API 필드
- oracle 저장 위치·권한과 결과·LLM 입력의 코드·로그 허용 범위
- 점수 가중치, 품질 하한, LLM judge 운영 기준
- 구현 언어, 패키징 방식 및 CI 환경

## 16. 구현 순서

1. setup, health check, down
2. 단일 저장소·리포트 실행, 상태 대기, 기록 수집
3. 다중 리포트 실행과 결정적 평가
4. LLM judge와 종합 보고서
5. 다중 suite, 격리 및 병렬화
