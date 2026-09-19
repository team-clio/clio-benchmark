import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from clio_benchmark.config import SuiteConfig
from clio_benchmark.errors import SuiteError
from clio_benchmark.suite import PreparedSuite, load_bugs_file, load_cases_file

FIXTURE = Path("tests/fixtures/suite")


def test_loads_separate_input_and_ground_truth_contracts() -> None:
    cases = load_cases_file(FIXTURE / "cases.json")
    bugs = load_bugs_file(FIXTURE / "bugs.json")

    assert [case.id for case in cases.cases] == ["BUG-001"]
    assert "재현 절차" in cases.cases[0].report.as_bug_description()
    assert bugs.bugs[0].location.lines == (42, 58)
    assert bugs.bugs[0].root_cause.startswith("The update path")


def test_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    payload = json.loads((FIXTURE / "cases.json").read_text(encoding="utf-8"))
    payload["cases"].append(payload["cases"][0])
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SuiteError, match="case ids must be unique"):
        load_cases_file(path)


def test_requires_matching_case_and_ground_truth_ids() -> None:
    cases = load_cases_file(FIXTURE / "cases.json")
    bugs = load_bugs_file(FIXTURE / "bugs.json")
    bugs.bugs[0].id = "BUG-OTHER"

    with pytest.raises(ValidationError, match="ids must match"):
        PreparedSuite(
            config=SuiteConfig(
                name="fixture", repository="https://example.com/fixture.git", revision="main"
            ),
            path=FIXTURE,
            commit_sha="abc123",
            cases=cases,
            ground_truth=bugs,
        )
