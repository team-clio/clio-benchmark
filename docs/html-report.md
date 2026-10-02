# HTML 결과 보고서

상태: 구현 완료 · 독자: 벤치마크 실행자 · 작성: 2026-10-03

## 실행과 확인

`run`은 Tool 로그 수집과 최종 manifest 저장 후 다음 보고서를 자동 생성한다.

```text
.benchmark/runs/<run-id>/
  report.html              사람이 읽는 6개 섹션 보고서
  report-data.json         보고서에 사용한 집계와 사례 자료
  report-narrative.json    LLM 서술 결과·설정·실패 원인
  report-generation.json   HTML 생성 상태와 서술 생성 상태
  report-llm-input.json    실제 서술 LLM 입력(LLM 입력을 구성한 경우)
```

HTML 파일 경로를 확인하고 브라우저에서 연다. 기존 Markdown 출력은 그대로 지원한다.

```shell
uv run clio-benchmark report --format html
uv run clio-benchmark report --format html --run-id <run-id>
uv run clio-benchmark report
```

## 목차와 작성 역할

| 섹션 | 코드가 제공 | LLM이 제공 |
|---|---|---|
| 실행 요약 | 최종 상태·평가 건수 | 핵심 관찰 1~3개 |
| 평가 결과 | suite별 결과·Judge 4항목 평균 | 사례와 점수를 연결한 해석 |
| 실행·수집 상태 | 오류 종류·시간·Tool 통계 | — |
| 케이스 상세 | 입력·정답·Clio 분석·Judge 근거 | — |
| 개선 제안 | 근거 ID의 유효성 검증 | 실패 양상·개선 항목·검증 방법 |
| 평가 조건·자료 | suite SHA·설정·평가 정의·산출물 링크 | — |

HTML·CSS는 패키지의 고정 템플릿이다. LLM은 JSON 서술만 반환하며 수치와 점수를 재채점하지 않는다.
모든 서술은 `run:summary`, `run:execution` 또는 입력에 제공한 `suite/case-id`를 근거로 연결한다.
없는 근거 ID·응답 스키마 위반은 서술 실패로 처리한다. 숫자·사실의 의미적 정확성은 LLM의 한계가 있다.
입력·정답·분석·LLM 문장은 HTML escaping 후 삽입한다.

## LLM 설정

보고서 LLM은 기본 활성화다. Judge의 활성화 여부와 무관하게 모델·키·endpoint 등의 설정을 재사용한다.
보고서 호출은 채점과 별도이며 API 사용 비용이 추가될 수 있다. 예:

```yaml
reporting:
  enabled: true
  llm:
    enabled: true
    model: gpt-4.1
    api_key_env: REPORT_API_KEY
    temperature: 0
    timeout_seconds: 60
    max_retries: 2
    prompt_version: report-v1
    max_input_chars: 60000
    max_case_chars: 4000
```

키 자체는 YAML에 넣지 않고 환경 변수로 전달한다. 기본 설정을 재사용한다면 Judge provider의 키를 설정한다.

```shell
export REPORT_API_KEY="your-api-key"
```

미지정 `provider`, `model`, `api_key_env`, `base_url`, `temperature`, timeout, retries는 Judge 설정을 상속한다.
다른 provider를 명시하면 이전 provider의 모델·키 환경 변수·endpoint는 상속하지 않고 새 provider 기본값을 쓴다.
`reporting.llm.enabled: false`는 LLM 없이 HTML을 생성한다. `reporting.enabled: false`는 HTML 생성을 끈다.

LLM에는 집계와 선택한 사례 설명을 전달한다. 입력 예산은 JSON 문자 수 기준이며 토큰 수 기준은 아니다.
실행 실패·위치 불일치·낮은 Judge 점수 순으로 사례를 선택하고, 포함·생략 건수를 기록한다.
사례 설명은 `max_case_chars`로 제한한다. 일부 텍스트가 잘릴 수 있으며 전체 내용은 HTML에 유지한다.
전체 집계만으로 입력 예산을 넘으면 LLM 서술을 실패 처리하고 수치·표를 유지한다.
환경변수·비밀 키 이름·Tool 인자/반환값은 보고서 LLM 입력에 포함하지 않는다.

## 실패와 부분 실행

LLM 호출·구조화 응답·근거 검증 실패 시 HTML은 생성하고 서술 실패를 표시한다.
보고서 생성 실패는 별도 파일에 기록하며 벤치마크의 상태·종료 코드를 바꾸지 않는다.
실패·취소·빈 실행에서도 확보한 자료를 사용한다. 빈 실행은 LLM 호출을 생략한다.
취소 후에도 보고서 생성 단계는 실행되므로, LLM이 활성화된 경우 해당 호출 시간이 추가될 수 있다.

예정 사례 목록이 있으면 `not_run`을 표시한다. 제출 입력이 있지만 최종 metrics가 없으면 `interrupted`다.
suite 준비 전에 실패한 경우 예정 수는 확인 불가다. 과거 실행도 존재하는 자료만 사용한다.
누락·읽기 실패는 보고서에 표시한다. 전체 수집 실패나 일부 자료 손상은 결과 해석 범위를 제한한다.

## 지표 정의

- `completed`: 절차 완료이며 분석 정답과 별도다. Judge 실패는 실행 오답과 분리한다.
- 탐지·위치 분모: 결정적 평가 자료가 있는 사례. 기존 Markdown의 전체 처리 사례 분모와 다르다.
- 탐지 신호: 정규화된 `detected`. 명시 판정이 없으면 원인·설명·위치 존재로 추론할 수 있다.
- 위치 일치: 동일 파일에서 정답 허용 범위와 한 곳 이상의 예측 범위가 겹치는 경우다.
- Judge 평균: 유효한 0~4점이 있는 사례만 포함한다. 실패·비활성을 0점으로 대체하지 않는다.
- 케이스 시간: 제출부터 Judge 종료까지 포함한다. 완료 사례와 실패·중단 사례를 따로 집계한다.
- P90: 정렬된 표본의 `(n-1)*0.9` 위치를 선형 보간한다. 표본 0은 값 없음으로 표시한다.
- 전체 경계 구간: suite 준비 등을 포함하고 종료 Tool 로그 다운로드는 제외한다.
- Tool 통계: 실행 경계 안에서 시작한 호출. 사례별 귀속이나 다른 요청 혼입 방지를 보장하지 않는다.

종합 점수·합격 판정·Precision·F1·재현 성공률·토큰·비용은 산출하지 않는다.
입력과 정답은 분리되지만 환경 격리·정답 누출 부재·사례의 독립 시행을 자동 검증하지는 않는다.
suite의 확인된 SHA와 서비스의 설정 revision은 구분한다. 실제 서비스 SHA·Agent 모델은 미검증이다.

## 저장된 실행에서 재생성

```shell
uv run clio-benchmark report --format html --regenerate --run-id <run-id>
uv run clio-benchmark report --format html --regenerate --config benchmark.local.yaml
```

기본은 manifest에 저장된 설정이며 `--config`로 보고서 설정을 덮어쓸 수 있다.
재생성은 Clio 실행·재채점을 하지 않고 보고서 파일을 갱신한다. LLM이 켜져 있으면 서술 API를 다시 호출한다.
manifest의 실행 상태는 변경하지 않는다. LLM 없이 재생성하려면 설정에서 보고서 LLM을 끈다.

새 실행은 suite checkout 직후 `suites/<suite>/{cases,ground-truth,metadata}.json`을 보존한다.
분석 응답은 `cases/<suite>/<case>/normalized-result.json`에도 저장한다.
과거 실행에 snapshot이 없으면 정답은 미확보로 표시한다. 현재 checkout에서 정답을 가져오지 않는다.
과거 원시 응답을 다시 정규화한 경우 해당 사례에 `recomputed-v1`을 표시한다.

원시 파일 링크는 보고서 옆 실행 디렉터리를 기준으로 한다. 보고서만 옮기면 링크는 작동하지 않는다.
템플릿은 네트워크·JavaScript·외부 폰트 없이 읽을 수 있으며 긴 표는 가로 스크롤을 지원한다.
