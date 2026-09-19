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
    runner.invoke(
        app, ["run", "--config", str(config_path), "--workspace", str(workspace)]
    )

    result = runner.invoke(app, ["report", "--workspace", str(workspace)])

    assert result.exit_code == 2
    assert "Report not found" in result.stderr
