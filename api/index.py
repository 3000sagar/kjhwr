"""Vercel's Python function entrypoint for the read-only FastAPI app."""

from urllib.parse import parse_qsl, urlencode

from starlette.types import ASGIApp, Receive, Scope, Send

from backend.app.main import app


class VercelPathMiddleware:
    """Restore the intended API path when Vercel rewrites it to this function."""

    def __init__(self, asgi_app: ASGIApp) -> None:
        self.asgi_app = asgi_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.asgi_app(scope, receive, send)
            return

        params = parse_qsl(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)
        path_values = [value for key, value in params if key == "__path"]
        if not path_values:
            await self.asgi_app(scope, receive, send)
            return

        # Use the route suffix carried in the query because rewrite path handling varies by runtime.
        path = "/api/" + path_values[-1].lstrip("/")
        forwarded_scope = dict(scope)
        forwarded_scope["path"] = path
        forwarded_scope["raw_path"] = path.encode("utf-8")
        forwarded_scope["query_string"] = urlencode(
            [(key, value) for key, value in params if key != "__path"]
        ).encode("ascii")
        await self.asgi_app(forwarded_scope, receive, send)


app.add_middleware(VercelPathMiddleware)

__all__ = ["app"]
