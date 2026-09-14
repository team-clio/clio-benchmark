# Clio Benchmark

여러 벤치마크 저장소를 같은 조건에서 실행하고 Clio의 버그 분석 품질과 실행 효율을 평가하는 도구입니다.

## 현재 구현 범위

- Python 패키지와 `clio-benchmark` CLI
- YAML 설정 검증 및 비밀 값이 제거된 실행 manifest
- 빈 테스트 저장소 목록을 허용하는 실행 흐름
- 품질 점수 집계와 별도 효율성 지표

Clio 저장소 복제, Docker 실행, API 작업 수집은 다음 구현 단계입니다. 테스트 저장소가 설정된 실행은 잘못된 성공 결과를 만들지 않도록 현재 실패 처리합니다.

## 시작하기

```shell
cp benchmark.example.yaml benchmark.local.yaml
uv sync --extra dev
uv run clio-benchmark setup
uv run clio-benchmark run
uv run clio-benchmark status
```

로컬 키는 git에서 제외되는 `benchmark.local.yaml`의 `secrets`에 입력합니다. 실행 manifest에는 값 대신 키 이름만 저장됩니다.

## 문서

- [벤치마크 설계](docs/benchmark-design.md)
- [구현 계획](docs/implementation-plan.md)

## 문서 상태

- 상태: 구현 진행 중
- 최종 수정일: 2026-09-14
- 리뷰: Clio-Agent 및 Clio-Server 담당자 리뷰 필요
