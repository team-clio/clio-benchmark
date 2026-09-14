from pathlib import Path

from clio_benchmark.config import load_config


def test_example_config_accepts_empty_suites() -> None:
    config = load_config(Path("benchmark.example.yaml"))

    assert config.suites == []
    assert sum(config.evaluation.weights.as_dict().values()) == 100


def test_redacted_snapshot_excludes_secret_values(tmp_path: Path) -> None:
    config_path = tmp_path / "benchmark.yaml"
    source = Path("benchmark.example.yaml").read_text(encoding="utf-8")
    source = source.replace(
        "agent: {}\n  server: {}\n\n# 테스트",
        "agent:\n    API_KEY: secret-value\n  server: {}\n\n# 테스트",
    )
    config_path.write_text(source, encoding="utf-8")

    snapshot = load_config(config_path).redacted_snapshot()

    assert snapshot["secret_names"]["agent"] == ["API_KEY"]
    assert "secret-value" not in str(snapshot)
