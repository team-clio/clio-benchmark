from pathlib import Path

from clio_benchmark.config import load_config
from clio_benchmark.manifest import RunStatus
from clio_benchmark.workspace import Workspace


def test_manifest_round_trip_uses_redacted_config(tmp_path: Path) -> None:
    config = load_config(Path("benchmark.example.yaml"))
    workspace = Workspace(tmp_path / ".benchmark")

    manifest = workspace.create_run(config)
    manifest.transition(RunStatus.COMPLETED)
    path = workspace.save_manifest(manifest)
    restored = workspace.load_manifest(manifest.run_id)

    assert path.exists()
    assert restored.status is RunStatus.COMPLETED
    assert restored.config["secret_names"] == {"agent": [], "server": []}


def test_latest_manifest_is_none_before_first_run(tmp_path: Path) -> None:
    assert Workspace(tmp_path / ".benchmark").latest_manifest() is None
