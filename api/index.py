"""Vercel entry point for the FastAPI dashboard.

The full app remains a normal ASGI application so the same source works on
Chabokan, Render, Docker, and Vercel.  Vercel imports this module as a Python
Function and serves the exported ``app`` object.
"""

from app.main import app

__all__ = ["app"]
