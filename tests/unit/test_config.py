import secrets
from datetime import timedelta
from typing import Any

import pytest

from faststudio import ConfigurationError
from faststudio.config import Settings, normalize_base_url, resolve_settings


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/admin", "/admin"),
        ("/admin/", "/admin"),
        ("/back-office/studio", "/back-office/studio"),
        ("/a_b.c~d", "/a_b.c~d"),
    ],
)
def test_base_url_normalized(raw: str, expected: str) -> None:
    assert normalize_base_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "/",
        "admin",
        "//admin",
        "/\\evil.example",
        "/admin//x",
        "/admin/../x",
        "/./admin",
        "/admin?x=1",
        "/admin#x",
        "/ad min",
        "/admin\n",
        "/admin;x",
        "/admin/<script>",
        "http://evil.example/admin",
        "/%61dmin",
        "/\N{CYRILLIC SMALL LETTER A}dmin",
    ],
)
def test_invalid_base_url_rejected(raw: str) -> None:
    with pytest.raises(ConfigurationError, match="base_url"):
        normalize_base_url(raw)


@pytest.mark.parametrize("raw", [None, b"/admin", 1])
def test_non_str_base_url_rejected(raw: object) -> None:
    with pytest.raises(ConfigurationError, match="base_url must be a str"):
        normalize_base_url(raw)


def _resolve(**overrides: Any) -> Settings:
    kwargs: dict[str, Any] = {
        "secret_key": secrets.token_urlsafe(48),
        "title": "FastStudio",
        "base_url": "/admin",
        "session_max_age": timedelta(hours=8),
        "secure_cookies": True,
        "max_page_size": 100,
        "max_list_offset": 10_000,
        "show_powered_by": True,
    }
    kwargs.update(overrides)
    return resolve_settings(**kwargs)


def test_settings_resolved() -> None:
    settings = _resolve(
        title="  My Admin  ",
        base_url="/studio/",
        session_max_age=timedelta(hours=1),
        max_page_size=50,
        show_powered_by=False,
    )
    assert settings.title == "My Admin"
    assert settings.base_url == "/studio"
    assert settings.api_url == "/studio/api/v1"
    assert settings.session_max_age == timedelta(hours=1)
    assert settings.max_page_size == 50
    assert settings.secure_cookies is True
    assert settings.show_powered_by is False


def test_secret_not_in_repr() -> None:
    key = secrets.token_urlsafe(48)
    settings = _resolve(secret_key=key)
    assert key not in repr(settings)
    assert settings.secret_key == key


@pytest.mark.parametrize("title", ["", "   ", "x" * 101, "Admin\x00", "Ad\u202emin", "tab\tbed"])
def test_invalid_title(title: str) -> None:
    with pytest.raises(ConfigurationError, match="title"):
        _resolve(title=title)


@pytest.mark.parametrize("age", [timedelta(0), timedelta(seconds=-1), timedelta(seconds=59)])
def test_invalid_session_max_age(age: timedelta) -> None:
    with pytest.raises(ConfigurationError, match="session_max_age"):
        _resolve(session_max_age=age)


@pytest.mark.parametrize("size", [0, -5, 1001])
def test_invalid_max_page_size(size: int) -> None:
    with pytest.raises(ConfigurationError, match="max_page_size"):
        _resolve(max_page_size=size)


@pytest.mark.parametrize("offset", [1, 10_000, 10_000_000])
def test_max_list_offset_bounds_accepted(offset: int) -> None:
    assert _resolve(max_list_offset=offset).max_list_offset == offset


@pytest.mark.parametrize("offset", [0, -1, 10_000_001])
def test_invalid_max_list_offset(offset: int) -> None:
    with pytest.raises(ConfigurationError, match="max_list_offset must be between 1 and 10000000"):
        _resolve(max_list_offset=offset)


@pytest.mark.parametrize(
    ("option", "value", "message"),
    [
        ("max_list_offset", "10000", "max_list_offset must be int"),
        ("max_list_offset", True, "max_list_offset must be int"),
        ("title", None, "title must be str"),
        ("title", 1, "title must be str"),
        ("session_max_age", 3600, "session_max_age must be timedelta"),
        ("max_page_size", "100", "max_page_size must be int"),
        ("max_page_size", True, "max_page_size must be int"),
        ("max_page_size", 10.0, "max_page_size must be int"),
        ("secure_cookies", "yes", "secure_cookies must be bool"),
        ("secure_cookies", 1, "secure_cookies must be bool"),
        ("show_powered_by", None, "show_powered_by must be bool"),
        ("secret_key", b"x" * 48, "secret key must be a str"),
        ("base_url", None, "base_url must be a str"),
    ],
)
def test_wrong_option_types_raise_configuration_error(
    option: str, value: object, message: str
) -> None:
    with pytest.raises(ConfigurationError, match=message):
        _resolve(**{option: value})


def test_insecure_cookies_log_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="faststudio"):
        _resolve(secure_cookies=False)
    assert any("secure_cookies=False" in r.getMessage() for r in caplog.records)
    assert all(r.name.startswith("faststudio") for r in caplog.records)


def test_no_insecure_warning_when_startup_fails(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="faststudio"), pytest.raises(ConfigurationError):
        _resolve(secure_cookies=False, secret_key="short")
    assert caplog.records == []


def test_secure_cookies_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="faststudio"):
        _resolve(secure_cookies=True)
    assert caplog.records == []
