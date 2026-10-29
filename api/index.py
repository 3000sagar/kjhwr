"""Vercel's Python function entrypoint for the read-only FastAPI app."""

from backend.app.main import app

__all__ = ["app"]
