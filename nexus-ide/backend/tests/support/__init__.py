"""Shared, production-free test support for the group-runtime closeout.

Nothing in this package is imported by the application.  It exists so the
independent end-to-end tests can drive the *real* FastAPI/uvicorn backend with
a scripted, loopback model provider while remaining deterministic.
"""
