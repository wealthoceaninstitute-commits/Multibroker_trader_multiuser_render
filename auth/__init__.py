"""
Authentication package for CT‑FastAPI WebApp.

This package exposes a router for user registration, login and
profile endpoints as well as utility functions for JWT encoding
and user‑specific storage.  It is self‑contained and does not
depend on external authentication providers.  To enable
authentication include the router in your FastAPI app::

    from auth.auth_router import router as auth_router
    app.include_router(auth_router, prefix="/auth")
"""

# Re‑export the router so ``from auth import auth_router`` works.
from .auth_router import router as auth_router  # noqa: F401
