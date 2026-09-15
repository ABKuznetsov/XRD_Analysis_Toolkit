from __future__ import annotations

import json
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.error import URLError
from urllib.request import Request, urlopen
from xrd_finder.services.network import create_ssl_context, ensure_online_allowed


COD_BASE_URLS = (
    "https://www.crystallography.net/cod",
    "https://cod.ibt.lt/cod",
)
COD_SEARCH_URL = f"{COD_BASE_URLS[0]}/result"
COD_ENTRY_URL = f"{COD_BASE_URLS[0]}/{{cod_id}}.cif"
COD_USER_AGENT = "XRD-Phase-Finder/1.5"


@dataclass(slots=True)
class CodEntry:
    cod_id: str
    formula: str = ""
    name: str = ""
    mineral: str = ""
    spacegroup: str = ""
    source: str = ""


class CodOnlineService:
    def __init__(
        self,
        status_callback: Callable[[str], None] | None = None,
        alert_callback: Callable[[str], None] | None = None,
    ) -> None:
        self._ssl_context = self._create_ssl_context()
        self._status_callback = status_callback
        self._alert_callback = alert_callback
        self._active_base_url = COD_BASE_URLS[0]

    def search_text(self, query: str, limit: int = 100, timeout: float = 15.0) -> list[CodEntry]:
        if not query.strip():
            return []

        params = {
            "text": query.strip(),
            "format": "json",
        }
        return self._search(params=params, limit=limit, timeout=timeout)

    def search_formula(self, formula: str, limit: int = 100, timeout: float = 15.0) -> list[CodEntry]:
        if not formula.strip():
            return []

        params = {
            "formula": formula.strip(),
            "format": "json",
        }
        return self._search(params=params, limit=limit, timeout=timeout)

    def search_elements(
        self,
        elements: list[str],
        excluded_elements: list[str] | None = None,
        limit: int = 100,
        timeout: float = 15.0,
    ) -> list[CodEntry]:
        selected = [element.strip() for element in elements if element.strip()]
        if not selected:
            return []

        params = {"format": "json"}
        for index, element in enumerate(selected[:8], start=1):
            params[f"el{index}"] = element
        entries = self._search(params=params, limit=limit * 3, timeout=timeout)
        excluded = {element.strip() for element in excluded_elements or [] if element.strip()}
        if excluded:
            entries = [entry for entry in entries if not (formula_elements(entry.formula) & excluded)]
        return entries[:limit]

    def cif_url(self, cod_id: str) -> str:
        return f"{self._active_base_url}/{cod_id}.cif"

    def download_cif(self, cod_id: str, target_dir: str | Path, timeout: float = 20.0) -> Path:
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        output_path = target / f"{cod_id}.cif"
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path
        output_path.write_bytes(self._request_bytes(f"/{cod_id}.cif", timeout=timeout))
        return output_path

    def _search(self, params: dict[str, str], limit: int, timeout: float) -> list[CodEntry]:
        payload = self._request_bytes(
            f"/result?{urlencode(params)}",
            timeout=timeout,
        ).decode("utf-8", errors="replace")
        raw_entries = json.loads(payload)
        if isinstance(raw_entries, dict):
            raw_entries = raw_entries.get("entries", [])
        return [self._to_entry(item) for item in raw_entries[:limit]]

    def _request_bytes(self, path: str, *, timeout: float) -> bytes:
        ensure_online_allowed("COD online")
        bases = [self._active_base_url]
        bases.extend(base for base in COD_BASE_URLS if base not in bases)
        last_error: Exception | None = None

        for index, base_url in enumerate(bases):
            request = Request(
                f"{base_url}{path}",
                headers={"User-Agent": COD_USER_AGENT, "Accept": "application/json, */*"},
            )
            try:
                with urlopen(request, timeout=timeout, context=self._ssl_context) as response:
                    payload = response.read()
            except (URLError, TimeoutError, ssl.SSLError, OSError) as exc:
                last_error = exc
                if index + 1 < len(bases):
                    next_host = bases[index + 1].split("//", 1)[-1].split("/", 1)[0]
                    if base_url == COD_BASE_URLS[0]:
                        self._emit_alert(
                            f"Primary online database endpoint is unavailable. Trying COD mirror {next_host}."
                        )
                    else:
                        self._emit_status(f"COD: {next_host} unavailable; trying another server...")
                continue

            if base_url != COD_BASE_URLS[0] and self._active_base_url != base_url:
                mirror_host = base_url.split("//", 1)[-1].split("/", 1)[0]
                self._emit_status(f"COD: connected through mirror {mirror_host}")
            self._active_base_url = base_url
            return payload

        if last_error is not None:
            self._emit_alert(
                "Online database connection is unavailable for COD. Local data is shown. "
                "Check VPN or proxy settings if online databases should be reachable."
            )
            raise last_error
        raise RuntimeError("No COD servers are configured.")

    def _emit_status(self, message: str) -> None:
        if self._status_callback is None:
            return
        try:
            self._status_callback(message)
        except Exception:
            pass

    def _emit_alert(self, message: str) -> None:
        if self._alert_callback is None:
            return
        try:
            self._alert_callback(message)
        except Exception:
            pass

    def _to_entry(self, item: dict) -> CodEntry:
        cod_id = str(item.get("file") or item.get("cod_id") or item.get("id") or "")
        formula = str(item.get("formula") or item.get("formula_sum") or "")
        name = str(item.get("chemical_name_common") or item.get("name") or item.get("chemical_name_systematic") or "")
        mineral = str(item.get("mineral") or item.get("mineral_name") or "")
        spacegroup = str(item.get("sg") or item.get("spacegroup") or item.get("space_group_name_H-M_alt") or "")
        source = str(item.get("journal") or item.get("doi") or "")
        return CodEntry(
            cod_id=cod_id,
            formula=formula,
            name=name,
            mineral=mineral,
            spacegroup=spacegroup,
            source=source,
        )

    def _create_ssl_context(self):
        return create_ssl_context()


def formula_elements(formula: str) -> set[str]:
    return set(re.findall(r"[A-Z][a-z]?", formula))
