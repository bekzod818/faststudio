"""The bundled common-password list keeps its provenance (plan amendment A5, §8)."""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
from importlib import resources
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
DATA = resources.files("faststudio.auth") / "data"


def _build_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_common_passwords", ROOT / "scripts" / "build_common_passwords.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_notice_names_source_version_and_licence() -> None:
    script = _build_script()
    notice = (DATA / "NOTICE").read_text(encoding="utf-8")
    assert "https://github.com/dropbox/zxcvbn" in notice
    assert f"commit {script.COMMIT}" in notice
    assert script.SOURCE_SHA256 in notice
    assert "Licence:  MIT" in notice
    assert "Copyright (c) 2012-2016 Dan Wheeler and Dropbox, Inc." in notice
    assert "Permission is hereby granted, free of charge" in notice
    assert f"{script.TOP:,}".replace(",", " ") in notice  # "20 000 most frequent entries"


def test_the_repository_notice_repeats_it() -> None:
    notice = (DATA / "NOTICE").read_text(encoding="utf-8")
    third_party = (ROOT / "THIRD_PARTY_NOTICES").read_text(encoding="utf-8")
    bundled_part = notice[notice.index("common-passwords.txt.gz") :]
    assert bundled_part in third_party


def test_the_list_is_the_documented_one() -> None:
    """Deterministic gzip of passwords only: one per line, no counts, no names."""
    raw = (DATA / "common-passwords.txt.gz").read_bytes()
    assert raw[4:8] == b"\x00\x00\x00\x00"  # gzip mtime 0: reproducible
    lines = gzip.decompress(raw).decode("utf-8").splitlines()
    assert len(lines) == _build_script().TOP
    assert lines[:3] == ["123456", "password", "12345678"]
    assert all(line and " " not in line and "\t" not in line for line in lines)
    assert len(set(lines)) == len(lines)
    # The exact committed bytes (offline); --check re-derives the text from the source.
    assert hashlib.sha256(raw).hexdigest() == _build_script().OUTPUT_SHA256


def test_importing_faststudio_reads_no_list() -> None:
    """The bundled list is read on first use, never at import (A5)."""
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    code = (
        "import faststudio, faststudio.contrib.auth\n"
        "from faststudio.auth.validators import _bundled_passwords\n"
        "assert _bundled_passwords.cache_info().currsize == 0\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False, timeout=60
    )
    assert result.returncode == 0, result.stderr
