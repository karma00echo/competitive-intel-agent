from datetime import datetime
from dataclasses import replace

import pytest

from competitive_intel.domain.search import SearchResponse, SearchResult
from competitive_intel.domain.sources import SourceType, DiscoveryStatus, SourceDiscoveryLimits
from competitive_intel.domain.task_budget import TaskBudget, BudgetLimits, BudgetExhausted
from competitive_intel.domain.webpage import FetchPageResult, FetchStatus
from competitive_intel.services.source_discovery_service import SourceDiscoveryService


BASE = 'https://atlas.example'


class Search:
    name = 'offline'

    def search(self, request):
        return SearchResponse(request, tuple(SearchResult('Atlas', BASE + path, 'Atlas product', i + 1,
            self.name, request.query) for i, path in enumerate(('/', '/docs', '/features', '/pricing'))), self.name)


class Pages:
    def __init__(self, failed=(), budget=None):
        self.failed, self.budget, self.calls = failed, budget, []

    def fetch(self, request):
        if self.budget:
            self.budget.reserve(fetches=1)
        self.calls.append(request.url)
        path = request.url.removeprefix(BASE)
        status = FetchStatus.JS_UNSUPPORTED if path in self.failed else FetchStatus.SUCCESS
        html = (f'<html><head><title>Atlas product</title><link rel="canonical" href="{request.url}"></head>'
                '<body><main><h1>Atlas product</h1><p>Atlas supports projects, documents and automated workflows.</p>'
                '<a href="/docs">Docs</a><a href="/features">Features</a><a href="/pricing">Pricing</a>'
                '<h2>Pro plan</h2><div>$10 USD per user/month billed annually</div></main></body></html>')
        return FetchPageResult(request.url, request.url, (request.url,), 200, 'text/html', 'Atlas',
                               html if status == FetchStatus.SUCCESS else '<div id="app"></div>',
                               datetime(2026, 1, 1), status)


def service(persistence, pages):
    return SourceDiscoveryService(persistence, Search(), pages,
        limits=SourceDiscoveryLimits(max_pages=3, max_supplemental_searches=0))


def test_failed_first_feature_candidate_uses_second_and_persists_ownership(persistence):
    pages = Pages(failed=('/docs',))
    result = service(persistence, pages).discover('Atlas')
    feature = next(d for d in result.discoveries if d.source_type == SourceType.FEATURES)
    assert feature.status == DiscoveryStatus.FOUND
    assert feature.candidate_url == BASE + '/features'
    assert pages.calls.count(BASE + '/docs') == 1
    assert len(result.saved_source_ids) == 3
    with persistence.transaction() as tx:
        saved = [persistence.sources.get(tx, sid) for sid in result.saved_source_ids]
    assert all(s['verification_status'] == 'VERIFIED' and s['domain'] in ('atlas.example',) for s in saved)


def test_two_equally_valid_candidates_remain_ambiguous(persistence):
    result = service(persistence, Pages()).discover('Atlas')
    feature = next(d for d in result.discoveries if d.source_type == SourceType.FEATURES)
    assert feature.status == DiscoveryStatus.AMBIGUOUS
    assert len(result.saved_source_ids) == 2


def test_verified_aliases_with_same_final_page_are_not_ambiguous(persistence):
    class Alias(Pages):
        def fetch(self, request):
            result = super().fetch(request)
            if request.url.endswith('/features'):
                return replace(result, final_url=BASE + '/docs')
            return result
    result = service(persistence, Alias()).discover('Atlas')
    feature = next(d for d in result.discoveries if d.source_type == SourceType.FEATURES)
    assert feature.status == DiscoveryStatus.FOUND
    assert len(result.saved_source_ids) == 3


def test_identity_shell_falls_back_within_domain_and_reuses_page(persistence):
    pages = Pages(failed=('/',))
    result = service(persistence, pages).discover('Atlas')
    assert result.official_domain == 'atlas.example'
    assert pages.calls[:2] == [BASE + '/', BASE + '/docs']
    assert pages.calls.count(BASE + '/docs') == 1


def test_fallback_cannot_reset_shared_budget(persistence):
    budget = TaskBudget(BudgetLimits(fetches=1))
    pages = Pages(failed=('/',), budget=budget)
    with pytest.raises(BudgetExhausted):
        service(persistence, pages).discover('Atlas')
    assert pages.calls == [BASE + '/']
    assert budget.used['fetches'] == 1


def test_empty_first_feature_candidate_uses_second(persistence):
    class EmptyPage(Pages):
        def fetch(self, request):
            result = super().fetch(request)
            return replace(result, raw_html='<html><body></body></html>') if request.url.endswith('/docs') else result
    result = service(persistence, EmptyPage()).discover('Atlas')
    feature = next(d for d in result.discoveries if d.source_type == SourceType.FEATURES)
    assert feature.status == DiscoveryStatus.FOUND
    assert feature.candidate_url == BASE + '/features'


def test_cross_domain_redirect_never_becomes_owned_feature_source(persistence):
    class Redirect(Pages):
        def fetch(self, request):
            result = super().fetch(request)
            if request.url.endswith(('/docs', '/features')):
                return replace(result, final_url='https://another.example/features')
            return result
    result = service(persistence, Redirect()).discover('Atlas')
    feature = next(d for d in result.discoveries if d.source_type == SourceType.FEATURES)
    assert feature.status == DiscoveryStatus.AMBIGUOUS
    assert len(result.saved_source_ids) == 2
