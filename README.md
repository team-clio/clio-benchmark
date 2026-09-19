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
`run`은 설정된 주소에서 두 서비스가 이미 실행 중이어야 합니다.

## 시작하기

```shell
cp benchmark.example.yaml benchmark.local.yaml
uv sync --extra dev
uv run clio-benchmark setup
uv run clio-benchmark run
uv run clio-benchmark status
uv run clio-benchmark report
```

Clio Agent·Server에 전달할 로컬 키는 git에서 제외되는 `benchmark.local.yaml`의
`secrets`에 입력합니다. 실행 manifest에는 값 대신 키 이름만 저장됩니다. LLM Judge API
키는 YAML에 입력하지 않고 아래 설명처럼 환경 변수로 전달합니다.

## LLM Judge 설정

LLM Judge는 Clio 분석 결과의 근본 원인 정확성, 설명 품질, 해결책 타당성, 근거 품질을
각각 0~4점으로 평가합니다. `provider`는 `openai`와 `deepseek`를 지원하며 기본값은
`openai`입니다. Judge를 사용하지 않으면 `enabled: false`로 두면 됩니다.

### OpenAI

`benchmark.local.yaml`에서 Judge를 활성화합니다.

```yaml
evaluation:
  llm_judge:
    enabled: true
    provider: openai
```

기본 모델은 `gpt-4.1`, 기본 키 환경 변수는 `OPENAI_API_KEY`입니다.

```shell
export OPENAI_API_KEY="your-api-key"
uv run clio-benchmark run
```

### DeepSeek

```yaml
evaluation:
  llm_judge:
    enabled: true
    provider: deepseek
```

DeepSeek 기본 설정은 다음과 같습니다.

- 모델: `deepseek-flash`
- API 키 환경 변수: `DEEPSEEK_API_KEY`
- Base URL: `https://api.deepseek.com`

```shell
export DEEPSEEK_API_KEY="your-api-key"
uv run clio-benchmark run
```

### 세부 설정과 사용자 지정 endpoint

Provider 기본값을 변경해야 할 때만 다음 항목을 지정합니다.

```yaml
evaluation:
  llm_judge:
    enabled: true
    provider: deepseek
    model: deepseek-v4-pro
    api_key_env: CUSTOM_LLM_API_KEY
    base_url: https://llm-gateway.example.com/v1
    temperature: 0
    timeout_seconds: 60
    max_retries: 2
    max_source_chars: 20000
    prompt_version: v1
```

- `model`: Judge 모델 이름
- `api_key_env`: API 키를 읽을 환경 변수 이름. 키 자체를 입력하지 않습니다.
- `base_url`: OpenAI-compatible API 주소
- `temperature`: 평가 생성 온도
- `timeout_seconds`: LLM 요청 제한 시간
- `max_retries`: LangChain/OpenAI client의 최대 재시도 횟수
- `max_source_chars`: Judge에 전달할 Ground Truth 코드 구간의 최대 문자 수
- `prompt_version`: 결과에 기록할 평가 프롬프트 버전

위 예시에서는 다음과 같이 키를 전달합니다.

```shell
export CUSTOM_LLM_API_KEY="your-api-key"
```

### 평가 결과

각 Case의 결과는 다음 위치에 저장됩니다.

```text
.benchmark/runs/<run-id>/cases/<suite>/<case-id>/evaluation.json
```

`llmJudge.status`는 다음 값을 가집니다.

- `disabled`: Judge가 비활성화됨
- `completed`: 구조화 평가 완료. `result`에 항목별 점수와 판단 근거가 저장됨
- `failed`: Judge 호출 또는 응답 검증 실패. `error`에 원인이 저장됨

`completed`와 `failed` 결과 모두 사용한 provider, 모델, temperature, timeout, 재시도 횟수,
프롬프트 버전을 함께 기록합니다. Judge 실패는 해당 Case의 `evaluation_failed`로 분류되며
다른 Case 처리는 계속됩니다.

현재 LLM Judge 평가는 구현되어 있지만 결정적 평가와 결합한 최종 가중치 점수 산출은 아직
구현되지 않았습니다. 따라서 Judge 완료 후에도 전체 Quality Score는
`pending_score_aggregation`으로 기록됩니다.

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
