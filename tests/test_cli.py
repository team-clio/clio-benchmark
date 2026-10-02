from pathlib import Path

import yaml
from typer.testing import CliRunner

from clio_benchmark.cli import app

runner = CliRunner()


def test_empty_suite_run_completes_and_can_be_read(tmp_path: Path) -> None:
    workspace = tmp_path / ".benchmark"
    config_path = tmp_path / "benchmark.yaml"
    config = yaml.safe_load(Path("benchmark.example.yaml").read_text(encoding="utf-8"))
    config["suites"] = []
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    run_result = runner.invoke(
        app,
        [
            "run",
            "--config",
            str(config_path),
            "--workspace",
            str(workspace),
        ],
    )
    status_result = runner.invoke(app, ["status", "--workspace", str(workspace)])

    assert run_result.exit_code == 0
    assert "no suites configured" in run_result.stdout
    assert status_result.exit_code == 0
    assert '"status": "completed"' in status_result.stdout


def test_report_exits_when_run_has_no_generated_report(tmp_path: Path) -> None:
    workspace = tmp_path / ".benchmark"
    config_path = tmp_path / "benchmark.yaml"
    config = yaml.safe_load(Path("benchmark.example.yaml").read_text(encoding="utf-8"))
    config["suites"] = []
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    runner.invoke(app, ["run", "--config", str(config_path), "--workspace", str(workspace)])

    result = runner.invoke(app, ["report", "--workspace", str(workspace)])

    assert result.exit_code == 2
    assert "Report not found" in result.stderr


def test_logs_are_collected_on_success_failure_and_cancel(monkeypatch, tmp_path: Path) -> None:
    import json
    from types import SimpleNamespace

    import clio_benchmark.cli as cli
    from clio_benchmark.agent_client import Boundary
    from clio_benchmark.errors import BenchmarkError

    collected = []

    class Agent:
        def __init__(self, *args):
            pass

        def boundary(self):
            return Boundary(sequence=0, at="start", store_id="test")

        def collect(self, manifest, workspace, start):
            collected.append(manifest.status)
            manifest.tool_log_status = "completed"
            workspace.save_manifest(manifest)

        def close(self):
            pass

    class Benchmark:
        error = None

        def __init__(self, *args):
            pass

        def execute(self, manifest):
            if self.error:
                raise self.error
            return SimpleNamespace(total_cases=1, completed_cases=1, failed_cases=0)

    monkeypatch.setattr(cli, "AgentLogClient", Agent)
    monkeypatch.setattr(cli, "BenchmarkRunner", Benchmark)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(Path("benchmark.example.yaml").read_text())
    for index, (error, code, status) in enumerate(
        [
            (None, 0, "completed"),
            (BenchmarkError("original error"), 2, "failed"),
            (KeyboardInterrupt(), 130, "cancelled"),
        ]
    ):
        Benchmark.error = error
        workspace = tmp_path / str(index)
        result = runner.invoke(
            app, ["run", "--config", str(config_path), "--workspace", str(workspace)]
        )
        assert result.exit_code == code, result.output
        manifest = json.loads(next((workspace / "runs").glob("*/manifest.json")).read_text())
        assert manifest["status"] == status
        assert manifest["tool_log_status"] == "completed"
    assert len(collected) == 3


def test_collection_failure_does_not_replace_original_run_error(monkeypatch, tmp_path):
    import json

    import clio_benchmark.cli as cli
    from clio_benchmark.agent_client import Boundary, LogCollectionError
    from clio_benchmark.errors import BenchmarkError

    class Agent:
        def __init__(self, *args):
            pass

        def boundary(self):
            return Boundary(sequence=0, at="start", store_id="test")

        def collect(self, manifest, workspace, start):
            manifest.tool_log_status = "failed"
            manifest.tool_log_error = "collection failed"
            workspace.save_manifest(manifest)
            raise LogCollectionError("collection failed")

        def close(self):
            pass

    class Benchmark:
        def __init__(self, *args):
            pass

        def execute(self, manifest):
            raise BenchmarkError("original execution error")

    monkeypatch.setattr(cli, "AgentLogClient", Agent)
    monkeypatch.setattr(cli, "BenchmarkRunner", Benchmark)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(Path("benchmark.example.yaml").read_text())
    workspace = tmp_path / "workspace"
    result = runner.invoke(
        app,
        [
            "run",
            "--config",
            str(config_path),
            "--workspace",
            str(workspace),
        ],
    )
    manifest = json.loads(next((workspace / "runs").glob("*/manifest.json")).read_text())
    assert result.exit_code == 2
    assert manifest["status"] == "failed"
    assert manifest["error"] == "original execution error"
    assert manifest["tool_log_error"] == "collection failed"
