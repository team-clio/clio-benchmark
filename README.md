# Clio Benchmark

여러 벤치마크 저장소를 같은 조건에서 실행하고 Clio의 버그 분석 품질과 실행 효율을 평가하는 도구입니다.

## 현재 구현 범위

- Python 패키지와 `clio-benchmark` CLI
- YAML 설정 검증 및 비밀 값이 제거된 실행 manifest
- 빈 테스트 저장소 목록을 허용하는 실행 흐름
- 테스트 저장소 checkout과 `benchmark.json` 검증
- Clio 프로젝트·저장소·버그 생성 및 완료 polling
- suite commit, Clio 리소스와 분석 결과 저장
- 품질 점수 집계와 별도 효율성 지표

Clio Agent·Server의 Docker 실행 자동화와 oracle 기반 자동 채점은 다음 구현 단계입니다. 현재 `run`은 설정된 주소에서 두 서비스가 이미 실행 중이어야 합니다.

## 시작하기

```shell
cp benchmark.example.yaml benchmark.local.yaml
uv sync --extra dev
uv run clio-benchmark setup
uv run clio-benchmark run
uv run clio-benchmark status
```

로컬 키는 git에서 제외되는 `benchmark.local.yaml`의 `secrets`에 입력합니다. 실행 manifest에는 값 대신 키 이름만 저장됩니다.

기본 예시는 `team-clio/clio-benchmark-fixture-feature-flags`의 실제 버그 리포트 한 건을 실행합니다. `benchmark.json`은 Agent 분석에서 제외해 정답 유출을 방지합니다.

## 문서

- [벤치마크 설계](docs/benchmark-design.md)
- [구현 계획](docs/implementation-plan.md)

## 문서 상태

- 상태: 구현 진행 중
- 최종 수정일: 2026-09-14
- 리뷰: Clio-Agent 및 Clio-Server 담당자 리뷰 필요
