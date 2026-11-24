"""Serve the bundled SPA with runtime configuration (ADR-0005)."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from faststudio.config import API_PREFIX, Settings
from faststudio.exceptions import FastStudioError
from faststudio.schemas.contract import SCHEMA_VERSION, SpaConfig

HEAD_MARKER = "<!-- faststudio:head -->"
#: Scope key holding the admin mount root as the browser sees it (proxy prefix + base_url).
ADMIN_ROOT_KEY = "faststudio.admin_root"
_TITLE = re.compile(r"<title>.*?</title>", re.DOTALL)
_JSON_ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026"}
# First path segments that never fall back to the SPA.
_RESERVED = frozenset({"api", "assets"})
_MAX_CACHED_ROOTS = 16
_PLACEHOLDER = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>FastStudio</title></head>
<body><h1>FastStudio UI is not built</h1>
<p>Run <code>pnpm -C frontend install &amp;&amp; pnpm -C frontend build</code>,
or install FastStudio from a wheel.</p></body></html>
"""


class AdminRootRecorder:
    """Record the admin mount root in the scope.

    Nested mounts (e.g. `/assets`) replace `root_path`; handlers that need the
    admin root (SPA fallback) read `ADMIN_ROOT_KEY` instead.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the admin application."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Store `root_path` (already proxy prefix + base_url at the mount)."""
        if scope["type"] == "http":
            scope[ADMIN_ROOT_KEY] = scope.get("root_path", "")
        await self.app(scope, receive, send)


def config_json(config: SpaConfig) -> str:
    """Serialize the config for embedding inside a `<script>` element.

    `<`, `>` and `&` are escaped so no value can close the element; non-ASCII
    (including U+2028/U+2029) is escaped by `ensure_ascii`.
    """
    text = json.dumps(config.model_dump(mode="json"), ensure_ascii=True, sort_keys=True)
    for char, escape in _JSON_ESCAPES.items():
        text = text.replace(char, escape)
    return text


def validate_template(template: str) -> str:
    """Return `template` if it has the head marker, else raise."""
    if HEAD_MARKER not in template:
        msg = f"FastStudio SPA index.html is missing the {HEAD_MARKER!r} marker."
        raise FastStudioError(msg)
    return template


def render_index(template: str, *, admin_root: str, title: str, max_list_offset: int) -> str:
    """Insert `<base href>`, the JSON config block and the page title.

    `admin_root` is the mount path as the browser sees it, including any proxy
    prefix (`root_path`), e.g. `/proxy/admin`.
    """
    config = SpaConfig(
        schema_version=SCHEMA_VERSION,
        base_url=admin_root,
        api_url=f"{admin_root}{API_PREFIX}",
        title=title,
        max_list_offset=max_list_offset,
    )
    head = (
        f'<base href="{html.escape(admin_root + "/", quote=True)}">\n'
        f'    <script type="application/json" id="fs-config">{config_json(config)}</script>'
    )
    rendered = validate_template(template).replace(HEAD_MARKER, head, 1)
    escaped_title = f"<title>{html.escape(title, quote=True)}</title>"
    return _TITLE.sub(lambda _: escaped_title, rendered, count=1)


class SpaSite:
    """The SPA's static directory, its index template and top-level files."""

    def __init__(self, static_dir: Path, settings: Settings) -> None:
        """Load the index template and an allowlist of top-level files once.

        Top-level files are served only by exact name from this allowlist, so
        requests never touch the filesystem (no case-folding aliases such as
        `INDEX.HTML`, no NUL/long-name errors, no symlinks or dotfiles).
        """
        self.settings = settings
        index = static_dir / "index.html"
        self.template = (
            validate_template(index.read_text(encoding="utf-8")) if index.is_file() else None
        )
        self.root_files = _top_level_files(static_dir)
        self._rendered: dict[str, str] = {}

    @staticmethod
    def admin_root(request: Request) -> str:
        """Mount path as seen by the browser (proxy prefix + base_url)."""
        root: str = request.scope.get(ADMIN_ROOT_KEY, request.scope.get("root_path", ""))
        return root

    def route_path(self, request: Request) -> str:
        """Path relative to the admin mount, without the leading slash."""
        path: str = request.scope["path"]
        root = self.admin_root(request)
        if root and path.startswith(root):
            path = path[len(root) :]
        return path.lstrip("/")

    def is_reserved(self, request: Request) -> bool:
        """Return True for API and asset paths, which never render the SPA."""
        return self.route_path(request).split("/", 1)[0] in _RESERVED

    def fallback(self, request: Request) -> Response | None:
        """Response for an unmatched GET/HEAD: a top-level file or the SPA shell."""
        if request.method not in {"GET", "HEAD"} or self.is_reserved(request):
            return None
        root_file = self.root_files.get(self.route_path(request))
        if root_file is not None:
            return FileResponse(root_file)
        if self.template is None:
            return HTMLResponse(_PLACEHOLDER, status_code=503)
        return HTMLResponse(self.index_for(self.admin_root(request)))

    def index_for(self, admin_root: str) -> str:
        """Render (and cache) the shell for one mount root."""
        if self.template is None:
            msg = "FastStudio SPA is not built; there is no index.html to render."
            raise FastStudioError(msg)
        cached = self._rendered.get(admin_root)
        if cached is None:
            cached = render_index(
                self.template,
                admin_root=admin_root,
                title=self.settings.title,
                max_list_offset=self.settings.max_list_offset,
            )
            if len(self._rendered) < _MAX_CACHED_ROOTS:
                self._rendered[admin_root] = cached
        return cached


def _top_level_files(static_dir: Path) -> dict[str, Path]:
    if not static_dir.is_dir():
        return {}
    files: dict[str, Path] = {}
    for entry in static_dir.iterdir():
        name = entry.name
        if name.startswith(".") or name.casefold() == "index.html" or entry.is_symlink():
            continue
        if entry.is_file():
            files[name] = entry
    return files
