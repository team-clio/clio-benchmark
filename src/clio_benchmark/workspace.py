"""Workspace layout and atomic manifest persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from clio_benchmark.config import BenchmarkConfig
from clio_benchmark.errors import WorkspaceError
from clio_benchmark.manifest import RunManifest


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.sources = self.root / "sources"
        self.suites = self.root / "suites"
        self.runs = self.root / "runs"

    def initialize(self) -> None:
        for directory in (self.root, self.sources, self.suites, self.runs):
            directory.mkdir(parents=True, exist_ok=True)

    def create_run(self, config: BenchmarkConfig) -> RunManifest:
        self.initialize()
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"{timestamp}-{uuid4().hex[:8]}"
        manifest = RunManifest(run_id=run_id, config=config.redacted_snapshot())
        self.save_manifest(manifest)
        return manifest

    def save_manifest(self, manifest: RunManifest) -> Path:
        run_dir = self.runs / manifest.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        destination = run_dir / "manifest.json"
        temporary = run_dir / ".manifest.json.tmp"
        payload = manifest.model_dump_json(indent=2)
        temporary.write_text(f"{payload}\n", encoding="utf-8")
        temporary.replace(destination)
        return destination

    def load_manifest(self, run_id: str) -> RunManifest:
        path = self.runs / run_id / "manifest.json"
        try:
            return RunManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise WorkspaceError(f"Run not found: {run_id}") from exc
        except (ValidationError, json.JSONDecodeError) as exc:
            raise WorkspaceError(f"Invalid manifest: {path}") from exc

    def latest_manifest(self) -> RunManifest | None:
        if not self.runs.exists():
            return None
        manifests = sorted(self.runs.glob("*/manifest.json"), reverse=True)
        return self.load_manifest(manifests[0].parent.name) if manifests else None

    def write_run_artifact(self, run_id: str, relative_path: Path, payload: object) -> Path:
        run_dir = (self.runs / run_id).resolve()
        destination = (run_dir / relative_path).resolve()
        if not destination.is_relative_to(run_dir):
            raise WorkspaceError(f"Artifact path escapes run directory: {relative_path}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        temporary.write_text(
            f"{json.dumps(payload, indent=2, ensure_ascii=False, default=str)}\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
        return destination

    def write_run_text(self, run_id: str, relative_path: Path, content: str) -> Path:
        run_dir = (self.runs / run_id).resolve()
        destination = (run_dir / relative_path).resolve()
        if not destination.is_relative_to(run_dir):
            raise WorkspaceError(f"Artifact path escapes run directory: {relative_path}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(destination)
        return destination
