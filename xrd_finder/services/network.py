from __future__ import annotations

import ssl
from urllib.request import Request, urlopen

from xrd_finder.services.security_mode import offline_mode_enabled


def ensure_online_allowed(service: str = "network") -> None:
    if offline_mode_enabled():
        raise RuntimeError(f"{service} is disabled because offline/secure mode is enabled")


def create_ssl_context() -> ssl.SSLContext:
    """Create an HTTPS context that works reliably with python.org builds on macOS."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def open_url(url_or_request: str | Request, timeout: float = 30.0):
    ensure_online_allowed("Network access")
    return urlopen(url_or_request, timeout=timeout, context=create_ssl_context())
