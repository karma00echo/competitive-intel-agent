"""Formal data pages share editorial styling without changing API contracts."""
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from competitive_intel.web import create_app
from test_web_api import _settings, _wait


def test_data_shell_and_audit_routes_preserve_chat(persistence):
    with TestClient(create_app(settings=_settings(), persistence=persistence)) as client:
        for route in ['/signals', '/competitors', '/reports', '/developer', '/competitors/1', '/reports/1', '/developer/runs/1', '/runs/1']:
            soup = BeautifulSoup(client.get(route).text, 'html.parser')
            assert 'editorial-data' in soup.body['class']
            assert not soup.select('.ed-hero')
            assert soup.select_one('a[aria-current="page"]')
        for route in ['/', '/analyst']:
            soup = BeautifulSoup(client.get(route).text, 'html.parser')
            assert 'editorial-data' not in soup.body.get('class', [])
            assert soup.select_one('#chat-form') and soup.select_one('#chat-input')
        dev = BeautifulSoup(client.get('/developer').text, 'html.parser')
        assert dev.select_one('#audit-history')
        assert dev.select_one('details #analysis-form')
        assert not dev.select_one('.audit-launch').has_attr('open')
        audit = BeautifulSoup(client.get('/developer/runs/1').text, 'html.parser')
        for section in ['audit-events', 'audit-tools', 'audit-evidence', 'audit-provider', 'audit-result', 'audit-error', 'audit-retry']:
            assert audit.select_one('#' + section)
        assert client.get('/api/runs').json()['data']['items'] == []
        for asset in ['audit.js', 'data-pages.css']:
            assert client.get('/static/' + asset).status_code == 200
        assert 'innerHTML' not in client.get('/static/audit.js').text


def test_audit_reuses_persisted_success_and_failed_records(persistence):
    with TestClient(create_app(settings=_settings(), persistence=persistence)) as client:
        accepted = client.post('/api/analyses', json={'competitor_name':'Notion','search_provider':'fixture'})
        rid = accepted.json()['run_id']
        assert _wait(client,rid)['final_state'] == 'COMPLETED'
        data = client.get(f'/api/workspace/runs/{rid}').json()['data']
        assert data['events'] and data['tool_calls'] and data['facts'] and data['report']
        assert data['provider_summary']['search_provider'] == 'fixture'
        for route in [f'/developer/runs/{rid}', f'/runs/{rid}']:
            soup = BeautifulSoup(client.get(route).text,'html.parser')
            assert soup.body['data-resource-id'] == str(rid)
            assert soup.body['data-page'] == 'audit'
        assert len(client.get('/api/runs').json()['data']['items']) == 1
        with persistence.transaction() as session:
            failed = persistence.agent_runs.create(session,input_name='Unknown',normalized_input='unknown')
            persistence.agent_runs.finish(session,failed,status='FAILED',current_state='FAILED',error_code='NO_SOURCE',error_message='No verified source')
        data = client.get(f'/api/workspace/runs/{failed}').json()['data']
        assert data['run']['final_state'] == 'FAILED'
        assert data['run']['errors'] and data['report'] is None
        assert client.get('/api/workspace/runs/99999999').status_code == 404
