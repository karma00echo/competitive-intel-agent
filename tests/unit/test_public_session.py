import pytest
import requests

from competitive_intel.infrastructure.http.public_session import PublicSession, PublicAdapter, public_address
from competitive_intel.infrastructure.budgeted_transport import BudgetedSession
from competitive_intel.domain.task_budget import TaskBudget, BudgetLimits, BudgetExhausted


@pytest.mark.parametrize('ip', ['127.0.0.1','10.1.1.1','172.16.0.1','192.168.1.1',
                              '169.254.169.254','::1','fc00::1','fe80::1','224.0.0.1','0.0.0.0'])
def test_nonpublic_addresses_denied(ip):
    with pytest.raises(requests.exceptions.InvalidURL):
        public_address('https://example.com/', lambda *a, **k: [(0,0,0,'',(ip,443))])


@pytest.mark.parametrize('url', ['file:///etc/passwd','https://user:pass@example.com/',
                               'http://example.com:22/','ftp://example.com/'])
def test_unsupported_urls(url):
    with pytest.raises(requests.exceptions.InvalidURL):
        public_address(url)


def test_mixed_dns_is_denied():
    with pytest.raises(requests.exceptions.InvalidURL):
        public_address('https://example.com', lambda *a, **k:
                       [(0,0,0,'',('8.8.8.8',443)),(0,0,0,'',('127.0.0.1',443))])


def test_tls_connection_pins_checked_ip_and_preserves_hostname(monkeypatch):
    calls = []
    def resolve(url):
        calls.append(url)
        return '8.8.8.8'
    monkeypatch.setattr('competitive_intel.infrastructure.http.public_session.public_address', resolve)
    adapter = PublicAdapter()
    prepared = requests.Request('GET','https://example.com/').prepare()
    pool = adapter.get_connection_with_tls_context(prepared, True)
    assert pool.host == '8.8.8.8'
    assert pool.assert_hostname == 'example.com'
    assert pool.conn_kw['server_hostname'] == 'example.com'
    assert len(calls) == 1
    adapter.close()


def test_redirect_revalidated_before_connect_and_budget_shared(monkeypatch):
    addresses = []
    def resolve(host, *a, **k):
        addresses.append(host)
        return [(0,0,0,'',('127.0.0.1' if host == 'localhost' else '8.8.8.8',443))]
    monkeypatch.setattr('socket.getaddrinfo', resolve)
    sent = []
    def send(self, request, **kwargs):
        # Exercise the production adapter's address check without any socket.
        self.get_connection_with_tls_context(request, True)
        sent.append(request)
        response = requests.Response()
        response.status_code = 302
        response.url = request.url
        response.request = request
        response.headers['Location'] = 'https://localhost/private'
        response._content = b''
        response._content_consumed = True
        return response
    monkeypatch.setattr(PublicAdapter, 'send', send)
    budget = TaskBudget(BudgetLimits(fetches=2))
    session = BudgetedSession(budget, 'fetches')
    with pytest.raises(requests.exceptions.InvalidURL):
        session.get('https://example.com/', headers={'Authorization':'secret','Cookie':'secret'})
    assert addresses == ['example.com','localhost']
    assert len(sent) == 1
    assert not {'Authorization','Cookie'}.intersection(sent[0].headers)
    assert budget.used['fetches'] == 2
    with pytest.raises(BudgetExhausted):
        session.get('https://example.com/')
    assert len(sent) == 1
    session.close()


def test_no_ambient_credentials_or_proxy():
    session = PublicSession()
    assert session._session.trust_env is False
    assert isinstance(session._session.get_adapter('https://example.com'), PublicAdapter)
    session.close()
