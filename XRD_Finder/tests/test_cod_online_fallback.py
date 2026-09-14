from __future__ import annotations

import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from xrd_finder.services.cod_online_service import CodOnlineService


class _Response:
    def __init__(self, payload: bytes, read_error: Exception | None = None) -> None:
        self._payload = payload
        self._read_error = read_error

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> bool:
        return False

    def read(self) -> bytes:
        if self._read_error is not None:
            raise self._read_error
        return self._payload


class CodOnlineFallbackTests(unittest.TestCase):
    def test_search_switches_to_mirror_after_primary_ssl_failure(self) -> None:
        requested_urls: list[str] = []
        notices: list[str] = []
        alerts: list[str] = []

        def open_url(request, **_kwargs):
            url = request.full_url
            requested_urls.append(url)
            if "www.crystallography.net" in url:
                raise URLError(ssl.SSLEOFError(8, "unexpected EOF"))
            return _Response(b'[{"file":"1000000","formula":"Ca B O"}]')

        service = CodOnlineService(
            status_callback=notices.append,
            alert_callback=alerts.append,
        )
        with patch("xrd_finder.services.cod_online_service.urlopen", side_effect=open_url):
            entries = service.search_elements(["Ca", "B", "O"])

        self.assertEqual([entry.cod_id for entry in entries], ["1000000"])
        self.assertIn("www.crystallography.net", requested_urls[0])
        self.assertIn("cod.ibt.lt", requested_urls[1])
        self.assertEqual(
            notices,
            ["COD: connected through mirror cod.ibt.lt"],
        )
        self.assertEqual(
            alerts,
            ["Primary COD server is unavailable. Trying mirror cod.ibt.lt."],
        )

    def test_download_reuses_the_working_mirror(self) -> None:
        requested_urls: list[str] = []

        def open_url(request, **_kwargs):
            requested_urls.append(request.full_url)
            return _Response(b"data_1000000\n")

        service = CodOnlineService()
        service._active_base_url = "https://cod.ibt.lt/cod"
        with tempfile.TemporaryDirectory() as directory:
            with patch("xrd_finder.services.cod_online_service.urlopen", side_effect=open_url):
                path = service.download_cif("1000000", Path(directory))

            self.assertEqual(path.read_bytes(), b"data_1000000\n")

        self.assertEqual(len(requested_urls), 1)
        self.assertTrue(requested_urls[0].startswith("https://cod.ibt.lt/cod/"))

    def test_read_error_also_switches_to_mirror(self) -> None:
        requested_urls: list[str] = []

        def open_url(request, **_kwargs):
            requested_urls.append(request.full_url)
            if "www.crystallography.net" in request.full_url:
                return _Response(b"", ssl.SSLEOFError(8, "unexpected EOF"))
            return _Response(b'[{"file":"1000000","formula":"Ca B O"}]')

        service = CodOnlineService(alert_callback=lambda _message: None)
        with patch("xrd_finder.services.cod_online_service.urlopen", side_effect=open_url):
            entries = service.search_elements(["Ca", "B", "O"])

        self.assertEqual([entry.cod_id for entry in entries], ["1000000"])
        self.assertEqual(len(requested_urls), 2)


if __name__ == "__main__":
    unittest.main()
