"""Browser-shaped wire contract; entirely offline, no MySQL or providers."""
import json
import subprocess
import traceback
from contextlib import contextmanager
from types import SimpleNamespace
import pytest
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from competitive_intel.config import Settings, DatabaseSettings
from competitive_intel.web.app import create_app


@pytest.mark.parametrize('mode', ['success', 'timeout', 'blocked'])
def test_shipped_chat_fee_confirmation_and_replay(mode):
    result = subprocess.run(['node', 'tests/chat_workflow_submission.cjs', mode],
                            capture_output=True, text=True, encoding='utf-8', check=True)
    data = json.loads(result.stdout)
    assert len([r for r in data['requests'] if r['method'] == 'POST']) == (0 if mode == 'blocked' else 1)


def test_browser_wire_reproduces_422_and_fixed_request_reaches_start_once(monkeypatch):
    @contextmanager
    def transaction():
        yield None
    calls, errors = [], []
    store = SimpleNamespace(transaction=transaction, reports=SimpleNamespace(require_competitive_schema=lambda tx: None))
    manager = SimpleNamespace(shutdown=lambda: None,
                              start_workflow=lambda text, workflow: calls.append(text) or 42)
    from dataclasses import replace
    settings = Settings(database=DatabaseSettings('localhost', 3306, 'unused_test', 'unused', ''))
    settings = replace(settings, search=replace(settings.search, api_key='offline'),
                       llm=replace(settings.llm, api_key='offline', model='offline', endpoint='https://offline.invalid'))
    app = create_app(settings=settings, persistence=store, task_manager=manager)
    app.state.workflow_context_factory = lambda: SimpleNamespace(close=lambda: None)
    @app.exception_handler(RequestValidationError)
    async def capture(request, exc):
        assert 'fastapi' in ''.join(traceback.format_exception(exc))
        errors.extend(exc.errors())
        return JSONResponse(status_code=422, content={'error': exc.errors()[0]['msg']})
    monkeypatch.setenv('WORKFLOW_PAID_ENABLED', '1')
    for name in ('RESEARCH_SEARCH_COST_MICROUSD','RESEARCH_INPUT_COST_MICROUSD_PER_MILLION','RESEARCH_OUTPUT_COST_MICROUSD_PER_MILLION'):
        monkeypatch.setenv(name, '1000')
    wire = json.loads(subprocess.run(['node','tests/chat_workflow_submission.cjs','success'],
                       capture_output=True,text=True,encoding='utf-8',check=True).stdout)
    post = next(r for r in wire['requests'] if r['method']=='POST')
    with TestClient(app) as client:
        # Fetch assigns this MIME type to a string body when JSON headers are absent.
        bad = client.post(post['url'],content=post['body'].encode(),headers={'Content-Type':'text/plain;charset=UTF-8'})
        assert bad.status_code == 422 and not calls
        assert errors[0]['type']=='model_attributes_type' and errors[0]['loc']==('body',)
        assert isinstance(errors[0]['input'], bytes)
        assert bad.json()['error']=='Input should be a valid dictionary or object to extract fields from'
        payload=json.loads(post['body'])
        assert client.post(post['url'],json={**payload,'allow_paid':False}).status_code==403
        assert client.post(post['url'],json={**payload,'text':123}).status_code==422
        assert not calls
        good=client.post(post['url'],content=post['body'].encode(),headers={'Content-Type':post['contentType']})
        assert good.status_code==202 and good.json()['data']['run_id']==42
        assert calls==[payload['text']]
