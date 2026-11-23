import pytest

from faststudio import AuthBackend, AuthenticatedUser, ConfigurationError
from tests._stubs import StubAuthBackend


def test_valid_user() -> None:
    user = AuthenticatedUser(id="1", username="admin", auth_version="v1")
    assert user.auth_version == "v1"


def test_auth_version_is_required() -> None:
    with pytest.raises(TypeError):
        AuthenticatedUser(id="1", username="admin")  # type: ignore[call-arg]  # deliberately missing


@pytest.mark.parametrize("field", ["id", "username", "auth_version"])
@pytest.mark.parametrize("bad", ["", None, 1])
def test_empty_or_non_str_fields_rejected(field: str, bad: object) -> None:
    kwargs: dict[str, object] = {"id": "1", "username": "admin", "auth_version": "v1"}
    kwargs[field] = bad
    with pytest.raises(ConfigurationError, match=field):
        AuthenticatedUser(**kwargs)  # type: ignore[arg-type]  # deliberately wrong type


def test_stub_satisfies_protocol() -> None:
    assert isinstance(StubAuthBackend(), AuthBackend)
