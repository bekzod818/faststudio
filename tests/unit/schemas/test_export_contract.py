"""Committed JSON Schema stays in sync with the Pydantic contract (ADR-0007)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "export_contract.py"


@pytest.fixture(scope="module")
def exporter() -> ModuleType:
    spec = importlib.util.spec_from_file_location("export_contract", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_schema_is_up_to_date(exporter: ModuleType) -> None:
    committed = exporter.OUTPUT.read_text(encoding="utf-8")
    assert committed == exporter.render(exporter.build_schema()), (
        "contract.schema.json is stale: run `uv run python scripts/export_contract.py`"
    )


def test_output_is_deterministic(exporter: ModuleType) -> None:
    assert exporter.render(exporter.build_schema()) == exporter.render(exporter.build_schema())


def test_schema_exposes_every_top_level_shape(exporter: ModuleType) -> None:
    schema = exporter.build_schema()
    assert set(schema["properties"]) == {
        "ChoicesResponse",
        "ErrorResponse",
        "ListResponse",
        "LoginRequest",
        "MetaResponse",
        "Row",
        "SpaConfig",
        "UserResponse",
    }
    for name in ("FieldMeta", "ModelMeta", "RelationMeta", "FilterMeta", "ErrorBody"):
        assert name in schema["$defs"]


def test_schema_documents_closed_objects_and_enums(exporter: ModuleType) -> None:
    defs = exporter.build_schema()["$defs"]
    assert defs["FieldMeta"]["additionalProperties"] is False
    assert defs["FieldMeta"]["properties"]["type"] == {"$ref": "#/$defs/FieldType"}
    assert "unsupported" in defs["FieldType"]["enum"]
    assert defs["ErrorBody"]["properties"]["code"] == {"$ref": "#/$defs/ErrorCode"}
    assert defs["MetaResponse"]["properties"]["schema_version"]["const"] == "1"
    assert defs["LoginRequest"]["properties"]["password"]["maxLength"] == 1024


def test_schema_is_valid_json(exporter: ModuleType) -> None:
    json.loads(exporter.OUTPUT.read_text(encoding="utf-8"))


def test_check_mode(exporter: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "contract.schema.json"
    monkeypatch.setattr(exporter, "OUTPUT", target)
    assert exporter.main(["--check"]) == 1  # missing
    assert exporter.main([]) == 0
    assert exporter.main(["--check"]) == 0
    target.write_text("{}\n", encoding="utf-8")
    assert exporter.main(["--check"]) == 1  # stale


def test_usage(exporter: ModuleType) -> None:
    assert exporter.main(["--bogus"]) == 2


def test_property_titles_are_dropped(exporter: ModuleType) -> None:
    text = exporter.render(exporter.build_schema())
    assert '"title": "Label"' not in text
    assert '"title": "FastStudioContract"' in text


def test_fields_named_title_are_kept(exporter: ModuleType) -> None:
    defs = exporter.build_schema()["$defs"]
    assert "title" in defs["MetaResponse"]["properties"]
    assert "title" in defs["MetaResponse"]["required"]
    assert "title" not in defs["MetaResponse"]["properties"]["title"]


def test_no_named_enum_is_left_inline(exporter: ModuleType) -> None:
    schema = exporter.build_schema()
    defs = dict(schema["$defs"])
    for name in exporter.NAMED_ENUMS:
        defs.pop(name)
    assert exporter._inline_named_enums(defs) == []
    relation = schema["$defs"]["RelationMeta"]["properties"]["value_type"]
    assert relation == {"$ref": "#/$defs/FieldType"}


def test_literal_values_are_not_rewritten(exporter: ModuleType) -> None:
    node = {"title": "T", "default": {"title": "kept"}, "const": "title", "properties": {}}
    assert exporter._tidy(node) == {
        "default": {"title": "kept"},
        "const": "title",
        "properties": {},
    }
