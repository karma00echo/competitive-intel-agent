"""Shared shell and homepage regression tests; no public network."""
from pathlib import Path

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from competitive_intel.web import create_app
from test_web_api import _settings


def test_editorial_shell_uses_real_routes_without_home_append(persistence):
    routes = ["/", "/signals", "/analyst", "/competitors", "/reports", "/developer"]
    with TestClient(create_app(settings=_settings(), persistence=persistence)) as client:
        for route in routes:
            response = client.get(route)
            assert response.status_code == 200
            soup = BeautifulSoup(response.text, "html.parser")
            links = soup.select('.ed-nav a')
            assert [a['href'] for a in links] == routes
            assert [a['href'] for a in links if a.get('aria-current') == 'page'] == [route]
            assert bool(soup.select('.ed-hero')) == (route == '/')
            assert not soup.select('#detail')
            assert 'content.js' not in response.text
        home = BeautifulSoup(client.get('/').text, 'html.parser')
        assert [a['href'] for a in home.select('.ed-entry')] == ['/competitors', '/signals', '/reports']
        assert home.select_one('.ed-analyst-entry a')['href'] == '/analyst'
        assert home.select_one('#product-content')
        assert 'Real natural-language AgentProvider' in home.get_text()
        assert home.select_one('.ed-botanical')['aria-hidden'] == 'true'
        data = client.get('/api/command-center').json()['data']
        assert data['metrics']['competitor_count'] == 0
        assert data['recent_signals'] == []
        for asset in ['editorial.css', 'editorial/botanical.svg', 'editorial/landscape.svg']:
            assert client.get('/static/' + asset).status_code == 200


def test_editorial_assets_are_the_approved_assets():
    root = Path(__file__).resolve().parents[2]
    for name in ['botanical.svg', 'landscape.svg']:
        original = (root / 'ui-demos/final-editorial-demo' / name).read_text(encoding='utf-8').strip()
        migrated = (root / 'src/competitive_intel/web/static/editorial' / name).read_text(encoding='utf-8').strip()
        assert migrated == original
