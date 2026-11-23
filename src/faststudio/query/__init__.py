"""Safe query building for the list API (private).

This package is the only place where request parameters become SQL, always
as SQLAlchemy expressions over columns from `RegisteredModel` allowlists.
"""
