"""Application-level errors exposed by the CLI."""


class BenchmarkError(Exception):
    """Base error for expected benchmark failures."""


class ConfigurationError(BenchmarkError):
    """Raised when a benchmark configuration is invalid."""


class WorkspaceError(BenchmarkError):
    """Raised when workspace state is missing or inconsistent."""
