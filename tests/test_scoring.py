from pathlib import Path

from clio_benchmark.config import EvaluationConfig
from clio_benchmark.oracle import load_oracle
from clio_benchmark.scoring import score_case


def test_scores_expected_root_cause_location_and_evidence() -> None:
    oracle = load_oracle(Path("oracles/feature-flags.json")).cases[0]
    result = {
        "bug": {"status": "TRIAGED"},
        "analysis": {
            "issueAnalysis": {
                "status": "COMPLETED",
                "confidence": 0.9,
                "hypotheses": [
                    {
                        "hypothesis": (
                            "FeatureFlagCache._key cache key omits tenant_id and only uses "
                            "flag_name"
                        )
                    }
                ],
                "evidence": [
                    {
                        "source_type": "knowledge",
                        "location": "src/feature_flags/cache.py:1-16",
                        "source_revision": "abc123",
                    },
                    {
                        "source_type": "knowledge",
                        "location": "src/feature_flags/repository.py:1-21",
                        "source_revision": "abc123",
                    },
                    {
                        "source_type": "knowledge",
                        "location": "src/feature_flags/service.py:1-26",
                        "source_revision": "abc123",
                    },
                ],
                "resolution_plan": {
                    "steps": ["Run tests/test_feature_flags.py for tenant-alpha and tenant-beta"]
                },
            }
        },
        "efficiency": {"duration_seconds": 62.0},
    }

    report = score_case(result, oracle, EvaluationConfig())

    assert report.score == 100
    assert report.passed is True
    assert report.efficiency.duration_seconds == 62.0


def test_missing_root_cause_does_not_receive_full_score() -> None:
    oracle = load_oracle(Path("oracles/feature-flags.json")).cases[0]
    result = {
        "bug": {"status": "TRIAGED"},
        "analysis": {
            "issueAnalysis": {
                "status": "COMPLETED",
                "confidence": 0.9,
                "hypotheses": [{"hypothesis": "The request may be malformed"}],
                "evidence": [],
                "resolution_plan": {},
            }
        },
    }

    report = score_case(result, oracle, EvaluationConfig())

    assert report.score < 50
    assert report.passed is False
