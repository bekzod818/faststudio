# ADR-0011: Backend capabilities, authorization and contrib.auth

- Status: Accepted (2026-11-25, maintainer approval with amendments A1–A7)
- Date: 2026-11-24
- Amends: ADR-0004 (decision 1), ADR-0009 (made public), threat model T2 and new T9.
  Plan: docs/plans/v0.2.md §2, §4

## Context

v0.1 treats every authenticated admin as all-powerful. v0.2 adds optional
Django-style users, groups and permissions, while `ModelUserBackend` users
keep v0.1 behaviour and core never imports `contrib`. ADR-0009 deferred
public naming, capability detection, refusal codes, a shared guard helper
and the definition of "admin".

## Decision

1. **Capabilities are namespaced.** A backend may define
   `faststudio_capabilities`, returning a frozen `BackendCapabilities` with
   optional `account_guard`, `permissions`, `user_admin`,
   `session_revocation` and `register_admins`.
   - Unknown or unrelated attributes on a backend are never inspected.
   - Startup validates each present capability.
   - Capability methods receive an `AsyncSession` and never a `Request`,
     because the CLI has no request.
   - A backend whose `guards`, `before_write` and `check_model` (the 0.1.1
     private protocol) are all callable, but which has no
     `faststudio_capabilities`, gets a `ConfigurationError`, so it cannot
     fail open. A lone unrelated attribute never triggers this.
2. **Vocabulary.** The actions are `view`, `create`, `edit` and `delete`.
   - Codenames are `<identity>.<action>`, plus
     `ModelAdmin.extra_permissions` keys (`[a-z][a-z0-9_]{0,40}`, not one of
     the actions, codename at most 100 characters).
   - `edit` implies `view`.
3. **Resolution.** `PermissionBackend.resolve(session, user)` returns
   `ALL | frozenset[str]`, once per request, cached on `request.state`.
   - Without the capability: `ALL`, with 0 queries.
   - In contrib: superuser gives `ALL` with 0 queries; otherwise exactly
     1 query (direct ∪ group permissions).
4. **Hooks.** Async classmethods on `ModelAdmin`:
   - `has_view_permission(request, obj=None)`
   - `has_create_permission(request)`
   - `has_edit_permission(request, obj=None)`
   - `has_delete_permission(request, obj=None)`

   Each defaults to the static flag AND the permission. `has_perm(request,
   codename)` is public. Object-level hooks run on retrieve, edit and delete
   only: **they do not filter lists or choices** (a list-query hook is
   v0.3). An object-level refusal answers 404 on retrieve, and 403 on edit
   and delete (documented).
5. **Enforcement** on every route (`403 forbidden`), checked by a test that
   enumerates the mounted routes:
   - `/meta` lists only models the user can view, `permissions` gains
     `view`, and `relation.target_identity` is null for targets the user
     cannot view.
   - Choices need create or edit on the source, and answer `403` without
     view on the target.
   - FK and M2M labels of targets the user cannot view fall back to the
     primary key, in list and detail responses. FK and M2M fields pointing
     to such targets are readonly for that user, so the existence check
     cannot probe a denied model.
   - **Implications:** `edit` implies `view`. `create` and `delete` without
     `view` are API-only, because `/meta` lists only viewable models.
     Create without view returns a minimal `Row` (`pk` plus the submitted
     fields). The full table will be in docs/auth.md (M21).
6. **Escalation rules**, enforced by core before the account guard, on
   **create, update and delete**. The guard capability declares the
   superuser-like flag and the permission-bearing M2M fields, including any
   writable reverse sides. Checking a target account holding `ALL` resolves
   the target's permissions; this adds queries on guarded writes only.
   - Only a user holding `ALL` may set or change the superuser-like flag
     (including on create), edit or delete an account holding `ALL`, or set
     another user's password. Nobody may set their **own** password through
     the set-password endpoint; that goes through `POST /auth/password`.
   - **Effective-permission rule:** for any write that changes anyone's
     effective permissions, the codenames each affected user would gain
     (`effective_after − effective_before`) must be a subset of the actor's,
     unless the actor holds `ALL`. This covers `user.permissions`,
     `user.groups` (self-membership included), `group.permissions` (every
     member is affected) and writable reverse sides.
     - It is computed **before the flush, from the intent** (only
       association rows change), in the write's transaction, after locking
       the affected group and user rows (`FOR UPDATE`, primary-key order).
     - A refusal is `403 forbidden`, before the account guard.
     - A conservative closed form keeps the query count fixed: for
       `group.permissions`, the added codenames must be within the actor's;
       for `user.groups` / `user.permissions`, `(perms(added groups) ∪ added
       codenames) − effective_before(u)` must be within the actor's. This is
       slightly stricter than "no user may gain", which is documented.
     - Removals are never escalation. The guard capability supplies the
       affected models and the resolver, so core stays contrib-agnostic.
7. **Guard (ADR-0009, now public).**
   - "Admin" is defined by flags only; group-granted permissions do not
     count.
   - `FlagAccountGuard(model, pk_field, flags)` is the shared public helper.
   - There are no new refusal codes; permission denials are always
     `403 forbidden`, never `WriteRefused`.
8. **`faststudio.contrib.auth`:**
   - `AuthModels(Base, table_prefix="faststudio_")` declares
     `FastStudioUser`, `FastStudioGroup`, `FastStudioPermission` and three
     association tables. Calling it twice on the same `Base` raises
     `ConfigurationError`.
   - `DatabaseAuthBackend` reuses core hashing, dummy verification and
     `auth_version` (`password_hash | is_active | is_superuser |
     session_token`).
   - New users get an unusable hash.
   - Password validators live in core (`faststudio.auth.validators`) and are
     re-exported by contrib.
9. **Contract versioning.** New keys and enum values are additive and keep
   `schema_version "1"`. Clients must ignore unknown keys and treat unknown
   `FieldType` values as `unsupported`. Removing, renaming or changing a
   meaning requires `"2"`.

## Alternatives considered

- **Duck-typed capability methods** (ADR-0009's private form): risk of
  accidental matches and failing open.
- **Permissions in core with core-owned tables:** contradicts ADR-0004 for
  `ModelUserBackend` users.
- **Django action names** (`add`, `change`): inconsistent with the
  contract.

## Consequences

- `ModelUserBackend` users see no behaviour change and no new HTTP write
  path. The HTTP password endpoints are opt-in for that backend
  (`password_endpoints=False` by default), because every one of its admins
  holds `ALL`. Responses gain only additive keys:
  - in `/meta`: `permissions.view`, `capabilities`, `account.set_password`
    (false unless opted in) and `account.admin_flag`;
  - on detail rows: `many_labels` and `truncated`, empty without M2M
    fields.
- With the `user_admin` and `session_revocation` capabilities, FastStudio
  may write to the host's user table, but only through capabilities the
  backend explicitly provides. Threat model T2 is amended accordingly.
- Permission changes take effect on the next request; group changes don't
  revoke sessions.

## Implementation notes (M17, approved 2026-11-25)

Decisions the plan left open, approved with the M17 plan:

1. **Escalation logic lives in core.** The backend declares where users,
   groups and permissions live with `BackendCapabilities.permission_schema`
   (`PermissionSchema`: models, codename attribute, relationship names of
   each writable side). It needs `permissions` and an `account_guard` that
   covers its user model. (§6 says "the guard capability declares"; after
   the architect review the schema moved to `BackendCapabilities`, so the
   account guard keeps only account-safety concerns such as `admin_flag`.) Core reads and locks
   the association tables with its own many-to-many introspection
   (ADR-0010). The backend only resolves accounts
   (`PermissionBackend.resolve_accounts`). Core refuses to register a mapping
   of a declared association table, or a writable many-to-many over one that
   the schema does not declare. Renaming a permission's codename counts as
   granting the new codename to its holders.
2. **Removing links on the other side** when a record is deleted needs only
   the delete permission on that record's model (removals never escalate).
3. **Link counts** (`GET .../links`) leave out fields of models the admin may
   not view.
4. **Relations to models the admin may not view** are readonly for them:
   `/meta` marks them readonly, and writing one is `422 extra_forbidden`,
   before the existence check.
5. **The SPA** shows one "Not found or no access" page for models missing
   from `/meta` and for `403` answers.

Also: creates reach the account guard (`WriteIntent.action == "create"`);
`ModelUserBackend` provides its guard as `FlagAccountGuard` through
`faststudio_capabilities`, and its private 0.1.1 guard methods are removed.

**Protocol evolution (approved 2026-11-25).** Released capability protocols
(`AccountGuard`, `PermissionBackend`) are frozen: adding a member to a
`runtime_checkable` protocol breaks every third-party implementation. New
behaviour arrives as a new optional `BackendCapabilities` field, or as a
method with a documented default that core probes for. `BackendCapabilities`
and `PermissionSchema` are keyword-only dataclasses, so new fields with
defaults are additive.

**Security review fixes (M17).** Other mappings of the user, group and
permission tables are refused at `register()`; the codename is read through
its mapped attribute; an account `resolve_accounts` does not report counts
as holding `ALL` when it is the target; the target account is re-read under
a lock before the flag and `ALL` checks; the object-level view hook also
applies to edit, delete and link counts (404).

## Implementation notes (M18a, approved 2026-11-25)

- **Names.** The capability called `user_admin` in §1 and in the
  Consequences shipped as `BackendCapabilities.accounts`, protocol
  `AccountManager` (`password_validators`, `user_inputs`, `check_password`,
  `set_password`; accounts named by the `AuthenticatedUser.id` string). The
  HTTP password endpoints are switched on by a separate
  `BackendCapabilities.password_endpoints` (off for `ModelUserBackend`
  unless `password_endpoints=True`), because the CLI always uses `accounts`.
  M19 adds `find_account`, `required_fields` and `create_admin` before
  0.2.0 is tagged.
- **Validators** live in core (`faststudio.auth.validators`); no
  common-password list is bundled (A5 open).
- **Setting another account's password** needs every permission *and* the
  model's edit hooks (`can_edit`, `has_edit_permission(obj)`); a record
  hidden by `has_view_permission(obj)` is a 404, as on retrieve.

## Implementation notes (M18b, approved 2026-11-25)

- **Secret fields.** `AccountGuard.secret_fields(model)` (new, before the
  protocol is released) names columns that must never be shown;
  `Admin.register()` fails unless they are excluded. `contrib.auth` declares
  `password_hash` and `session_token`; `ModelUserBackend` declares none, so
  v0.1 apps keep starting (with the existing warning).
- **`BackendCapabilities.register_admins`** (keyword-only, additive) is
  called with the `Admin` at the end of its construction. `contrib.auth`
  registers its users, groups and permissions admins unless
  `DatabaseAuthBackend(register_admins=False)`; the default admin classes
  are public factories (`user_admin`, `group_admin`, `permission_admin`) to
  subclass.
- **Usernames.** A `username_normalized` column (NFKC + case-fold, kept in
  sync on assignment) with a plain unique index replaces the functional
  `lower(username)` index: same behaviour on SQLite, PostgreSQL and MySQL,
  and clean Alembic autogenerate.
- **Lock order across chunks** (M17 follow-up): only matters above 500
  keys in one write; the worst case is a deadlock, which is a documented
  `409`. A PostgreSQL test pins "409, never 500" for concurrent writes on
  admin accounts.
- **Codename count (A3).** The warning when codenames exceed 10 000 moves to
  `syncpermissions` (M19): only there are all registered models known.
- **Password helpers are public** (`faststudio.auth.passwords.__all__`):
  `hash_password`, `hash_password_async`, `verify_password_async`,
  `dummy_verify_async`, `is_password_hash`, `prepare_dummy_hash`. Contrib
  depends only on public core API; custom backends need the same helpers.
