# ADR-0009: Account-safety guard as an optional auth-backend capability

- Status: Accepted
- Date: 2026-11-24
- Refines: ADR-0004 (authentication, sessions and CSRF)

## Context

When the model behind `ModelUserBackend` is registered in the admin, an admin
can edit their own row. In v0.1.0, an admin who cleared their own `is_admin`
or `is_active` flag, or deleted their own row, got a successful response and
then a 401 on every later request, with no recovery path in the UI. Two admins
demoting each other at the same moment could also leave nobody able to sign
in.

Only the auth backend knows which model holds the accounts, which flags decide
who may sign in, and which row is the signed-in user. The write API knows when
a write happens and owns its transaction. `faststudio.contrib.auth` (v0.2)
needs the same protection for `is_superuser`.

## Decision

1. **An optional backend capability.** The write API checks whether the auth
   backend implements `AccountGuard` (`faststudio/auth/_guard.py`). If it does
   not, nothing changes. If it does:
   - `check_model(model)` runs at `register()` and may refuse a model whose
     writes the guard could not check;
   - `guards(model)` selects the models whose writes are checked;
   - `before_write(session, user, intent)` runs before each update or delete
     of such a model, in the request's transaction. It raises
     `WriteRefused(code, message)` to refuse the write (409 with that `code`),
     or returns a post-write check that the API runs **after the flush and
     before the commit**, in the same transaction.
2. **`ModelUserBackend` implements it** for its user model and mapped
   subclasses of it. Registering another mapping of the user model's tables
   (a base class in an inheritance hierarchy, or a second class mapped to the
   same table) raises `ConfigurationError`, because writes through it would
   bypass the guard. This is deliberately conservative: it also refuses a
   sibling subclass (`Customer(Person)` next to the user model
   `Staff(Person)`) that shares the table.
   - **`self_lockout`**: on the signed-in user's own row, changing a sign-in
     flag (`is_active_field`, `is_admin_field`) to a different value, or
     deleting the row, is refused. Re-sending the current values is allowed.
     The row is matched by `str(primary key) == user.id`, the same rule that
     builds `user.id`.
   - **`last_admin`**: a write that could remove an active admin is refused if
     no active admin remains afterwards. An active admin has every configured
     flag true; with no flags configured, every row counts.
3. **Atomic last-admin check.**
   - **Which writes are checked** is decided from the request alone: every
     delete, and every update that sends a sign-in flag with a value other
     than `true`. It never depends on the loaded row, which was read before
     any lock and may be stale.
   - **Before the write**, the guard locks every active admin row
     (`SELECT pk ... ORDER BY pk FOR UPDATE`). The fixed order means concurrent
     requests cannot deadlock each other.
   - **After the flush**, the check reads the remaining active admins with a
     locking read (`... FOR UPDATE`, counted in Python because PostgreSQL
     rejects `FOR UPDATE` with aggregates). A locking read sees the latest
     committed rows; a plain read would use the transaction's earlier snapshot
     under MySQL's default REPEATABLE READ.
   - **How each database serializes it:**
     - PostgreSQL, READ COMMITTED (default): the concurrent request waits for
       the lock, re-reads the rows after the first commit, and is refused with
       `last_admin`.
     - PostgreSQL, REPEATABLE READ / SERIALIZABLE: the database aborts the
       loser with a serialization failure, which becomes `409 conflict`.
     - MySQL / InnoDB, REPEATABLE READ (default): `FOR UPDATE` waits, and the
       locking re-read sees the first commit, so the loser gets `last_admin`.
     - SQLite ignores `FOR UPDATE`. The flush takes the database write lock,
       so a concurrent writer serializes behind it. Depending on the driver's
       transaction mode it either counts after the first commit
       (`last_admin`) or fails to get the lock (`409 conflict`).
   - **The result** on every database: exactly one of two concurrent removals
     of the last admins succeeds, and the other gets `409 last_admin` or
     `409 conflict`. SQLite is covered by the test suite, PostgreSQL (READ
     COMMITTED and REPEATABLE READ) by the PostgreSQL CI job; MySQL is not
     tested in 0.1.1.
4. **Concurrency losers are conflicts, not errors.** These failures during any
   write become `409 conflict`:
   - lock and snapshot failures: SQLite `SQLITE_BUSY` / `SQLITE_LOCKED`,
     SQLSTATE `40001` / `40P01` / `55P03`, MySQL 1205 / 1213;
   - an update whose row a concurrent request deleted (`StaleDataError`).
5. **Private in v0.1.x.** The protocol stays in a private module for the patch
   release. v0.2 makes it public together with the other backend capabilities
   (permissions) and reuses it in `contrib.auth` for `is_superuser`.

## Contract for implementers

- `before_write` runs after authorization (`can_edit` / `can_delete`, and
  the v0.2 permission checks), body validation and relation checks, and before
  any change is applied to `intent.obj`. Refusal codes therefore never reach a
  user who is not allowed to make the write anyway. For deletes, it runs after
  the related-records check, so a delete refused for related rows never takes
  the guard's locks.
- `session` is the request's session, inside an open transaction.
  Implementations must not commit, roll back, close or flush it, and must not
  modify `intent.obj`.
- `intent.changes` holds only validated, writable fields. Readonly and
  excluded fields never appear in it.
- Anything the post-write check depends on must be locked in `before_write`
  (in a deterministic order), and re-read with a locking read in the check.
  Decide what to check from `intent`, not from the loaded object's state.
- The post-write check runs after the flush and before the commit. Raising
  `WriteRefused` rolls back the whole write. Lock or snapshot errors raised in
  either call become `409 conflict`; any other exception is a 500, after a
  rollback.
- `WriteRefused.message` is shown to the admin and must not contain stored
  values.
- `WriteAction` is `"update"` or `"delete"`. Creates are not guarded, because
  a create cannot remove access. Future write paths keep these two actions:
  - bulk updates and deletes (v0.3) call `before_write` once per object, then
    flush once, then run every returned check, so one transaction may carry
    many intents;
  - many-to-many changes (v0.2) arrive as `update` intents, with the
    relationship field in its contract form (a list of primary keys).

  Implementations must refuse an action they do not recognize rather than
  allow it, so the vocabulary can widen safely.

## Not covered

- Writes outside FastStudio's write API: the host application's own code,
  direct database changes, database-only `ON DELETE CASCADE` rules from other
  tables (they have no ORM relationship for the write API to check), and v0.3
  custom actions that run arbitrary ORM code. For custom actions, core should
  offer a helper that runs the guard for each object an action touches,
  rather than leaving it to action authors.
- Custom `AuthBackend`s that do not implement the capability.
- The guard only covers HTTP writes by a signed-in admin, which is why `user`
  is required. Recovering a locked-out installation is done from a shell:
  `docs/getting-started.md` ("Locked out?"), and a CLI in v0.2.

## Alternatives considered

- **A check inside the write route, reading `ModelUserBackend` internals.**
  This would couple core to one backend, and `contrib.auth` would need a second
  copy.
- **Making the flag fields read-only for everyone.** Admins could then never
  promote or deactivate other accounts.
- **Counting admins before the write only.** Two concurrent removals would
  each see the other admin still active and both succeed.

## Consequences

- One-admin installations cannot lock themselves out through the UI or API.
- Custom `AuthBackend`s get no protection until they implement the capability
  (public in v0.2). This is stated in `docs/api-contract.md` and the threat
  model.
- A checked write takes row locks on all active admins. That is cheap, because
  admin rows are few, and it happens only when a write could remove an admin.
- The SPA learns which fields are protected on the admin's own record from an
  additive `ModelMeta` field. The server remains the enforcement point.

## Deferred to the v0.2 auth ADR

- **Refusal codes.** `RefusalCode` is a closed two-value literal tied to the
  contract's `ErrorCode`. A new code is an additive contract change.
  Permission denials (for example "cannot grant a permission you lack") are
  `403 forbidden`, not `WriteRefused`, so the guard does not become a second
  permission system.
- **Reusable logic.** Extract the flag-based rules into a helper (for example
  `FlagAccountGuard(model, pk_field, flags)`) that `ModelUserBackend` and
  `contrib.auth`'s backend delegate to, instead of copying or inheriting.
- **Who counts as an admin.** If admin rights can come from groups or
  permissions, decide whether they count for `last_admin`. If they do,
  `guards()` must also cover the group and association models, and the
  remaining-admins query becomes a join. The interface allows this, and it is
  the backend's job.
- **Public naming and detection.** `runtime_checkable` only checks attribute
  names, so an unrelated `guards` attribute would match. When going public,
  prefer an explicit optional `account_guard` attribute that returns a guard
  object, or more specific method names.
- **Bulk operations.** One post-write check per object means N counts for N
  objects. That is acceptable because admin rows are few.
