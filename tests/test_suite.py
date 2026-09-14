from pathlib import Path

import pytest

from clio_benchmark.errors import SuiteError
from clio_benchmark.suite import load_benchmark_file


def test_loads_feature_flag_benchmark_contract() -> None:
    fixture = Path("../clio-benchmark-fixture-feature-flags/benchmark.json")

    benchmark = load_benchmark_file(fixture)

    assert benchmark.schema_version == 1
    assert [case.id for case in benchmark.cases] == [
        "flag-value-changes-after-another-tenant-lookup"
    ]
    assert "재현 절차" in benchmark.cases[0].report.as_bug_description()


def test_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    path = tmp_path / "benchmark.json"
    path.write_text(
        """
        {
          "schema_version": 1,
          "cases": [
            {
              "id": "same",
              "report": {
                "title": "title",
                "description": "description",
                "steps_to_reproduce": ["step"],
                "expected_behavior": "expected",
                "actual_behavior": "actual"
              }
            },
            {
              "id": "same",
              "report": {
                "title": "title",
                "description": "description",
                "steps_to_reproduce": ["step"],
                "expected_behavior": "expected",
                "actual_behavior": "actual"
              }
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    with pytest.raises(SuiteError, match="case ids must be unique"):
        load_benchmark_file(path)
