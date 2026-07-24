"""Canonical URL normalization for search candidates and site links."""

from __future__ import annotations

import posixpath
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit


TRACKING_KEYS = {
    "gclid",
    "fbclid",
    "msclkid",
    "yclid",
    "_hsenc",
    "_hsmi",
    "referrer",
}


def normalize_url(url: str, *, base_url: str | None = None) -> str:
    value = urljoin(base_url, url) if base_url else url
    if "://" not in value:
        value = f"https://{value}"
    parts = urlsplit(value)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError(f"unsupported URL scheme: {scheme}")
    hostname = (parts.hostname or "").rstrip(".").lower()
    if not hostname:
        raise ValueError("URL must include a hostname")
    hostname = hostname.encode("idna").decode("ascii")
    port = parts.port
    default_port = (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    )
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    path = parts.path or "/"
    path = posixpath.normpath(path)
    if not path.startswith("/"):
        path = f"/{path}"
    if path != "/":
        path = path.rstrip("/")
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_KEYS
    ]
    query.sort()
    return urlunsplit((scheme, netloc, path, urlencode(query, doseq=True), ""))


def domain_from_url(url: str) -> str:
    return (urlsplit(normalize_url(url)).hostname or "").lower()


def same_site(left: str, right: str) -> bool:
    left_domain = domain_from_url(left)
    right_domain = domain_from_url(right)
    return (
        left_domain == right_domain
        or left_domain.endswith(f".{right_domain}")
        or right_domain.endswith(f".{left_domain}")
    )
