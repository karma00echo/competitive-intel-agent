"""Public-only, credential-free HTTP with validated IP pinning on every hop."""
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import requests
import urllib3


def public_address(url, resolver=None):
    parts = urlsplit(url)
    if (parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username
            or parts.password or parts.port not in (None, 80 if parts.scheme == 'http' else 443)):
        raise requests.exceptions.InvalidURL('PUBLIC_URL_REQUIRED')
    resolver = resolver or socket.getaddrinfo
    try:
        answers = resolver(parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80),
                           type=socket.SOCK_STREAM)
        ips = {item[4][0] for item in answers}
        if not ips or any(not ipaddress.ip_address(ip).is_global
                          or ipaddress.ip_address(ip).is_multicast
                          or ipaddress.ip_address(ip).is_reserved for ip in ips):
            raise requests.exceptions.InvalidURL('NON_PUBLIC_ADDRESS')
    except socket.gaierror as exc:
        raise requests.exceptions.ConnectionError('PUBLIC_DNS_FAILED') from exc
    return sorted(ips)[0]


class PublicAdapter(requests.adapters.HTTPAdapter):
    def __init__(self):
        super().__init__(max_retries=0)
        self._pinned_pools = []

    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        if proxies or cert or verify is False:
            raise requests.exceptions.InvalidURL('PUBLIC_TRANSPORT_POLICY')
        parts = urlsplit(request.url)
        address = public_address(request.url)
        port = parts.port or (443 if parts.scheme == 'https' else 80)
        if parts.scheme == 'https':
            pool = urllib3.HTTPSConnectionPool(address, port, server_hostname=parts.hostname,
                                             assert_hostname=parts.hostname, cert_reqs='CERT_REQUIRED', retries=False)
        else:
            pool = urllib3.HTTPConnectionPool(address, port, retries=False)
        # Numeric pool host prevents DNS rebinding between validation and connect.
        self._pinned_pools.append(pool)
        return pool

    def close(self):
        for pool in self._pinned_pools:
            pool.close()
        self._pinned_pools.clear()
        super().close()


class _ManualRedirectSession(requests.Session):
    def resolve_redirects(self, response, request, **kwargs):
        # requests otherwise consumes redirect bodies even with allow_redirects=False.
        # Redirect ownership belongs to PublicSession / BudgetedSession only.
        return iter(())


class PublicSession:
    def __init__(self):
        self._session = _ManualRedirectSession()
        self._session.trust_env = False  # No netrc or inherited proxy credentials.
        self._session.mount('https://', PublicAdapter())
        self._session.mount('http://', PublicAdapter())

    def get(self, url, **kwargs):
        follow = kwargs.pop('allow_redirects', True)
        history = []
        for _ in range(6):
            parts = urlsplit(url)
            self._session.cookies.clear()
            headers = {k: v for k, v in kwargs.get('headers', {}).items()
                       if k.lower() not in {'cookie', 'authorization', 'proxy-authorization', 'host'}}
            headers['Host'] = parts.netloc
            response = self._session.get(url, **{**kwargs, 'headers': headers, 'allow_redirects': False})
            if not follow or response.status_code not in {301, 302, 303, 307, 308} or not response.headers.get('Location'):
                response.history = history
                return response
            history.append(response)
            url = urljoin(url, response.headers['Location'])
            response.close()
        raise requests.exceptions.TooManyRedirects('Bounded redirect limit reached')

    def close(self):
        self._session.close()
