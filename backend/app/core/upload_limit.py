"""
Early request-size rejection for the upload endpoint.

FastAPI parses a multipart body *before* it calls the route handler, so the
handler's own size check (uploads._read_bounded) can only run after the whole
body has been received and spooled. This pure-ASGI middleware looks at the
declared `Content-Length` of `POST {prefix}/projects/<id>/upload` and, if it is
clearly larger than any upload could be, answers 413 immediately without
reading a byte of the body.

What it is NOT:

* Not the authoritative check. The exact per-file-type limit depends on the
  filename inside the multipart body, which this layer cannot see, so the
  threshold here is the largest limit of any type (plus a little multipart
  overhead). The handler enforces the exact limit regardless.
* Not a defence against a client that omits or lies about Content-Length
  (e.g. chunked transfer). Such bodies are still bounded by the handler
  (memory) but not by this layer (bandwidth/disk) - a reverse-proxy
  `client_max_body_size`-style limit is the control for that.

Written against the bare ASGI interface (no Starlette/FastAPI imports) so it
can be unit-tested directly and has no framework-version coupling.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

# Multipart framing (boundary lines, part headers) is a few hundred bytes; a
# whole MiB of slack means a file that is exactly at the limit is never
# rejected here, only by the exact check in the handler.
MULTIPART_OVERHEAD_BYTES = 1024 * 1024


class UploadSizeLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        api_prefix: str,
        max_body_bytes: Callable[[], int],
    ) -> None:
        """`max_body_bytes` is a callable (not a number) so the limit follows
        the current settings on every request rather than being frozen when
        the app object was built."""
        self.app = app
        self._max_body_bytes = max_body_bytes
        self._path = re.compile(rf"^{re.escape(api_prefix)}/projects/[^/]+/upload/?$")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or not self._path.match(scope.get("path", ""))
        ):
            await self.app(scope, receive, send)
            return

        declared = _content_length(scope)
        limit = self._max_body_bytes()
        if declared is not None and declared > limit + MULTIPART_OVERHEAD_BYTES:
            await _send_413(send, limit)
            return
        await self.app(scope, receive, send)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name.lower() == b"content-length":
            try:
                declared = int(value)
            except ValueError:
                return None  # malformed: leave it to the framework
            return declared if declared >= 0 else None
    return None


async def _send_413(send: Send, limit_bytes: int) -> None:
    limit_mb = limit_bytes // (1024 * 1024)
    body = json.dumps(
        {
            "error": {
                "code": "file_too_large",
                "message": f"This upload is larger than the {limit_mb} MB maximum file size.",
                "details": {"limit_bytes": limit_bytes, "limit_mb": limit_mb},
            }
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                # The client may still be mid-upload; do not keep the
                # connection alive expecting a next request on it.
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
