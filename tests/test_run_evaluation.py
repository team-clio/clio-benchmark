import json
from pathlib import Path

from clio_benchmark.config import load_config
from clio_benchmark.run_evaluation import evaluate_run, render_comparison
from clio_benchmark.workspace import Workspace


def test_evaluates_persisted_run_and_writes_reports(tmp_path: Path) -> None:
    config = load_config(Path("benchmark.example.yaml"))
    workspace = Workspace(tmp_path / ".benchmark")
    manifest = workspace.create_run(config)
    result_path = (
        workspace.runs
        / manifest.run_id
        / "cases/feature-flags/flag-value-changes-after-another-tenant-lookup/result.json"
    )
    result_path.parent.mkdir(parents=True)
    result_path.write_text(
        json.dumps(
            {
                "bug": {"status": "TRIAGED"},
                "analysis": {
                    "issueAnalysis": {
                        "status": "COMPLETED",
                        "confidence": 0.9,
                        "hypotheses": [
                            {
                                "hypothesis": (
                                    "FeatureFlagCache._key cache key omits tenant_id and "
                                    "flag_name identifies the collision"
                                )
                            }
                        ],
                        "evidence": [
                            {
                                "source_type": "code",
                                "location": "src/feature_flags/cache.py:1-16",
                                "commit": "abc",
                            },
                            {
                                "source_type": "code",
                                "location": "src/feature_flags/repository.py:1-21",
                                "commit": "abc",
                            },
                            {
                                "source_type": "code",
                                "location": "src/feature_flags/service.py:1-26",
                                "commit": "abc",
                            },
                        ],
                        "resolution_plan": {
                            "test": ("tests/test_feature_flags.py tenant-alpha tenant-beta")
                        },
                    }
                },
                "efficiency": {"duration_seconds": 60},
            }
        ),
        encoding="utf-8",
    )

    summary = evaluate_run(config, workspace, manifest)

    assert summary["mean_score"] == 100
    assert (workspace.runs / manifest.run_id / "summary.json").exists()
    assert (workspace.runs / manifest.run_id / "report.md").exists()
    assert "full-clio" in render_comparison([summary])
