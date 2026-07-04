from __future__ import annotations

import html as html_lib
from dataclasses import dataclass
import re
from http.cookiejar import CookieJar
from pathlib import Path
import ssl
from urllib.parse import quote, urlencode, urljoin
from urllib.request import HTTPSHandler, HTTPCookieProcessor, Request, build_opener, urlopen


DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
CCDC_SEARCH_URL = "https://www.ccdc.cam.ac.uk/structures/Search?Doi={doi}"


def extract_doi(text: str) -> str:
    match = DOI_RE.search(text or "")
    return match.group(0).rstrip(".,;") if match else ""


@dataclass(slots=True)
class CcdcApiStatus:
    installed: bool
    configured: bool
    label: str


@dataclass(slots=True)
class CcdcEntry:
    identifier: str
    formula: str = ""
    name: str = ""
    doi: str = ""


class CcdcService:
    def __init__(self) -> None:
        self._ssl_context = self._create_ssl_context()

    def status(self) -> CcdcApiStatus:
        try:
            from ccdc.io import EntryReader
        except Exception:
            return CcdcApiStatus(False, False, "CCDC Python API is not installed")
        try:
            reader = EntryReader("CSD")
            try:
                count = len(reader)
                label = f"CSD available ({count} entries)"
            except Exception:
                label = "CSD available"
            return CcdcApiStatus(True, True, label)
        except Exception as exc:
            return CcdcApiStatus(True, False, f"CCDC API installed, but CSD is not available: {exc}")

    def search_text(self, query: str, target_dir: str | Path, limit: int = 80) -> list[CcdcEntry]:
        query = query.strip()
        if not query:
            return []
        status = self.status()
        if not status.configured:
            return []

        hits = self._search_csd_hits(query, limit=limit)
        entries: list[CcdcEntry] = []
        for hit in hits[:limit]:
            identifier = self._hit_identifier(hit)
            if not identifier:
                continue
            try:
                cif_path = self.export_csd_cif(identifier, target_dir)
            except Exception:
                continue
            entries.append(self._entry_from_cif_or_hit(cif_path, hit, identifier))
        return entries

    def export_csd_cif(self, identifier: str, target_dir: str | Path) -> Path:
        identifier = identifier.strip()
        if not identifier:
            raise ValueError("CCDC identifier is empty.")
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        output_path = target / f"{self._safe_id(identifier)}.cif"
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path

        from ccdc.io import EntryReader, EntryWriter

        reader = EntryReader("CSD")
        entry = reader.entry(identifier)
        with EntryWriter(str(output_path), format="cif") as writer:
            try:
                writer.write(entry)
            except Exception:
                writer.write(entry.crystal)
        return output_path

    def download_cif_by_doi(self, doi: str, target_dir: str | Path, timeout: float = 25.0) -> Path:
        doi = doi.strip()
        if not doi:
            raise ValueError("DOI is empty.")
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        output_path = target / f"{self._safe_id(doi)}.cif"
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path

        opener = build_opener(HTTPCookieProcessor(CookieJar()), HTTPSHandler(context=self._ssl_context))
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

    def _search_csd_hits(self, query: str, limit: int) -> list[object]:
        from ccdc.io import EntryReader
        from ccdc.search import TextNumericSearch

        method_names = ["add_all_identifiers", "add_all_text", "add_compound_name", "add_synonym"]
        if extract_doi(query):
            method_names.append("add_doi")
        hits = []
        seen = set()
        for method_name in method_names:
            searcher = TextNumericSearch()
            method = getattr(searcher, method_name, None)
            if method is None:
                continue
            try:
                method(query)
                for hit in searcher.search(max_hit_structures=limit):
                    identifier = self._hit_identifier(hit)
                    if identifier and identifier not in seen:
                        seen.add(identifier)
                        hits.append(hit)
                    if len(hits) >= limit:
                        return hits
            except Exception:
                continue
        if hits:
            return hits

        reader = EntryReader("CSD")
        lowered = query.lower()
        hits = []
        for index, entry in enumerate(reader):
            haystack = " ".join(
                str(value or "")
                for value in [
                    getattr(entry, "identifier", ""),
                    getattr(entry, "chemical_name", ""),
                    getattr(entry, "synonyms", ""),
                    getattr(entry, "formula", ""),
                    getattr(entry, "doi", ""),
                ]
            ).lower()
            if lowered in haystack:
                hits.append(entry)
                if len(hits) >= limit:
                    break
            if index > 5000 and hits:
                break
        return hits

    def _hit_identifier(self, hit: object) -> str:
        return str(getattr(hit, "identifier", "") or getattr(getattr(hit, "entry", None), "identifier", "") or "")

    def _entry_from_cif_or_hit(self, cif_path: Path, hit: object, identifier: str) -> CcdcEntry:
        try:
            from xrd_finder.io.cif_loader import create_phase_from_cif

            _phase, structure = create_phase_from_cif(cif_path)
            return CcdcEntry(
                identifier=identifier,
                formula=getattr(structure, "formula", "") or str(getattr(hit, "formula", "") or ""),
                name=getattr(structure, "name", "") or str(getattr(hit, "chemical_name", "") or identifier),
                doi=str(getattr(hit, "doi", "") or ""),
            )
        except Exception:
            return CcdcEntry(
                identifier=identifier,
                formula=str(getattr(hit, "formula", "") or ""),
                name=str(getattr(hit, "chemical_name", "") or identifier),
                doi=str(getattr(hit, "doi", "") or ""),
            )

    def _read_url(self, url: str, timeout: float, opener=None, data: bytes | None = None) -> bytes:
        headers = {"User-Agent": "XRD Finder/1.0.1"}
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = Request(url, data=data, headers=headers)
        open_fn = opener.open if opener is not None else urlopen
        if opener is None and data is None:
            with open_fn(request, timeout=timeout, context=self._ssl_context) as response:
                return response.read()
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

    def _create_ssl_context(self) -> ssl.SSLContext:
        try:
            import certifi

            return ssl.create_default_context(cafile=certifi.where())
        except Exception:
            return ssl.create_default_context()
