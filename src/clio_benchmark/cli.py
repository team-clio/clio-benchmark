"""Command-line entry point for Clio Benchmark."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from clio_benchmark.config import BenchmarkConfig, load_config
from clio_benchmark.errors import BenchmarkError
from clio_benchmark.manifest import RunStatus
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
    """Create a run record; empty suite configurations complete without work."""
    benchmark_config = _load_or_exit(config)
    local_workspace = Workspace(workspace)
    manifest = local_workspace.create_run(benchmark_config)
    if not benchmark_config.suites:
        manifest.transition(RunStatus.COMPLETED)
        local_workspace.save_manifest(manifest)
        typer.echo(f"Run {manifest.run_id} completed: no suites configured")
        return

    manifest.transition(
        RunStatus.FAILED,
        error="Suite execution is not available until the Clio API adapter is configured",
    )
    local_workspace.save_manifest(manifest)
    typer.echo(f"Run {manifest.run_id} failed: {manifest.error}", err=True)
    raise typer.Exit(code=2)


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
