"""Provider-neutral search infrastructure."""

from .base import SearchProvider
from .factory import create_search_provider
from .search_web import search_web

__all__ = ["SearchProvider", "create_search_provider", "search_web"]
