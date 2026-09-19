"""Application-level errors exposed by the CLI."""


class BenchmarkError(Exception):
    """Base error for expected benchmark failures."""


class ConfigurationError(BenchmarkError):
    """Raised when a benchmark configuration is invalid."""


class WorkspaceError(BenchmarkError):
    """Raised when workspace state is missing or inconsistent."""


class SuiteError(BenchmarkError):
    """Raised when a benchmark suite cannot be prepared or parsed."""


class ClioApiError(BenchmarkError):
    """Raised when Clio Server cannot complete a benchmark operation."""


class BenchmarkTimeout(ClioApiError):
    """Raised when an external benchmark operation exceeds its deadline."""


class ClioAnalysisError(BenchmarkError):
    """Raised when Clio finishes without producing an evaluable analysis result."""
