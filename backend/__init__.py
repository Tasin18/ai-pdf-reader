"""Backend package initializer.

Exposes the Flask app factory for convenient imports:
	from backend import create_app
"""

from .app import create_app  # noqa: F401
