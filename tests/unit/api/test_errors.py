"""Unit tests for contract error helpers (`faststudio.api.errors`)."""

from __future__ import annotations

from faststudio.api.errors import validation_issues


def test_validation_issues_handles_scalar_loc() -> None:
    issues = validation_issues([{"loc": "body", "msg": "m", "type": "t", "input": "SECRET"}])
    assert issues[0].loc == ["body"]
    assert "SECRET" not in issues[0].model_dump_json()


def test_validation_issues_keeps_integer_loc_parts() -> None:
    issues = validation_issues([{"loc": ("body", "items", 3), "msg": "m", "type": "t"}])
    assert issues[0].loc == ["body", "items", 3]
