from pathlib import Path

from typer.testing import CliRunner

from clio_benchmark.cli import app

runner = CliRunner()


def test_empty_suite_run_completes_and_can_be_read(tmp_path: Path) -> None:
    workspace = tmp_path / ".benchmark"

    run_result = runner.invoke(
        app,
        [
            "run",
            "--config",
            "benchmark.example.yaml",
            "--workspace",
            str(workspace),
        ],
    )
    status_result = runner.invoke(app, ["status", "--workspace", str(workspace)])

    assert run_result.exit_code == 0
    assert "no suites configured" in run_result.stdout
    assert status_result.exit_code == 0
    assert '"status": "completed"' in status_result.stdout
