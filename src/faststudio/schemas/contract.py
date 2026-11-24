"""Pydantic models defining the FastStudio HTTP API contract (ADR-0007).

These models are the single source of truth for API shapes. They are exported
to `contract.schema.json` and generated into TypeScript for the SPA; never
edit those artifacts by hand. Additive changes keep `SCHEMA_VERSION`;
removing or changing a field is breaking and needs an ADR.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from faststudio.introspection._types import FieldType

__all__ = [
    "SCHEMA_VERSION",
    "ChoiceMeta",
    "ChoicesResponse",
    "ErrorBody",
    "ErrorCode",
    "ErrorResponse",
    "FieldMeta",
    "FieldType",
    "FilterMeta",
    "ListResponse",
    "LoginRequest",
    "MetaResponse",
    "ModelMeta",
    "PermissionsMeta",
    "RelationMeta",
    "Row",
    "SpaConfig",
    "UserMeta",
    "UserResponse",
    "ValidationIssue",
]

SCHEMA_VERSION: Literal["1"] = "1"
MAX_USERNAME_LENGTH = 150
# argon2 cost grows with input; cap passwords so a huge body cannot stall the server.
MAX_PASSWORD_LENGTH = 1024
# Integers JavaScript represents exactly. Larger values travel as strings.
MAX_SAFE_INTEGER = 2**53 - 1
# No C0/C1 control characters or line/paragraph separators (log injection,
# driver errors on NUL) and no bidi overrides.
USERNAME_PATTERN = r"^[^\x00-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]+$"

ErrorCode = Literal[
    "invalid_query",
    "not_authenticated",
    "invalid_credentials",
    "csrf_failed",
    "forbidden",
    "not_found",
    "method_not_allowed",
    "conflict",
    "self_lockout",
    "last_admin",
    "validation_error",
    "payload_too_large",
    "rate_limited",
    "internal_error",
]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ChoiceMeta(_Contract):
    """One allowed value: wire `value` and display `label`."""

    value: str
    label: str


class RelationMeta(_Contract):
    """Many-to-one target.

    `target_identity` and `target_field` are both null when the target model is
    not registered; otherwise `target_field` is the target's primary key.
    """

    target_identity: str | None
    target_field: str | None
    value_type: FieldType


class FieldMeta(_Contract):
    """Description of one visible field (see docs/api-contract.md, "Field flags").

    `min_value`/`max_value` are only published within ±(2**53 - 1); wider
    ranges (BigInteger) are null and enforced by the server.
    """

    name: str
    label: str
    type: FieldType
    nullable: bool
    required: bool
    readonly: bool
    create_only: bool
    primary_key: bool
    default: JsonValue
    has_default: bool
    max_length: int | None
    min_value: int | None
    max_value: int | None
    choices: list[ChoiceMeta] | None
    relation: RelationMeta | None
    timezone: bool | None
    precision: int | None
    scale: int | None
    help_text: str | None


class FilterMeta(_Contract):
    """A list filter. Boolean filters have no choices (true/false/null)."""

    field: str
    kind: Literal["boolean", "choice"]
    choices: list[ChoiceMeta]


class PermissionsMeta(_Contract):
    """Actions allowed on a model."""

    create: bool
    edit: bool
    delete: bool


class AccountMeta(_Contract):
    """The model holds the admins' accounts (ADR-0009).

    On the record of the signed-in admin (`pk == MetaResponse.user.id`), the
    `protected_fields` cannot be changed and the record cannot be deleted; the
    server refuses with `self_lockout`.
    """

    protected_fields: list[str]


class ModelMeta(_Contract):
    """Everything the SPA needs to render one registered model."""

    identity: str
    name: str
    name_plural: str
    icon: str | None
    pk_field: str
    list_display: list[str]
    search_fields: list[str]
    list_filter: list[FilterMeta]
    #: Default sort as `field` / `-field`.
    ordering: list[str]
    sortable_fields: list[str]
    page_size: int
    permissions: PermissionsMeta
    fields: list[FieldMeta]
    #: Set on the model that stores the admins' accounts, else null.
    account: AccountMeta | None


class UserMeta(_Contract):
    """The signed-in admin."""

    id: str
    username: str


class UserResponse(_Contract):
    """`POST /auth/login` and `GET /auth/me`."""

    user: UserMeta


class MetaResponse(_Contract):
    """`GET /meta`."""

    schema_version: Literal["1"]
    version: str
    title: str
    show_powered_by: bool
    user: UserMeta
    models: list[ModelMeta]


class Row(_Contract):
    """One record: primary key as a string, visible field values, relation labels."""

    pk: str
    data: dict[str, JsonValue]
    labels: dict[str, str]


class ListResponse(_Contract):
    """`GET /models/{identity}/items`."""

    items: list[Row]
    total: int
    page: int
    page_size: int


class ChoicesResponse(_Contract):
    """`GET /models/{identity}/fields/{field}/choices`."""

    items: list[ChoiceMeta]
    total: int


class SpaConfig(_Contract):
    """Runtime config injected into index.html as `<script type="application/json" id="fs-config">`.

    Served before login, so it holds only what the login page needs (no version).
    """

    schema_version: Literal["1"]
    base_url: str
    api_url: str
    title: str
    #: Lists never skip this many rows: the last reachable page is
    #: ceil(max_list_offset / page_size).
    max_list_offset: int = Field(ge=1, le=10_000_000)


class LoginRequest(_Contract):
    """`POST /auth/login` body. The password never appears in repr or errors."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    username: str = Field(min_length=1, max_length=MAX_USERNAME_LENGTH, pattern=USERNAME_PATTERN)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH, repr=False)


class ValidationIssue(_Contract):
    """One invalid input. Never echoes the submitted value."""

    loc: list[str | int]
    msg: str
    type: str


class ErrorBody(_Contract):
    """Error details: a list of issues for `validation_error`, otherwise null."""

    code: ErrorCode
    message: str
    details: list[ValidationIssue] | None


class ErrorResponse(_Contract):
    """Every non-2xx response body."""

    error: ErrorBody
