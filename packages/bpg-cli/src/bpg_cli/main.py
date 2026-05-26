"""Transitional CLI entrypoint that delegates to the legacy package."""

from bpg.cli import app, main

__all__ = ["app", "main"]
