# HTML 벤치마크 보고서 구현 결과

상태: 완료 · 작성: 2026-10-03 · 브랜치: `task/html-benchmark-report`

## 완료한 범위

- Tool 로그 수집과 최종 manifest 저장 후 고정 템플릿으로 `report.html`을 자동 생성한다.
- 요약·평가·실행·사례·개선·조건의 6개 섹션을 사용하고 수치와 표는 코드가 계산한다.
- 보고서 LLM은 Judge 설정을 기본으로 상속하며 전용 모델·키·endpoint 등으로 덮어쓸 수 있다.
- LLM은 한국어 구조화 서술과 근거 ID만 반환한다. 없는 근거·응답 검증 실패는 서술 실패로 처리한다.
- LLM 실패에도 수치·표 HTML을 남기며 벤치마크 상태·종료 코드를 바꾸지 않는다.
- 실패·취소·빈 실행은 남은 자료로 보고서를 만든다. 보고서 전체 생성 실패도 별도로 기록한다.
- 입력·정답의 suite snapshot과 정규화 응답을 보존한다. 현재 checkout을 과거 정답으로 사용하지 않는다.
- 저장된 실행에서 HTML을 재생성할 수 있다. 재실행·재채점을 하거나 manifest 상태를 변경하지 않는다.
- 보고서 데이터, 서술 결과, LLM 입력, 생성 상태를 JSON으로 남긴다.
- HTML escaping, 평가 스키마 검사, 없는 값과 0의 구분, 부분 로그의 경고를 적용한다.

## 검증

| 검사 | 결과 |
|---|---|
| 전체 pytest | 48개 통과 |
| `ruff check .` | 통과 |
| 변경한 Python 파일 `ruff format --check` | 통과 |
| `git diff --check` | 통과 |
| `uv build --offline` | sdist·wheel 생성 성공 |
| wheel 격리 경로 로딩 | 포함된 HTML 템플릿으로 보고서 렌더링 성공 |
| 브라우저 | fixture 보고서의 요약·목차·근거 링크·상세 대조 확인 |

테스트는 정상·실패·취소·Tool 수집 실패의 최종 상태, 서술 실패 fallback, 존재하지 않는 근거 ID,
누락·손상 평가의 분모 제외, Judge 실패의 평균 제외, 입력 예산, snapshot 보존, 재생성,
HTML escaping, provider 설정 상속, LangChain 구조화 응답 경로를 포함한다.

저장소 전체 포맷 검사에는 기존 미변경 파일 4개(`evaluation.py`, `llm_judge.py`, `result.py`,
`suite.py`)의 포맷 차이가 남아 있다. 이번 변경 파일은 포맷 검사를 통과했다.

## 사용과 산출물

```shell
uv run clio-benchmark run
uv run clio-benchmark report --format html
uv run clio-benchmark report --format html --regenerate --run-id <run-id>
```

설정·실패 처리·지표 정의는 [HTML 보고서 문서](../../docs/html-report.md)를 참조한다.
API 키는 환경 변수로 전달한다. 기본 보고서 LLM은 활성화이며 Judge provider의 설정을 사용한다.

## 검증 범위와 남은 제약

실제 Server·Agent 벤치마크와 외부 LLM API 호출은 수행하지 않았다. 미리보기는 명시한 테스트 대역이다.
LLM 서술의 의미적 정확성을 스키마와 ID 검증만으로 보장하지는 못한다.
입력 예산 때문에 일부 사례 서술은 생략되거나 잘릴 수 있다. HTML의 전체 사례 자료는 유지한다.
종합 점수·토큰·비용·실행 서비스 버전 검증·Docker 격리 자동화는 기존 미구현 범위다.
원시 자료 링크를 유지하려면 보고서와 실행 디렉터리를 함께 보관해야 한다.
