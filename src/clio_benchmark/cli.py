"""Command-line entry point for Clio Benchmark."""

from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path
from typing import Annotated

import typer

from clio_benchmark.agent_client import AgentLogClient, LogCollectionError
from clio_benchmark.clio_client import ClioClient
from clio_benchmark.config import BenchmarkConfig, load_config
from clio_benchmark.errors import BenchmarkError
from clio_benchmark.html_report import generate_html_report
from clio_benchmark.manifest import RunManifest, RunStatus
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
        manifest.tool_log_status = "skipped"
        manifest.transition(RunStatus.COMPLETED)
        local_workspace.save_manifest(manifest)
        _generate_report(benchmark_config, local_workspace, manifest)
        typer.echo(f"Run {manifest.run_id} completed: no suites configured")
        return

    manifest.transition(RunStatus.RUNNING)
    local_workspace.save_manifest(manifest)
    client = ClioClient(str(benchmark_config.runtime.server_url))
    agent = AgentLogClient(
        str(benchmark_config.runtime.agent_url),
        benchmark_config.runtime.tool_log_timeout_seconds,
    )
    start = None
    try:
        start = agent.boundary()
        manifest.execution_started_at = start.at
        local_workspace.save_manifest(manifest)
        summary = BenchmarkRunner(benchmark_config, local_workspace, client).execute(manifest)
        manifest.case_count = summary.total_cases
        manifest.completed_case_count = summary.completed_cases
        manifest.failed_case_count = summary.failed_cases
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
    except Exception as exc:
        manifest.transition(RunStatus.FAILED, error=str(exc))
        local_workspace.save_manifest(manifest)
        typer.echo(f"Run {manifest.run_id} failed: {manifest.error}", err=True)
        raise typer.Exit(code=2) from exc
    finally:
        if start is not None:
            try:
                agent.collect(manifest, local_workspace, start)
            except LogCollectionError as exc:
                typer.echo(str(exc), err=True)
        else:
            manifest.tool_log_status = "failed"
            manifest.tool_log_error = manifest.error
            local_workspace.save_manifest(manifest)
        agent.close()
        client.close()
        # 기존 오류·취소는 유지하고 정상 경로만 최종 상태로 전환한다.
        if manifest.status is RunStatus.RUNNING:
            if manifest.tool_log_status == "failed":
                manifest.transition(RunStatus.COMPLETED_WITH_ERRORS, error=manifest.tool_log_error)
            else:
                final_status = (
                    RunStatus.COMPLETED_WITH_ERRORS
                    if manifest.failed_case_count
                    else RunStatus.COMPLETED
                )
                manifest.transition(final_status)
        local_workspace.save_manifest(manifest)
        _generate_report(benchmark_config, local_workspace, manifest)
    if manifest.tool_log_status == "failed":
        raise typer.Exit(code=2)
    typer.echo(f"Run {manifest.run_id} completed: {manifest.case_count} case(s)")


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


@app.command()
def report(
    workspace: Annotated[Path, typer.Option()] = Path(".benchmark"),
    run_id: Annotated[str | None, typer.Option()] = None,
    output_format: Annotated[str, typer.Option("--format")] = "markdown",
    regenerate: Annotated[bool, typer.Option()] = False,
    config: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Print Markdown or the HTML path; optionally regenerate HTML from saved artifacts."""
    if output_format not in {"markdown", "html"}:
        _exit_with_error(ValueError("--format must be markdown or html"))
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
    if regenerate:
        if config is not None:
            benchmark_config = _load_or_exit(config)
        else:
            fields = {
                key: value
                for key, value in manifest.config.items()
                if key in BenchmarkConfig.model_fields
            }
            benchmark_config = BenchmarkConfig.model_validate(fields)
        try:
            generate_html_report(benchmark_config, local_workspace, manifest)
        except Exception as exc:
            _exit_with_error(exc)
    if output_format == "html":
        html_path = local_workspace.runs / manifest.run_id / "report.html"
        if not html_path.exists():
            _exit_with_error(ValueError(f"HTML report not found for run: {manifest.run_id}"))
        typer.echo(str(html_path))
        return
    report_path = local_workspace.runs / manifest.run_id / "report.md"
    if not report_path.exists():
        typer.echo(f"Report not found for run: {manifest.run_id}", err=True)
        raise typer.Exit(code=2)
    typer.echo(report_path.read_text(encoding="utf-8"))


def _load_or_exit(path: Path) -> BenchmarkConfig:
    try:
        return load_config(path)
    except BenchmarkError as exc:
        _exit_with_error(exc)


def _generate_report(config: BenchmarkConfig, workspace: Workspace, manifest: RunManifest) -> None:
    """보고서 오류는 실행 오류·종료 코드를 덮어쓰지 않는다."""
    try:
        path = generate_html_report(config, workspace, manifest)
        if path is not None:
            typer.echo(f"HTML report: {path}")
    except (Exception, KeyboardInterrupt) as exc:
        typer.echo(f"HTML report generation failed: {exc}", err=True)
        with suppress(Exception):
            workspace.write_run_artifact(
                manifest.run_id,
                Path("report-generation.json"),
                {"status": "failed", "error": str(exc)},
            )


def _exit_with_error(error: Exception) -> None:
    typer.echo(f"Error: {error}", err=True)
    raise typer.Exit(code=2)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
