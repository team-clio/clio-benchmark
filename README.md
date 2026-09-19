# Clio Benchmark

여러 벤치마크 저장소를 같은 조건에서 실행하고 Clio의 버그 분석 품질과 실행 효율을 평가하는 도구입니다. Clio에 제출하는 입력과 평가용 Ground Truth를 분리하여 정답이 Agent에 노출되지 않도록 합니다.

## 현재 구현 범위

- Python 패키지와 `clio-benchmark` CLI
- YAML 설정 검증 및 비밀 값이 제거된 실행 manifest
- 빈 테스트 저장소 목록을 허용하는 실행 흐름
- 테스트 저장소 checkout과 `cases.json`/`bugs.json` 검증
- Clio 프로젝트·저장소·버그 생성 및 완료 polling
- suite commit, Clio 원시 결과와 정규화된 결과 저장
- 결정적 Bug 탐지·코드 위치 평가
- Case별 오류 격리와 부분 실패 실행
- 실행 요약과 Markdown report 생성
- LangChain 기반 LLM Judge 구조화 평가
- 품질 점수 골격과 별도 효율성 지표

Clio Agent·Server의 Docker 실행 자동화와 최종 점수 집계는 다음 구현 단계입니다. 현재
`run`은 설정된 주소에서 두 서비스가 이미 실행 중이어야 합니다. LLM Judge를 사용하려면
`evaluation.llm_judge.enabled`를 `true`로 설정하고 `api_key_env`가 가리키는 환경 변수에
API 키를 입력합니다. Judge 결과와 모델·프롬프트 설정은 Case별 `evaluation.json`에 저장됩니다.
`provider`는 `openai` 또는 `deepseek`를 지원합니다. DeepSeek는 기본적으로
`DEEPSEEK_API_KEY`, `https://api.deepseek.com`, `deepseek-flash`를 사용합니다.

```yaml
evaluation:
  llm_judge:
    enabled: true
    provider: deepseek
```

## 시작하기

```shell
cp benchmark.example.yaml benchmark.local.yaml
uv sync --extra dev
uv run clio-benchmark setup
uv run clio-benchmark run
uv run clio-benchmark status
uv run clio-benchmark report
```

로컬 키는 git에서 제외되는 `benchmark.local.yaml`의 `secrets`에 입력합니다. 실행 manifest에는 값 대신 키 이름만 저장됩니다.

기본 예시는 `team-clio/clio-benchmark-fixture-feature-flags`를 사용합니다. Fixture 저장소에는 다음 두 파일이 필요합니다.

- `cases.json`: Clio에 제출할 사용자 관점의 Bug Report
- `bugs.json`: Benchmark Evaluator만 사용하는 실제 원인과 코드 위치

두 파일은 저장소 등록 시 Clio 분석 대상에서 제외됩니다. 두 파일의 Case ID 집합은 정확히 일치해야 합니다.

실행 결과는 다음 구조로 저장됩니다.

```text
.benchmark/runs/<run-id>/
├── manifest.json
├── summary.json
├── report.md
└── cases/<suite>/<case-id>/
    ├── input.json
    ├── clio-result.json
    ├── evaluation.json
    └── metrics.json
```

## 문서

- [벤치마크 설계](docs/benchmark-design.md)
- [구현 계획](docs/implementation-plan.md)

## 문서 상태

- 상태: 구현 진행 중
- 최종 수정일: 2026-09-14
- 리뷰: Clio-Agent 및 Clio-Server 담당자 리뷰 필요
