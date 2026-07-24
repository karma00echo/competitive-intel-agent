"""Bounded deterministic search-query generation."""

from __future__ import annotations

from .search import SearchIntent
from .sources import CompetitorIdentity


SUFFIXES = {
    "zh": {
        SearchIntent.OFFICIAL_SITE: ("官网", "官方网站"),
        SearchIntent.FEATURES: ("功能", "产品功能", "解决方案"),
        SearchIntent.PRICING: ("定价", "价格 套餐", "版本"),
        SearchIntent.CHANGELOG: ("产品更新", "更新日志", "发布记录"),
    },
    "en": {
        SearchIntent.OFFICIAL_SITE: ("official website", "official"),
        SearchIntent.FEATURES: ("features", "product", "solutions"),
        SearchIntent.PRICING: ("pricing", "plans"),
        SearchIntent.CHANGELOG: ("changelog", "release notes", "what's new"),
    },
}


def _language(identity: CompetitorIdentity, language: str | None) -> str:
    if language and language.lower().startswith("zh"):
        return "zh"
    if any("\u4e00" <= char <= "\u9fff" for char in identity.original_name):
        return "zh"
    return "en"


def generate_search_queries(
    identity: CompetitorIdentity,
    intent: SearchIntent,
    *,
    language: str | None = None,
    official_domain: str | None = None,
    max_queries: int = 3,
) -> tuple[str, ...]:
    if max_queries < 1:
        return ()
    lang = _language(identity, language)
    base = identity.original_name
    if official_domain and intent != SearchIntent.OFFICIAL_SITE:
        terms = SUFFIXES[lang][intent]
        candidates = [f"site:{official_domain} {term}" for term in terms]
    else:
        candidates = [f"{base} {term}" for term in SUFFIXES[lang][intent]]
    return tuple(dict.fromkeys(candidates))[:max_queries]
