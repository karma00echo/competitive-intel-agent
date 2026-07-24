"""Deterministic competitor-name normalization."""

from __future__ import annotations

import re
import unicodedata

from .sources import CompetitorIdentity


SPACE = re.compile(r"\s+")


def normalize_competitor_name(
    original_name: str, aliases: tuple[str, ...] = ()
) -> CompetitorIdentity:
    original = SPACE.sub(" ", unicodedata.normalize("NFKC", original_name)).strip()
    if not original:
        raise ValueError("competitor name must not be empty")
    normalized = original.casefold()
    normalized_aliases = tuple(
        dict.fromkeys(
            SPACE.sub(" ", unicodedata.normalize("NFKC", alias)).strip()
            for alias in aliases
            if alias.strip()
        )
    )
    return CompetitorIdentity(original, normalized, normalized_aliases)
