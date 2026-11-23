"""Exception hierarchy for FastStudio."""


class FastStudioError(Exception):
    """Base class for every error raised by FastStudio."""


class ConfigurationError(FastStudioError):
    """Raised when FastStudio or a host-provided component is misconfigured.

    Usually raised at startup by ``Admin(...)`` and ``register()``. It can also
    be raised at request time when a host-provided component misbehaves, e.g.
    a custom ``AuthBackend`` returning an ``AuthenticatedUser`` with an empty
    ``auth_version``; the API layer turns that into a logged 500.
    """
