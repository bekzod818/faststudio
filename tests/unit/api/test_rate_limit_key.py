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


@pytest.mark.parametrize(
    ("variant", "plain"),
    [
        # Checked against MySQL 8.4 utf8mb4_0900_ai_ci by the PR #23 reviewers.
        ("admin\u0903", "admin"),  # Devanagari visarga (Mc), ignored
        ("ad\u0903m\u0903in", "admin"),
        ("admin\u17c7", "admin"),  # Khmer reahmuk (Mc)
        ("admin\u0f7f", "admin"),  # Tibetan rnam bcad (Mc)
        ("admin\u07fa", "admin"),  # NKo lajanyalan (Lm)
        ("admin\u180a", "admin"),  # Mongolian nirugu (Po)
        ("admin\u1cf2", "admin"),  # Vedic ardhavisarga (Lo)
        ("admin\u0661", "admin1"),  # Arabic-Indic one
        ("\u09e8\u09e8admin", "22admin"),  # Bengali digits
        ("adm\u0365n", "admin"),  # combining Latin small letter i
        ("jos\u0364", "jose"),  # combining Latin small letter e
        ("\u0140ola", "lola"),  # l with middle dot
    ],
)
def test_ignorables_digits_and_letter_forms_share_a_key(variant: str, plain: str) -> None:
    assert rate_limit_username(variant) == rate_limit_username(plain)


@pytest.mark.parametrize("name", ["admin", "root", "ann", "dan-the-admin", "x" * 150])
def test_plain_names_are_unchanged(name: str) -> None:
    assert rate_limit_username(name) == name


def test_distinct_names_stay_distinct() -> None:
    assert rate_limit_username("ann") != rate_limit_username("anne")
    assert rate_limit_username("bob") != rate_limit_username("rob")
