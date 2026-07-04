from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import re
import ssl
from urllib.parse import urlencode
from urllib.request import urlopen


COD_SEARCH_URL = "https://www.crystallography.net/cod/result"
COD_ENTRY_URL = "https://www.crystallography.net/cod/{cod_id}.cif"


@dataclass(slots=True)
class CodEntry:
    cod_id: str
    formula: str = ""
    name: str = ""
    mineral: str = ""
    spacegroup: str = ""
    source: str = ""


class CodOnlineService:
    def __init__(self) -> None:
        self._ssl_context = self._create_ssl_context()

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
        return COD_ENTRY_URL.format(cod_id=cod_id)

    def download_cif(self, cod_id: str, target_dir: str | Path, timeout: float = 20.0) -> Path:
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        output_path = target / f"{cod_id}.cif"
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path
        with urlopen(self.cif_url(cod_id), timeout=timeout, context=self._ssl_context) as response:
            output_path.write_bytes(response.read())
        return output_path

    def _search(self, params: dict[str, str], limit: int, timeout: float) -> list[CodEntry]:
        url = f"{COD_SEARCH_URL}?{urlencode(params)}"
        with urlopen(url, timeout=timeout, context=self._ssl_context) as response:
            payload = response.read().decode("utf-8", errors="replace")
        raw_entries = json.loads(payload)
        if isinstance(raw_entries, dict):
            raw_entries = raw_entries.get("entries", [])
        return [self._to_entry(item) for item in raw_entries[:limit]]

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

    def _create_ssl_context(self) -> ssl.SSLContext:
        try:
            import certifi

            return ssl.create_default_context(cafile=certifi.where())
        except Exception:
            return ssl.create_default_context()


def formula_elements(formula: str) -> set[str]:
    return set(re.findall(r"[A-Z][a-z]?", formula))
