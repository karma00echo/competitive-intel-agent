import http.client
import json
import socket
import ssl

import pytest
import requests
from urllib3 import exceptions as ue

from competitive_intel.infrastructure.facts.llm_provider import LLMFactExtractionProvider
from test_llm_fact_provider import Session, Response, config, request


@pytest.mark.parametrize("error,classification", [
    (requests.ConnectionError(socket.gaierror(-2, "secret")), "DNS_RESOLUTION_FAILED"),
    (requests.ConnectionError(ConnectionRefusedError("secret")), "TCP_CONNECTION_FAILED"),
    (requests.exceptions.SSLError(ssl.SSLError("secret")), "TLS_SSL_ERROR"),
    (requests.ConnectTimeout("secret"), "CONNECT_TIMEOUT"),
    (requests.ReadTimeout("secret"), "READ_TIMEOUT"),
    (requests.ConnectionError(ue.ReadTimeoutError(None, "/secret", "secret")), "READ_TIMEOUT"),
    (requests.ConnectionError(http.client.RemoteDisconnected("secret")), "REMOTE_DISCONNECTED"),
    (requests.ConnectionError(ConnectionResetError("secret")), "REMOTE_DISCONNECTED"),
    (requests.exceptions.ChunkedEncodingError("secret"), "PROTOCOL_ERROR"),
    (requests.RequestException("secret"), "HTTP_CLIENT_ERROR"),
    (requests.Timeout("secret"), "TIMEOUT_UNSPECIFIED"),
])
@pytest.mark.parametrize("during_body", [False, True])
def test_typed_failures_are_audited_without_messages_or_retry(error, classification, during_body):
    class BrokenBody(Response):
        def iter_content(self, size):
            raise error
            yield b""
    session = Session([BrokenBody() if during_body else error])
    result = LLMFactExtractionProvider(config(max_retries=2), session=session).extract(request())
    audit = result.http_audit[0]
    assert result.error and len(session.calls) == 1
    assert audit["connection_failure"] == classification
    assert audit["failure_stage"] == ("READ_RESPONSE_BODY" if during_body else "CONNECT_OR_RESPONSE_HEADERS")
    assert audit["http_status"] == (200 if during_body else None)
    assert audit["exception_type"] == type(error).__name__
    assert "secret" not in json.dumps(audit) and "test-only" not in json.dumps(audit)
