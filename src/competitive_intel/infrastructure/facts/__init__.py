"""Fact-extraction provider infrastructure."""

from .base import FactExtractionProvider, FactExtractionRequest, FactExtractionResponse
from .fixture import FixtureFactExtractionProvider

__all__ = [
    "FactExtractionProvider", "FactExtractionRequest", "FactExtractionResponse",
    "FixtureFactExtractionProvider",
]
