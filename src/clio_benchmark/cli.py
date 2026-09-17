"""Command-line entry point for Clio Benchmark."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from clio_benchmark.clio_client import ClioClient
from clio_benchmark.config import BenchmarkConfig, load_config
from clio_benchmark.errors import BenchmarkError
from clio_benchmark.manifest import RunStatus
from clio_benchmark.run_evaluation import (
    evaluate_run,
    load_summary,
    render_comparison,
    render_report,
)
from clio_benchmark.runner import BenchmarkRunner
from clio_benchmark.workspace import Workspace

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)


@app.command()
def setup(
    config: Annotated[Path, typer.Option(exists=False)] = Path("benchmark.local.yaml"),
    workspace: Annotated[Path, typer.Option()] = Path(".benchmark"),
) -> None:
    """Validate configuration and prepare the local benchmark workspace."""
    benchmark_config = _load_or_exit(config)
    local_workspace = Workspace(workspace)
    local_workspace.initialize()
    typer.echo(
        f"Workspace ready: {local_workspace.root} "
        f"({len(benchmark_config.suites)} suite(s) configured)"
    )


@app.command()
def run(
    config: Annotated[Path, typer.Option(exists=False)] = Path("benchmark.local.yaml"),
    workspace: Annotated[Path, typer.Option()] = Path(".benchmark"),
) -> None:
    """Execute configured benchmark suites through Clio Server."""
    benchmark_config = _load_or_exit(config)
    local_workspace = Workspace(workspace)
    manifest = local_workspace.create_run(benchmark_config)
    if not benchmark_config.suites:
        manifest.transition(RunStatus.COMPLETED)
        local_workspace.save_manifest(manifest)
        typer.echo(f"Run {manifest.run_id} completed: no suites configured")
        return

    manifest.transition(RunStatus.RUNNING)
    local_workspace.save_manifest(manifest)
    client = ClioClient(str(benchmark_config.runtime.server_url))
    try:
        manifest.case_count = BenchmarkRunner(benchmark_config, local_workspace, client).execute(
            manifest
        )
    except KeyboardInterrupt as exc:
        manifest.transition(RunStatus.CANCELLED, error="Interrupted by user")
        local_workspace.save_manifest(manifest)
        typer.echo(f"Run {manifest.run_id} cancelled", err=True)
        raise typer.Exit(code=130) from exc
    except BenchmarkError as exc:
        manifest.transition(RunStatus.FAILED, error=str(exc))
        local_workspace.save_manifest(manifest)
        typer.echo(f"Run {manifest.run_id} failed: {manifest.error}", err=True)
        raise typer.Exit(code=2) from exc
    finally:
        client.close()
    manifest.transition(RunStatus.COMPLETED)
    local_workspace.save_manifest(manifest)
    typer.echo(f"Run {manifest.run_id} completed: {manifest.case_count} case(s)")
    if any(suite.oracle for suite in benchmark_config.suites):
        try:
            summary = evaluate_run(benchmark_config, local_workspace, manifest)
        except BenchmarkError as exc:
            typer.echo(f"Evaluation failed: {exc}", err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(render_report(summary))


@app.command("evaluate")
def evaluate_command(
    run_id: Annotated[str, typer.Argument()],
    config: Annotated[Path, typer.Option(exists=False)] = Path("benchmark.local.yaml"),
    workspace: Annotated[Path, typer.Option()] = Path(".benchmark"),
) -> None:
    """Evaluate a persisted run without executing Clio again."""
    benchmark_config = _load_or_exit(config)
    local_workspace = Workspace(workspace)
    try:
        manifest = local_workspace.load_manifest(run_id)
        summary = evaluate_run(benchmark_config, local_workspace, manifest)
    except BenchmarkError as exc:
        _exit_with_error(exc)
    typer.echo(render_report(summary))


@app.command("compare")
def compare_command(
    run_ids: Annotated[list[str], typer.Argument()],
    workspace: Annotated[Path, typer.Option()] = Path(".benchmark"),
) -> None:
    """Compare evaluated runs by profile, quality and duration."""
    local_workspace = Workspace(workspace)
    try:
        summaries = [load_summary(local_workspace, run_id) for run_id in run_ids]
    except BenchmarkError as exc:
        _exit_with_error(exc)
    typer.echo(render_comparison(summaries))


@app.command()
def status(
    workspace: Annotated[Path, typer.Option()] = Path(".benchmark"),
    run_id: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Print the latest or selected run manifest as JSON."""
    local_workspace = Workspace(workspace)
    try:
        manifest = (
            local_workspace.load_manifest(run_id) if run_id else local_workspace.latest_manifest()
        )
    except BenchmarkError as exc:
        _exit_with_error(exc)
    if manifest is None:
        typer.echo("No benchmark runs found")
        return
    typer.echo(json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=False))


def _load_or_exit(path: Path) -> BenchmarkConfig:
    try:
        return load_config(path)
    except BenchmarkError as exc:
        _exit_with_error(exc)


def _exit_with_error(error: Exception) -> None:
    typer.echo(f"Error: {error}", err=True)
    raise typer.Exit(code=2)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
