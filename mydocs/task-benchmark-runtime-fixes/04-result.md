# 벤치마크 실행 오류 수정 결과

- 상태: 30개 전체 실행 완료
- 작성일: 2026-10-03
- 독자: 벤치마크 실행자와 Clio 개발자
- 사람 리뷰: 확인 필요
- 절차: 사용자가 단계별 문서·승인 절차 생략을 승인했다.

## 문제와 변경

| 문제 | 변경 및 근거 |
|---|---|
| `needs_review` workflow는 완료됐지만 Bug는 `ANALYZING`에 남음 | Server가 같은 트랜잭션에서 Bug를 `TRIAGED`로 전이한다. Issue를 임의로 만들지 않는다. |
| 앞선 케이스의 Issue와 분석이 다음 케이스에 재사용됨 | 케이스마다 별도 프로젝트·저장소를 만든다. 프로젝트 정보는 케이스 metadata에도 저장한다. |
| 실제 `issueAnalysis` 응답을 읽지 못해 탐지가 false로 기록됨 | 가설·사실·해결 단계·근거 위치를 실제 응답 필드에서 정규화한다. 분석 없는 검토 결과는 탐지 false로 평가한다. |
| 입력 파일이 Agent 근거에 섞임 | `benchmark.json`, `DATASET.md`도 repository 제외 경로에 추가한다. |
| DeepSeek가 Tool 응답 누락으로 400을 반환함 | 병렬 호출을 끄고, 혼합 구조화 출력에서 미실행 Tool을 사실대로 오류 응답에 표시해 별도 호출을 요청한다. 가짜 실행 결과는 만들지 않는다. |
| 보고서 LLM이 실제 스키마와 다른 필드 이름을 반환함 | 서술 프롬프트에 JSON Schema와 정확한 필드 이름을 명시하고 저장된 결과에서 재생성한다. |
| workflow 실패 기록도 동기 소켓 호출로 차단됨 | 비동기 실패 경로에서 기록 API를 별도 스레드로 호출한다. |

Server와 Agent는 각각 `task/benchmark-runtime-fixes`에서 변경했다.
업무 데이터 쓰기는 기존대로 Server가 소유한다.

## 검증

- CLI: pytest 50개 통과, Ruff 통과.
- Server: 전체 Gradle 테스트 통과. 검토 완료·멱등 replay 회귀 테스트 포함.
- Agent: pytest 286개 통과, 3개 skip. Tool 혼합 응답 회귀 테스트 포함.
- 전체 실행: `.benchmark/runs/20261003T075211Z-305cc356`, CLI 종료 코드 0.
- 케이스 30개 완료, 실패 0개. Judge 30개 완료, 실패 0개.
- 탐지 30개, 정답 코드 위치 일치 24개.
- Tool 로그 수집 API 완료(0건), HTML·LLM 서술 생성 완료.
- 직전 실패 케이스 `auth-project-scope-short`는 이 실행에서 분석·Judge 완료.

## 실행 환경과 재현

Agent는 벤치마크 모드와 `--no-reload`로 실행했다.
Server는 로컬 PostgreSQL과 이미 실행 중인 Ollama를 사용했다.
로컬 Judge 설정을 활성화하고 Fish의 `DEEPSEEK_API_KEY_CLIO`를 사용했다.
비밀 값은 결과 문서나 커밋에 기록하지 않는다.

## 해석과 남은 범위

- 실행 성공은 분석 정답률이나 수정 성공률을 뜻하지 않는다.
- 최종 가중치 Quality Score 집계는 기존 미구현 범위다.
- 원격 fixture는 아직 `benchmark.json` 형식이다. 현재 checkout에 생성한
  `cases.json`과 `bugs.json`은 `.benchmark` 아래의 로컬 데이터다.
- 과거 비공개 oracle을 찾지 못해 fixture 코드에서 정답을 재구성했다.
  이전 평가와 동일한 기준이라고 간주하지 않는다.
- Tool 로그 callback은 현재 LLM Tool loop에 붙는다. 그래프가 직접 호출하는
  조회 Tool은 수집 범위에 포함되지 않아 이번 로그 파일은 0건이다.
  이를 Tool 실행이 전혀 없었다는 뜻으로 해석하지 않는다.
- 서비스 자동 기동·종료 기능은 추가하지 않았다.
