"""scripts/build_common_passwords.py fails cleanly offline (A5 follow-ups)."""

from __future__ import annotations

import hashlib
import http.client
import importlib.util
import urllib.error
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_common_passwords", ROOT / "scripts" / "build_common_passwords.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    return module


class _Response:
    def __init__(self, body: bytes | Exception) -> None:
        self.body = body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


def _serve(monkeypatch: pytest.MonkeyPatch, script: ModuleType, *bodies: Any) -> list[int]:
    calls: list[int] = []
    queue = list(bodies)

    def urlopen(_url: str, timeout: float) -> _Response:
        del timeout
        calls.append(1)
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, urllib.error.URLError):
            raise item
        return _Response(item)

    monkeypatch.setattr(script.urllib.request, "urlopen", urlopen)
    return calls


@pytest.mark.parametrize(
    "failure",
    [http.client.IncompleteRead(b"partial"), urllib.error.URLError("down"), ConnectionResetError()],
)
def test_network_failures_are_retried_then_reported(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    calls = _serve(monkeypatch, script, failure)
    with pytest.raises(SystemExit, match="after 3 attempts"):
        script.download()
    assert len(calls) == script.ATTEMPTS


def test_a_later_attempt_may_succeed(script: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    body = b"123456 1\n"
    monkeypatch.setattr(script, "SOURCE_SHA256", hashlib.sha256(body).hexdigest())
    calls = _serve(monkeypatch, script, http.client.IncompleteRead(b""), body)
    assert script.download() == body
    assert len(calls) == 2


def test_a_wrong_checksum_is_refused(script: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, script, b"tampered 1\n")
    with pytest.raises(SystemExit, match="checksum mismatch"):
        script.download()


def test_an_oversized_download_is_refused(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve(monkeypatch, script, b"x" * (script.MAX_SOURCE_BYTES + 1))
    with pytest.raises(SystemExit, match="larger than expected"):
        script.download()


def test_unknown_arguments_never_rewrite_the_file(script: ModuleType) -> None:
    with pytest.raises(SystemExit) as exited:
        script.main(["--chek"])
    assert exited.value.code == 2
