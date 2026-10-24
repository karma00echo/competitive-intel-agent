"""Offline search-to-page handoff; candidates are not verified facts."""
from competitive_intel.domain.source_discovery import discover_sources
from competitive_intel.domain.sources import CompetitorIdentity,SourceType,DiscoveryStatus
from competitive_intel.domain.search import SearchResult

class NoSearch:
    def search(self, request):
        raise AssertionError('Existing search results must not trigger paid search')

def discover(results, html='<main>Product</main>'):
    return discover_sources(CompetitorIdentity('Atlas','atlas'), 'https://atlas.example/',html,
        (SourceType.HOMEPAGE,SourceType.FEATURES,SourceType.PRICING),provider=NoSearch(),
        max_supplemental_searches=0,max_pages=3,existing_results=tuple(results))

def hit(url,title='Pricing'):
    return SearchResult(title,url,'Atlas product',1,'offline','Atlas pricing')

def test_reuse_verified_domain_candidate_without_new_search():
    rows=discover([hit('https://atlas.example/pricing')])
    price=next(x for x in rows if x.source_type==SourceType.PRICING)
    assert price.status==DiscoveryStatus.FOUND and price.needs_validation
    assert price.candidate_url=='https://atlas.example/pricing'

def test_other_domains_and_homepage_cannot_fill_missing_price():
    rows=discover([hit('https://other.example/pricing'),hit('https://atlas.example/')])
    assert rows[-1].status==DiscoveryStatus.NOT_FOUND

def test_equal_candidates_remain_ambiguous():
    rows=discover([hit('https://atlas.example/price-a'),hit('https://atlas.example/price-b')])
    assert rows[-1].status==DiscoveryStatus.AMBIGUOUS

def test_navigation_retains_priority():
    rows=discover([hit('https://atlas.example/price-b')],'<main><a href="/pricing">Pricing</a></main>')
    assert rows[-1].candidate_url=='https://atlas.example/pricing'
