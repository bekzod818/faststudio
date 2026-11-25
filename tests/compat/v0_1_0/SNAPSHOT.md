# Frozen v0.1.0 snapshot (compatibility proof, v0.2 plan M14)

Copied from tag `v0.1.0` (commit `1393844b6ac683e758949e0b78139a131bdea88b`). Do not edit: `tests/compat/test_v0_1_0.py`
checks these hashes and runs the code against the current FastStudio.

The only change from the tag: the import path `examples.basic.` became
`tests.compat.v0_1_0.basic.` in `basic/*.py`, so the snapshot imports itself.
The directory is excluded from ruff and mypy so it stays byte-identical.

| File | SHA-256 |
|---|---|
| `README.md` | `1101528e51e5483022c153d44da4ddd22833dabac9f36f6453651f548f048366` |
| `basic/__init__.py` | `e4389ad39e03413f2e2e5ea7863546686d1a2605066609537578e8a53581afb1` |
| `basic/app.py` | `3494a5f8cc224dd60d9b681cfa5bc6e897218c1db36d896817c5535434523506` |
| `basic/db.py` | `d4b11619e3348559acede9cc5cd014fd60c187938d5030ce2c77476e1f12746e` |
| `basic/models.py` | `d75148a4b1222b8cf89793576e0b2b0b7fa00feccdf7950d52fb26e785c7ee67` |
