"""Build the bundled common-password list (plan amendment A5).

    uv run python scripts/build_common_passwords.py          # (re)write the file
    uv run python scripts/build_common_passwords.py --check  # verify it

Source: Dropbox zxcvbn ``data/passwords.txt`` at a pinned commit (MIT, see
src/faststudio/auth/data/NOTICE). The download is verified against a pinned
SHA-256 before anything is written. The output keeps the first `TOP` entries
(the file is ordered by frequency), one password per line, and is a
byte-for-byte reproducible gzip (no timestamp, no file name).
"""

from __future__ import annotations

import gzip
import hashlib
import io
import sys
import urllib.request
from pathlib import Path

COMMIT = "67c4ece9efc40c9d0a1d7d995b2b22a91be500c2"
URL = f"https://raw.githubusercontent.com/dropbox/zxcvbn/{COMMIT}/data/passwords.txt"
SOURCE_SHA256 = "6313cc5ef683a0461416318ee3b16f3d771a3cd10ea2aae54571d27ff95d951f"
TOP = 20_000
OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "faststudio"
    / "auth"
    / "data"
    / "common-passwords.txt.gz"
)


def download() -> bytes:
    """Fetch the pinned source file and verify its checksum."""
    with urllib.request.urlopen(URL, timeout=60) as response:
        data: bytes = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SOURCE_SHA256:
        msg = f"checksum mismatch for {URL}: {digest} != {SOURCE_SHA256}"
        raise SystemExit(msg)
    return data


def build(source: bytes) -> bytes:
    """Return the gzip of the first `TOP` passwords, one per line."""
    passwords: list[str] = []
    seen: set[str] = set()
    for line in source.decode("utf-8").splitlines():
        fields = line.split()
        if not fields:
            continue
        password = fields[0]
        if password not in seen:
            seen.add(password)
            passwords.append(password)
        if len(passwords) == TOP:
            break
    if len(passwords) != TOP:
        msg = f"expected {TOP} passwords, found {len(passwords)}"
        raise SystemExit(msg)
    text = "\n".join(passwords) + "\n"
    buffer = io.BytesIO()
    # mtime=0 and no file name: the same input always gives the same bytes.
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0, compresslevel=9) as out:
        out.write(text.encode("utf-8"))
    return buffer.getvalue()


def main(argv: list[str]) -> int:
    """Write the list, or with ``--check`` compare it with a fresh build."""
    expected = build(download())
    if argv == ["--check"]:
        if OUTPUT.read_bytes() != expected:
            print(f"ERROR: {OUTPUT} does not match a fresh build from {URL}")
            return 1
        print(f"OK: {OUTPUT.name} matches zxcvbn {COMMIT[:12]} (top {TOP})")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(expected)
    print(f"wrote {OUTPUT} ({len(expected)} bytes, top {TOP} of zxcvbn {COMMIT[:12]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
