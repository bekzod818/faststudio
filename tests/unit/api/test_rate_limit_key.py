"""Login rate-limit keys merge what MySQL's default collation signs in as one (5b review)."""

from __future__ import annotations

import pytest

from faststudio.api.auth import rate_limit_username


@pytest.mark.parametrize(
    "variant",
    [
        "Jose",
        " JOSÉ ",
        "José",
        "josé",  # combining acute
        "ｊｏｓｅ",  # noqa: RUF001 - full-width on purpose
        "jo­se",  # soft hyphen
        "jo\u200bse",  # zero-width space
        "jo‍se",  # zero-width joiner
        "jo͏se",  # combining grapheme joiner
        "jo‎se",  # left-to-right mark
    ],
)
def test_variants_of_one_name_share_a_key(variant: str) -> None:
    assert rate_limit_username(variant) == "jose"


@pytest.mark.parametrize(
    ("variant", "plain"),
    [
        ("bjørn", "bjorn"),
        ("BJÖRN", "bjorn"),
        ("łukasz", "lukasz"),
        ("đorđe", "dorde"),
        ("ðór", "dor"),
        ("ħamrun", "hamrun"),
        ("æsir", "aesir"),
        ("œuvre", "oeuvre"),
        ("straße", "strasse"),
        ("ᾳ", "α"),  # noqa: RUF001 - Greek on purpose; iota subscript: MySQL compares it as the bare vowel
        ("مـحمد", "محمد"),  # tatweel
    ],
)
def test_letters_the_collation_equates_share_a_key(variant: str, plain: str) -> None:
    assert rate_limit_username(variant) == rate_limit_username(plain)


@pytest.mark.parametrize("name", ["admin", "root", "ann", "dan-the-admin", "x" * 150])
def test_plain_names_are_unchanged(name: str) -> None:
    assert rate_limit_username(name) == name


def test_distinct_names_stay_distinct() -> None:
    assert rate_limit_username("ann") != rate_limit_username("anne")
    assert rate_limit_username("bob") != rate_limit_username("rob")
