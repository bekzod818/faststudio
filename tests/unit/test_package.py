import re

import faststudio
from faststudio import ConfigurationError, FastStudioError


def test_version_is_pep440() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+((a|b|rc)\d+)?(\.dev\d+)?", faststudio.__version__)


def test_configuration_error_is_faststudio_error() -> None:
    assert issubclass(ConfigurationError, FastStudioError)


def test_public_api_is_explicit() -> None:
    assert sorted(faststudio.__all__) == [
        "Admin",
        "AuthBackend",
        "AuthenticatedUser",
        "ConfigurationError",
        "FastStudioError",
        "__version__",
    ]
