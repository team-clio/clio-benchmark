from pathlib import Path

import yaml

from clio_benchmark.config import load_config


def test_example_config_registers_first_fixture() -> None:
    config = load_config(Path("benchmark.example.yaml"))

    assert [suite.name for suite in config.suites] == ["feature-flags"]
    assert sum(config.evaluation.weights.as_dict().values()) == 100


def test_redacted_snapshot_excludes_secret_values(tmp_path: Path) -> None:
    config_path = tmp_path / "benchmark.yaml"
    source = yaml.safe_load(Path("benchmark.example.yaml").read_text(encoding="utf-8"))
    source["secrets"]["agent"]["API_KEY"] = "secret-value"
    config_path.write_text(yaml.safe_dump(source), encoding="utf-8")

    snapshot = load_config(config_path).redacted_snapshot()

    assert snapshot["secret_names"]["agent"] == ["API_KEY"]
    assert "secret-value" not in str(snapshot)
