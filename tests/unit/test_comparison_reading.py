from copy import deepcopy
from types import SimpleNamespace

import pytest

from competitive_intel.domain.comparison_presentation import capability_rows, reading_view
from competitive_intel.domain.competitive_findings import build_findings
from competitive_intel.domain.facts import CandidateFact, FactCategory
from competitive_intel.infrastructure.facts.llm_provider import _ground
from competitive_intel.services.competitive_report_service import render_competitive_report
from test_competitive_matrix import row, matrix


def features():
    def value(name, description):
        return dict(feature_name=name, normalized_feature_name=name.casefold(), feature_description=description,
                    feature_category="OTHER", availability=None, related_plan=None, status="UNKNOWN")
    return matrix({1: [row(1, value=value("AI agents", "AI agents handle issues."), quote="AI agents handle issues.")],
                   2: [row(2, value=value("Powered by AI", "Powered by AI summarizes text."), quote="Powered by AI summarizes text.")]},
                  products=None)


def analysis(m):
    return dict(matrix=m, status="PARTIAL", synthesis_status="NOT_RUN", limitations=[], issues=[], conclusions=[])


def test_semantic_category_does_not_claim_equivalence_or_absence():
    m=features();m['products']=m['products'][:2]
    rows=capability_rows(m)
    assert rows[0]['status']=='SHARED_CATEGORY'
    findings=build_findings(m)['findings']
    assert findings[0]['kind']=='SHARED_CAPABILITY_IMPLEMENTATIONS'
    assert 'not equivalent' in findings[0]['text']
    assert not any(f['kind']=='DOCUMENTED_DIFFERENTIATOR_CANDIDATE' for f in findings)
    assert set(findings[0]['fact_ids'])==set(m['facts'])


def test_conflict_and_third_product_gap_never_become_shared():
    m=features()
    assert capability_rows(m)[0]['status']=='ONE_SIDED_EVIDENCE'
    next(iter(m['facts'].values()))['verification_status']='SOURCE_CONFLICT'
    assert capability_rows(m)[0]['status']=='SOURCE_CONFLICT'
    assert not any(f['kind']=='SHARED_CAPABILITY_IMPLEMENTATIONS' for f in build_findings(m)['findings'])


def test_language_rendering_preserves_sources_and_partial_status():
    a=analysis(features());before=deepcopy(a)
    zh=SimpleNamespace(output_language='zh-CN'); en=SimpleNamespace(output_language='en')
    view=reading_view(zh,a)
    assert view['language']=='zh-CN' and view['status']=='PARTIAL'
    assert view['sections'][0]['heading']=='执行摘要'
    assert [e['quote'] for e in view['references']]==[e['quote'] for e in a['matrix']['evidence'].values()]
    assert '部分报告' in render_competitive_report(zh,a)
    assert 'Executive summary' in render_competitive_report(en,a)
    assert a==before


@pytest.mark.parametrize('quote,ok', [('Pro 10 per user/month Billed yearly',True),
                                     ('Pro 10 per user/month',False),
                                     ('Pro 10 per user/month billed monthly',False)])
def test_yearly_alias_requires_explicit_billing_evidence(quote,ok):
    v=dict(plan_name='Pro',amount='10',currency=None,billing_period='MONTH',billing_unit='USER',
           billing_commitment='ANNUAL_BILLING',region=None,tax_status='UNKNOWN',public_status='PUBLIC')
    fact=CandidateFact(FactCategory.PRICE,v,quote,quote,.9)
    if ok: _ground(fact,quote,'https://alpha.example/pricing')
    else:
        with pytest.raises(ValueError): _ground(fact,quote,'https://alpha.example/pricing')


def test_negative_name_not_inferred_from_unrelated_description():
    m=features();f=next(iter(m['facts'].values()));f['value']['feature_name']='Email'
    f['value']['feature_description']='AI agents handle issues.'
    assert any(r['category'].startswith('unmapped:') for r in capability_rows(m))


def test_annotations_are_literal_spans_with_evidence_references():
    m=features();view=reading_view(SimpleNamespace(output_language='zh-CN'),analysis(m))
    assert view['annotations']
    for annotation in view['annotations']:
        assert annotation['source_span'] in m['evidence'][annotation['evidence_id']]['quote']
        assert annotation['fact_id'] in m['facts']


def test_different_observation_days_are_not_semantic_common_claims():
    m=features();m['products']=m['products'][:2]
    list(m['evidence'].values())[1]['collected_at']='2026-01-02T00:00:00+00:00'
    assert capability_rows(m)[0]['status']=='TIME_INCOMPARABLE'
    assert not any(f['kind']=='SHARED_CAPABILITY_IMPLEMENTATIONS' for f in build_findings(m)['findings'])


def test_announced_capabilities_are_not_claimed_as_shared_availability():
    m=features();m['products']=m['products'][:2]
    next(iter(m['facts'].values()))['value']['status']='COMING_SOON'
    assert capability_rows(m)[0]['status']=='AVAILABILITY_UNCERTAIN'
    assert not any(f['kind']=='SHARED_CAPABILITY_IMPLEMENTATIONS' for f in build_findings(m)['findings'])
