"""Build the bundled common-password list (plan amendment A5).

    uv run python scripts/build_common_passwords.py          # (re)write the file
    uv run python scripts/build_common_passwords.py --check  # verify it

Source: Dropbox zxcvbn ``data/passwords.txt`` at a pinned commit (MIT, see
src/faststudio/auth/data/NOTICE). The download is verified against a pinned
SHA-256 before anything is written. The output keeps the first `TOP` entries
(the file is ordered by frequency), one password per line, as a gzip with no
timestamp and no file name.

``--check`` compares the *text* with a fresh build, so it passes with any
zlib (zlib-ng compresses the same text into different bytes). The exact
committed bytes are pinned by `OUTPUT_SHA256` and checked offline by
tests/unit/test_third_party_notices.py.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import http.client
import io
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

COMMIT = "67c4ece9efc40c9d0a1d7d995b2b22a91be500c2"
URL = f"https://raw.githubusercontent.com/dropbox/zxcvbn/{COMMIT}/data/passwords.txt"
SOURCE_SHA256 = "6313cc5ef683a0461416318ee3b16f3d771a3cd10ea2aae54571d27ff95d951f"
#: SHA-256 of the committed gzip (built with stock zlib).
OUTPUT_SHA256 = "aedb63ea8cb64411f1726f86097fcd1b0e3fb24bb7ad7bdea585c1229deb7dc8"
TOP = 20_000
MAX_SOURCE_BYTES = 2_000_000  # the source is about 0.6 MB
ATTEMPTS = 3
OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "faststudio"
    / "auth"
    / "data"
    / "common-passwords.txt.gz"
)


def download() -> bytes:
    """Fetch the pinned source file (a few attempts) and verify its checksum."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(URL, timeout=60) as response:
                data: bytes = response.read(MAX_SOURCE_BYTES + 1)
            break
        # URLError covers HTTP errors; IncompleteRead and OSError cover a
        # connection dropped mid-body.
        except (http.client.HTTPException, OSError) as exc:  # URLError is an OSError
            if attempt == ATTEMPTS:
                msg = f"cannot download {URL} after {ATTEMPTS} attempts ({exc})"
                raise SystemExit(msg) from None
            time.sleep(2**attempt)
    if len(data) > MAX_SOURCE_BYTES:
        msg = f"{URL} is larger than expected"
        raise SystemExit(msg)
    digest = hashlib.sha256(data).hexdigest()
    if digest != SOURCE_SHA256:
        msg = f"checksum mismatch for {URL}: {digest} != {SOURCE_SHA256}"
        raise SystemExit(msg)
    return data


def build(source: bytes) -> str:
    """Return the first `TOP` distinct passwords, one per line."""
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
    return "\n".join(passwords) + "\n"


def compress(text: str) -> bytes:
    """Gzip `text` without timestamp or file name (same zlib, same bytes)."""
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0, compresslevel=9) as out:
        out.write(text.encode("utf-8"))
    return buffer.getvalue()


def main(argv: list[str]) -> int:
    """Write the list, or with ``--check`` compare it with a fresh build."""
    parser = argparse.ArgumentParser(
        prog="build_common_passwords.py", description=__doc__, allow_abbrev=False
    )
    parser.add_argument(
        "--check", action="store_true", help="verify the committed list; write nothing"
    )
    args = parser.parse_args(argv)
    expected = build(download())
    if args.check:
        if gzip.decompress(OUTPUT.read_bytes()).decode("utf-8") != expected:
            print(f"ERROR: {OUTPUT} does not match a fresh build from {URL}")
            return 1
        print(f"OK: {OUTPUT.name} matches zxcvbn {COMMIT[:12]} (top {TOP})")
        return 0
    data = compress(expected)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    note = "" if digest == OUTPUT_SHA256 else f"; update OUTPUT_SHA256 to {digest}"
    print(f"wrote {OUTPUT} ({len(data)} bytes, top {TOP} of zxcvbn {COMMIT[:12]}){note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
