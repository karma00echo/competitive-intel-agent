"""Chat reuses existing commands and real run projections, entirely offline."""
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from competitive_intel.web import create_app
from test_web_api import _settings, _wait


def test_chat_routes_and_replay_are_read_only(persistence):
    with TestClient(create_app(settings=_settings(), persistence=persistence)) as client:
        for route in ['/', '/analyst', '/?conversation=missing', '/?run=99999']:
            soup = BeautifulSoup(client.get(route).text, 'html.parser')
            assert soup.select_one('textarea#chat-input')['maxlength'] == '250'
            assert soup.select_one('#chat-conversation').has_attr('hidden')
            assert len(soup.select('[data-prompt]')) == 3
            assert not soup.select('#product-content')
        assert 'chat-history' in client.get('/history').text
        assert client.get('/api/runs').json()['data']['items'] == []
        assert client.get('/api/workspace/runs/99999').status_code == 404
        assert 'product-content' in client.get('/command-center').text
        for asset in ['chat.js', 'chat.css']:
            assert client.get('/static/' + asset).status_code == 200


def test_chat_fixture_command_run_report_and_replay(persistence):
    with TestClient(create_app(settings=_settings(), persistence=persistence)) as client:
        command = client.get('/api/analyst/command', params={'text': '帮我分析 Notion 这个产品。'}).json()['data']
        assert command == {'action': 'analyze', 'name': 'Notion'}
        # Parsing and rendering never starts a run; explicit confirmation does.
        assert client.get('/api/runs').json()['data']['items'] == []
        accepted = client.post('/api/analyses', json={'competitor_name': command['name'], 'search_provider': 'fixture'})
        rid = accepted.json()['run_id']
        assert _wait(client, rid)['final_state'] == 'COMPLETED'
        data = client.get(f'/api/workspace/runs/{rid}').json()['data']
        assert data['provider_summary']['search_provider'] == 'fixture'
        assert data['events'] and data['tool_calls'] and data['report']
        assert data['facts'] and all(f['evidence_excerpt'] and f['source_url'] for f in data['facts'])
        assert client.get(f"/reports/{data['report']['report_id']}").status_code == 200
        for _ in range(2):
            assert client.get(f'/?run={rid}').status_code == 200
            assert client.get(f'/api/workspace/runs/{rid}').status_code == 200
        assert len(client.get('/api/runs').json()['data']['items']) == 1


def test_chat_failed_run_and_real_mode_isolation(persistence):
    with persistence.transaction() as session:
        rid = persistence.agent_runs.create(session, input_name='Failed product', normalized_input='failed product')
        persistence.agent_runs.finish(session, rid, status='FAILED', current_state='FAILED', error_code='TEST_FAILURE', error_message='No verified source')
    with TestClient(create_app(settings=_settings(), persistence=persistence)) as client:
        data = client.get(f'/api/workspace/runs/{rid}').json()['data']
        assert data['run']['final_state'] == 'FAILED'
        assert data['run']['errors'] and data['report'] is None and data['facts'] == []
        assert client.post('/api/analyses', json={'competitor_name': 'Notion', 'search_provider': 'serper', 'skip_fact_extraction': False}).status_code == 422
        assert client.get('/api/analyst/command', params={'text':'比较 Notion 和 Asana 的定价及功能。'}).json()['data']['action'] == 'unsupported'
