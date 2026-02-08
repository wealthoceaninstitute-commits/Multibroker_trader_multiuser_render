"""
Authentication package for the multi‑user backend.

This package exposes a FastAPI router implementing registration,
login and simple JWT based session handling.  It also re‑exports
helpers that can be used by other modules to authenticate
requests and compute per‑user storage locations.

Usage in the main application::

    from auth.auth_router import router as auth_router
    app.include_router(auth_router, prefix="/auth")

The ``auth_utils`` module defines helper functions such as
``get_current_user`` which return the current logged‑in userid from
the Authorization header.  Import and use these functions to
secure your own route handlers.
"""

from .auth_router import router  # noqa: F401
from .auth_utils import get_current_user, get_current_user_optional  # noqa: F401