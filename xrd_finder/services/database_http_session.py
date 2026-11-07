"""Reusable database HTTP connections, including the user's system proxy."""
from io import BytesIO
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import getproxies, proxy_bypass

from xrd_finder.services.network import ensure_online_allowed


class _Response:
    def __init__(self, response):
        self.response = response
        self.exhausted = False

    def __enter__(self):
        return self

    def read(self, size=-1):
        try:
            data = self.response.read(None if size < 0 else size)
        except Exception as error:
            raise URLError(str(error)) from error
        if size < 0 or not data or getattr(self.response, 'length_remaining', None) == 0:
            self.exhausted = True
        return data

    def __exit__(self, *args):
        if not self.exhausted:
            self.response.close()
        self.response.release_conn()


class DatabaseHttpSession:
    """Lazy pools: no imports, sockets or certificate loading on first paint."""
    def __init__(self, ssl_context):
        self.ssl_context = ssl_context
        self._pools = {}
        self._lock = Lock()

    def _pool(self, url):
        import urllib3
        parsed = urlsplit(url)
        proxy = getproxies().get(parsed.scheme)
        if proxy and proxy_bypass(parsed.hostname or ''):
            proxy = None
        with self._lock:
            if proxy not in self._pools:
                options = dict(ssl_context=self.ssl_context, num_pools=4, maxsize=4)
                if proxy:
                    location = urlsplit(proxy)
                    headers = {}
                    if location.username is not None:
                        credentials = unquote(location.username) + ':' + unquote(location.password or '')
                        headers = urllib3.make_headers(proxy_basic_auth=credentials)
                    self._pools[proxy] = urllib3.ProxyManager(proxy, proxy_headers=headers, **options)
                else:
                    self._pools[proxy] = urllib3.PoolManager(**options)
            return self._pools[proxy]

    def open(self, request, *, headers=None, timeout=16.):
        import urllib3
        ensure_online_allowed('Online databases')
        url = request.full_url if hasattr(request, 'full_url') else str(request)
        headers = dict(request.header_items() if hasattr(request, 'header_items') else headers or {})
        for _ in range(4):
            ensure_online_allowed('Online databases')
            try:
                reply = self._pool(url).request('GET', url, headers=headers,
                    preload_content=False, redirect=False, retries=False,
                    timeout=urllib3.Timeout(connect=min(4., timeout), read=timeout))
            except urllib3.exceptions.HTTPError as error:
                raise URLError(str(error)) from error
            if reply.status in (301, 302, 303, 307, 308) and reply.headers.get('Location'):
                new_url = urljoin(url, reply.headers['Location'])
                reply.close()
                reply.release_conn()
                old, new = urlsplit(url), urlsplit(new_url)
                if new.scheme not in ('http', 'https') or old.scheme == 'https' and new.scheme != 'https':
                    raise URLError('Unsupported database redirect')
                if (old.scheme, old.netloc) != (new.scheme, new.netloc):
                    headers = {key:value for key,value in headers.items()
                               if key.casefold() not in ('x-api-key','authorization','cookie')}
                url = new_url
                continue
            if reply.status >= 400:
                with _Response(reply) as response:
                    body = response.read(1024 * 1024)
                raise HTTPError(url, reply.status, reply.reason, reply.headers, BytesIO(body))
            return _Response(reply)
        raise URLError('Too many database redirects')
