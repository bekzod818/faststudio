"""Exception hierarchy for FastStudio."""


class FastStudioError(Exception):
    """Base class for every error raised by FastStudio."""


class ConfigurationError(FastStudioError):
    """Raised at startup when FastStudio is configured incorrectly."""
