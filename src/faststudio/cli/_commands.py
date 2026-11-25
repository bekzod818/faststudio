"""The CLI commands (ADR-0012). Each returns its exit code."""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from collections.abc import Callable, Coroutine, Iterable, Mapping, Sequence
from typing import Any

from faststudio.admin import Admin
from faststudio.api._permission_sync import MAX_CODENAMES, apply_sync, plan_sync
from faststudio.auth.capabilities import AccountManager, UsernameAudit
from faststudio.auth.validators import validate_password
from faststudio.cli._io import CliError, CliIO
from faststudio.schemas.contract import MAX_USERNAME_LENGTH, USERNAME_PATTERN

_USERNAME = re.compile(USERNAME_PATTERN)


def _accounts(admin: Admin) -> AccountManager:
    accounts = admin._capabilities.accounts
    if accounts is None:
        msg = (
            "The auth backend has no `accounts` capability (BackendCapabilities.accounts), "
            "so it cannot manage accounts from the command line."
        )
        raise CliError(msg)
    return accounts


def _check_username(username: str) -> str:
    if not username or username != username.strip():
        msg = "The username must not be empty or start or end with spaces."
        raise CliError(msg)
    if len(username) > MAX_USERNAME_LENGTH or not _USERNAME.fullmatch(username):
        msg = f"Use a username of at most {MAX_USERNAME_LENGTH} visible characters."
        raise CliError(msg)
    return username


def _read_new_password(io: CliIO, accounts: AccountManager, inputs: Sequence[str]) -> str:
    """Read a new password twice (never from argv or the environment) and validate it."""
    io.need_terminal("Reading a password")
    password = io.read_password("Password: ")
    if io.read_password("Password (again): ") != password:
        msg = "The passwords do not match."
        raise CliError(msg)
    problems = validate_password(password, accounts.password_validators, user_inputs=inputs)
    if problems:
        raise CliError("\n".join(problems))
    return password


def _parse_set(pairs: Sequence[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for pair in pairs:
        name, sep, value = pair.partition("=")
        if not sep or not name:
            msg = f"--set expects FIELD=VALUE, got {pair!r}."
            raise CliError(msg, code=2)
        fields[name] = value
    return fields


async def create_admin(admin: Admin, args: argparse.Namespace, io: CliIO) -> int:
    """``createadmin``: an account with every permission."""
    accounts = _accounts(admin)
    fields = _parse_set(args.set)
    if args.username is None:
        io.need_terminal("Asking for the username (or pass --username)")
    raw = args.username if args.username is not None else io.read_line("Username: ").strip()
    username = _check_username(raw)
    async with admin._session_maker() as session:
        if await accounts.find_account(session, username) is not None:
            msg = f"An account named {username!r} already exists; use changepassword."
            raise CliError(msg)
        missing = [name for name in accounts.required_fields() if name not in fields]
        if missing and not io.is_tty():
            msg = f"Missing required value(s): {', '.join(missing)} (pass --set FIELD=VALUE)."
            raise CliError(msg)
        for name in missing:
            fields[name] = io.read_line(f"{name}: ").strip()
        password = _read_new_password(io, accounts, [username, *fields.values()])
        try:
            account_id = await accounts.create_admin(
                session, username=username, password=password, fields=fields
            )
        except ValueError as exc:
            raise CliError(str(exc)) from None
        await session.commit()
    io.write(f"Created admin {username!r} (id {account_id}).")
    return 0


async def change_password(admin: Admin, args: argparse.Namespace, io: CliIO) -> int:
    """``changepassword USERNAME``: also signs the account out everywhere."""
    accounts = _accounts(admin)
    async with admin._session_maker() as session:
        account_id = await accounts.find_account(session, args.username)
        if account_id is None:
            msg = f"No account named {args.username!r}."
            raise CliError(msg)
        inputs = await accounts.user_inputs(session, account_id)
        password = _read_new_password(io, accounts, inputs)
        try:
            await accounts.set_password(session, account_id, password)
        except LookupError:
            msg = f"No account named {args.username!r}."
            raise CliError(msg) from None
        await session.commit()
    io.write(f"Password changed for {args.username!r}; their sessions are signed out.")
    return 0


def _listing(title: str, codenames: Sequence[str], io: CliIO) -> None:
    if codenames:
        io.write(f"{title} ({len(codenames)}):")
        for codename in codenames:
            io.write(f"  {codename}")


async def sync_permissions(admin: Admin, args: argparse.Namespace, io: CliIO) -> int:
    """``syncpermissions``: idempotent, in one transaction; prunes only when asked."""
    rules = admin._escalation
    if rules is None:
        msg = (
            "The auth backend declares no `permission_schema` (BackendCapabilities."
            "permission_schema), so there is no permission table to synchronize."
        )
        raise CliError(msg)
    async with admin._session_maker() as session, session.begin():
        plan = await plan_sync(session, rules, admin._registry)
        if len(plan.expected) > MAX_CODENAMES:
            io.error(
                f"Warning: {len(plan.expected)} codenames exceed {MAX_CODENAMES}, the most a "
                "permissions field can hold; some assignments will be read-only."
            )
        _listing("Missing", plan.missing, io)
        _listing("Renamed", plan.renamed, io)
        _listing("Stale (no registered model produces them)", plan.stale, io)
        _listing("Orphaned (stale, still granted)", plan.orphaned, io)
        if args.dry_run:
            io.write("Dry run: nothing was changed.")
            await session.rollback()
            return 0
        prune = bool(args.prune and plan.stale)
        if prune and not io.confirm(
            f"Delete {len(plan.stale)} stale permission(s) and their grants?", yes=args.yes
        ):
            io.error("Aborted: nothing was changed.")
            await session.rollback()
            return 1
        await apply_sync(session, rules, plan, prune=prune)
    io.write(
        f"Created {len(plan.missing)}, renamed {len(plan.renamed)}"
        + (f", deleted {len(plan.stale)} stale" if prune else "")
        + " permission(s)."
    )
    return 0


async def check_users(admin: Admin, args: argparse.Namespace, io: CliIO) -> int:
    """``checkusers``: report (and with ``--fix`` repair) normalized-username drift."""
    audit: UsernameAudit | None = admin._capabilities.username_audit
    if audit is None:
        msg = (
            "The auth backend has no `username_audit` capability: it signs in by the "
            "username itself, so there is nothing to check."
        )
        raise CliError(msg)
    async with admin._session_maker() as session, session.begin():
        accounts = await audit.audit(session)
        by_key: Mapping[str, list[str]] = _group(
            (account.expected, account.account_id) for account in accounts
        )
        names = {account.account_id: account.username for account in accounts}
        colliding = {i for ids in by_key.values() if len(ids) > 1 for i in ids}
        drifted = [a.account_id for a in accounts if a.stored != a.expected]
        fixable = [i for i in drifted if i not in colliding]
        for key, ids in sorted(by_key.items()):
            if len(ids) > 1:
                listed = ", ".join(f"{names[i]!r} (id {i})" for i in ids)
                io.write(f"Collision on {key!r}: {listed}")
        for i in drifted:
            note = " (collides: fix by renaming)" if i in colliding else ""
            io.write(f"Stale normalized username: {names[i]!r} (id {i}){note}")
        fixed = 0
        if args.fix and fixable:
            if not io.confirm(f"Repair {len(fixable)} account(s)?", yes=args.yes):
                io.error("Aborted: nothing was changed.")
                await session.rollback()
                return 1
            await audit.fix(session, fixable)
            fixed = len(fixable)
    remaining = len(colliding) + len(drifted) - fixed - len(colliding & set(drifted))
    if fixed:
        io.write(f"Repaired {fixed} account(s).")
    if remaining:
        io.error(f"{remaining} account(s) still need attention.")
        return 1
    io.write("All usernames are consistent.")
    return 0


def _group(pairs: Iterable[tuple[str, str]]) -> dict[str, list[str]]:
    grouped: defaultdict[str, list[str]] = defaultdict(list)
    for key, value in pairs:
        grouped[key].append(value)
    return dict(grouped)


COMMANDS: Mapping[str, Callable[[Admin, argparse.Namespace, CliIO], Coroutine[Any, Any, int]]] = {
    "createadmin": create_admin,
    "changepassword": change_password,
    "syncpermissions": sync_permissions,
    "checkusers": check_users,
}
