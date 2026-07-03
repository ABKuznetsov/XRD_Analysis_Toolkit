from __future__ import annotations

import html as html_lib
import re
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import quote, urlencode, urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen


DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
CCDC_SEARCH_URL = "https://www.ccdc.cam.ac.uk/structures/Search?Doi={doi}"


def extract_doi(text: str) -> str:
    match = DOI_RE.search(text or "")
    return match.group(0).rstrip(".,;") if match else ""


class CcdcService:
    def download_cif_by_doi(self, doi: str, target_dir: str | Path, timeout: float = 25.0) -> Path:
        doi = doi.strip()
        if not doi:
            raise ValueError("DOI is empty.")
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        output_path = target / f"{self._safe_id(doi)}.cif"
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path

        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        search_url = CCDC_SEARCH_URL.format(doi=quote(doi, safe=""))
        payload = self._read_url(search_url, timeout=timeout, opener=opener)
        if self._looks_like_cif(payload):
            output_path.write_bytes(payload)
            return output_path

        html = payload.decode("utf-8", errors="replace")
        load_html = self._read_load_search(html, search_url, timeout=timeout, opener=opener)
        if load_html:
            html = load_html

        for data in self._candidate_payloads(html, search_url, doi, timeout=timeout, opener=opener):
            if self._looks_like_cif(data):
                output_path.write_bytes(data)
                return output_path
            text = data[:200000].decode("utf-8", errors="replace")
            nested_doi = self._extract_ccdc_doi(text)
            if nested_doi and nested_doi.lower() != doi.lower():
                nested_url = CCDC_SEARCH_URL.format(doi=quote(nested_doi, safe=""))
                nested_payload = self._read_url(nested_url, timeout=timeout, opener=opener)
                if self._looks_like_cif(nested_payload):
                    output_path.write_bytes(nested_payload)
                    return output_path
                for nested_candidate in self._candidate_download_urls(
                    nested_payload.decode("utf-8", errors="replace"),
                    nested_url,
                    nested_doi,
                ):
                    nested_data = self._read_url(nested_candidate, timeout=timeout, opener=opener)
                    if self._looks_like_cif(nested_data):
                        output_path.write_bytes(nested_data)
                        return output_path

        raise ValueError("CCDC did not return a downloadable CIF for this DOI.")

    def _read_url(self, url: str, timeout: float, opener=None, data: bytes | None = None) -> bytes:
        headers = {"User-Agent": "XRD Finder/standalone"}
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = Request(url, data=data, headers=headers)
        open_fn = opener.open if opener is not None else urlopen
        with open_fn(request, timeout=timeout) as response:
            return response.read()

    def _read_load_search(self, html: str, base_url: str, timeout: float, opener=None) -> str:
        match = re.search(
            r"""id=["']loadSearch["'][^>]+data-url=["']([^"']+)["']""",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match is None:
            return ""
        load_url = urljoin(base_url, html_lib.unescape(match.group(1)))
        try:
            return self._read_url(load_url, timeout=timeout, opener=opener).decode("utf-8", errors="replace")
        except Exception:
            return ""

    def _candidate_payloads(self, html: str, base_url: str, doi: str, timeout: float, opener=None) -> list[bytes]:
        payloads = []
        for url, post_data in self._candidate_download_requests(html, base_url, doi):
            try:
                payloads.append(self._read_url(url, timeout=timeout, opener=opener, data=post_data))
            except Exception:
                continue
        return payloads

    def _candidate_download_requests(self, html: str, base_url: str, doi: str) -> list[tuple[str, bytes | None]]:
        requests: list[tuple[str, bytes | None]] = []
        for url in self._candidate_download_urls(html, base_url, doi):
            requests.append((url, None))

        token = self._extract_request_token(html)
        identifier = self._extract_first(r'"Identifier"\s*:\s*"([^"]+)"', html) or self._extract_first(
            r'name=["\']Identifier["\'][^>]+value=["\']([^"\']+)["\']', html
        )
        database_id = self._extract_first(r'"DatabaseId"\s*:\s*"([^"]+)"', html) or self._extract_first(
            r'name=["\']DatabaseId["\'][^>]+value=["\']([^"\']+)["\']', html
        )
        structure_action = self._extract_first(
            r'id=["\']downloadStructureDataFileForm["\'][^>]+action=["\']([^"\']+)["\']',
            html,
        )
        if structure_action and identifier:
            action_url = urljoin(base_url, html_lib.unescape(structure_action))
            base_payload = {
                "Identifier": identifier,
                "identifier": identifier,
                "CcdcNumber": identifier,
                "ccdcNumber": identifier,
            }
            if database_id:
                base_payload.update({"DatabaseId": database_id, "databaseId": database_id})
            if token:
                base_payload["__RequestVerificationToken"] = token
            for file_format in ("cif", "CIF"):
                payload = dict(base_payload)
                payload.update({"FileFormat": file_format, "fileFormat": file_format})
                requests.append((action_url, urlencode(payload).encode("utf-8")))

        return requests

    def _candidate_download_urls(self, html: str, base_url: str, doi: str) -> list[str]:
        urls = []
        links = re.findall(r"""(?:href|action|data-url)=["']([^"']+)["']""", html, flags=re.IGNORECASE)
        for href in links:
            lowered = href.lower()
            if ".cif" in lowered or "download" in lowered or "deposition" in lowered or "structures" in lowered:
                urls.append(urljoin(base_url, href))

        for number in self._extract_deposition_numbers(html):
            quoted_number = quote(number, safe="")
            urls.extend(
                [
                    f"https://www.ccdc.cam.ac.uk/services/structures?id={quoted_number}&sid=DataCite",
                    f"https://www.ccdc.cam.ac.uk/structures/download?id={quoted_number}",
                    f"https://www.ccdc.cam.ac.uk/structures/Download?Id={quoted_number}",
                    f"https://www.ccdc.cam.ac.uk/structures/download?depositionNumber={quoted_number}",
                    f"https://www.ccdc.cam.ac.uk/structures/Download?CcdcNumber={quoted_number}",
                ]
            )

        for candidate_doi in {doi, self._extract_ccdc_doi(html)}:
            if not candidate_doi:
                continue
            quoted_doi = quote(candidate_doi, safe="")
            urls.extend(
                [
                    f"https://www.ccdc.cam.ac.uk/structures/download?doi={quoted_doi}",
                    f"https://www.ccdc.cam.ac.uk/structures/Download?Doi={quoted_doi}",
                    f"https://www.ccdc.cam.ac.uk/services/structures?doi={quoted_doi}",
                ]
            )

        unique = []
        seen = set()
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            unique.append(url)
        return unique

    def _extract_deposition_numbers(self, html: str) -> list[str]:
        patterns = [
            r"Deposition\s+Number\s*</[^>]+>\s*<[^>]+>\s*(\d{5,9})",
            r"Deposition\s+Number[^0-9]{0,80}(\d{5,9})",
            r"CCDC[-\s]*(\d{5,9})",
        ]
        numbers = []
        for pattern in patterns:
            numbers.extend(re.findall(pattern, html, flags=re.IGNORECASE | re.DOTALL))
        return list(dict.fromkeys(numbers))

    def _extract_ccdc_doi(self, html: str) -> str:
        match = re.search(r"10\.5517/ccdc\.csd\.[-._;()/:A-Z0-9]+", html, flags=re.IGNORECASE)
        return match.group(0).rstrip(".,;") if match else ""

    def _extract_request_token(self, html: str) -> str:
        return self._extract_first(
            r'name=["\']__RequestVerificationToken["\'][^>]+value=["\']([^"\']+)["\']',
            html,
        )

    def _extract_first(self, pattern: str, text: str) -> str:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        return html_lib.unescape(match.group(1)) if match else ""

    def _looks_like_cif(self, payload: bytes) -> bool:
        head = payload[:4096].decode("utf-8", errors="ignore").lower()
        return "data_" in head and ("_cell_length_a" in head or "_atom_site" in head)

    def _safe_id(self, doi: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "_", doi).strip("_") or "ccdc_doi"
