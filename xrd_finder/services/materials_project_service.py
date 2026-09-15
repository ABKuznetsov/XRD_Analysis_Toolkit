from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from xrd_finder.services.network import ensure_online_allowed


@dataclass(slots=True)
class MaterialsProjectEntry:
    material_id: str
    formula: str = ""
    name: str = ""
    spacegroup: str = ""
    energy_above_hull: str = ""


@dataclass(slots=True)
class MaterialsProjectStatus:
    configured: bool
    client_available: bool
    label: str


class MaterialsProjectService:
    """Optional Materials Project connector.

    Finder uses only a small subset of the Materials Project API, so this class
    talks to the public REST endpoint directly instead of requiring mp-api and
    its large dependency tree.
    """

    BASE_URL = "https://api.materialsproject.org"
    LEGACY_BASE_URL = "https://www.materialsproject.org/rest/v2"
    SUMMARY_PATH = "/materials/summary/"
    USER_AGENT = "XRD-Phase-Finder/1.6"

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key.strip()

    def status(self, check_client: bool = False) -> MaterialsProjectStatus:
        if not self.api_key:
            return MaterialsProjectStatus(
                configured=False,
                client_available=False,
                label="API key is not configured",
            )
        if not check_client:
            return MaterialsProjectStatus(
                configured=True,
                client_available=False,
                label="API key configured; client will be checked when used",
            )
        return MaterialsProjectStatus(
            configured=True,
            client_available=True,
            label="Ready (Materials Project REST API)",
        )

    def search_text(self, query: str, limit: int = 80) -> list[MaterialsProjectEntry]:
        query = query.strip()
        if not query:
            return []
        element_tokens = re.findall(r"[A-Z][a-z]?", query)
        residue = re.sub(r"[A-Z][a-z]?|\s|,|;|-|_", "", query)
        if element_tokens and not residue:
            return self.search_elements(element_tokens, limit=limit)
        formula_like = re.sub(r"\s+", "", query)
        return self._search(formula=formula_like, elements=None, limit=limit)

    def search_elements(
        self,
        elements: list[str],
        limit: int = 80,
        optional_elements: list[str] | None = None,
    ) -> list[MaterialsProjectEntry]:
        selected = [element.strip() for element in elements if element.strip()]
        if not selected:
            return []
        optional = [element.strip() for element in optional_elements or [] if element.strip()]
        return self._search(formula=None, elements=selected, optional_elements=optional, limit=limit)

    def download_cif(self, material_id: str, target_dir: str | Path) -> Path:
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        output_path = target / f"{material_id}.cif"
        if output_path.exists() and output_path.stat().st_size > 0:
            existing_text = output_path.read_text(encoding="utf-8", errors="replace")[:2000]
            old_rest_fallback = (
                "XRD Phase Finder Materials Project REST adapter" in existing_text
                and "REST adapter v2" not in existing_text
                and "_symmetry_space_group_name_H-M 'P 1'" in existing_text
            )
            if not old_rest_fallback:
                return output_path
        official_cif = self._download_official_cif(material_id)
        if official_cif:
            output_path.write_text(official_cif, encoding="utf-8")
            return output_path
        docs = self._summary_search(
            {"material_ids": material_id},
            fields=["material_id", "formula_pretty", "structure", "symmetry"],
            limit=1,
        )
        if not docs:
            raise ValueError(f"Materials Project structure was not found: {material_id}")
        structure = docs[0].get("structure")
        if not isinstance(structure, dict):
            raise ValueError(f"Materials Project response has no structure for {material_id}")
        cif_text = self._structure_to_cif_text(
            structure,
            material_id=str(docs[0].get("material_id") or material_id),
            formula=str(docs[0].get("formula_pretty") or ""),
            symmetry=docs[0].get("symmetry"),
        )
        output_path.write_text(cif_text, encoding="utf-8")
        return output_path

    def _download_official_cif(self, material_id: str) -> str | None:
        """Return an official MP CIF when the API exposes one.

        The JSON structure field is useful as a fallback, but converting it
        locally loses the reported symmetry and creates a P1 CIF. Prefer the
        server-side CIF when it is available.
        """

        safe_id = quote(material_id.strip(), safe="")
        if not safe_id:
            return None
        url = f"{self.LEGACY_BASE_URL}/materials/{safe_id}/vasp/cif"
        try:
            payload = self._request_json(url)
        except Exception:
            return None
        return self._extract_cif_text(payload)

    def _search(
        self,
        formula: str | None,
        elements: list[str] | None,
        limit: int,
        optional_elements: list[str] | None = None,
    ) -> list[MaterialsProjectEntry]:
        if not self.status(check_client=True).configured:
            return []
        fields = ["material_id", "formula_pretty", "symmetry", "energy_above_hull"]
        base_kwargs: dict[str, str] = {}
        if formula:
            base_kwargs["formula"] = formula
        allowed_elements: set[str] = set()
        required_elements: set[str] = set()
        systems: list[list[str]] = [[]]
        if elements:
            selected = sorted({self._element_symbol(element.strip()) for element in elements})
            selected = [element for element in selected if element]
            required_elements = set(selected)
            optional = sorted(
                {
                    self._element_symbol(element.strip())
                    for element in optional_elements or []
                    if element.strip()
                }
                - set(selected)
            )
            optional = [element for element in optional if element]
            allowed_elements = set(selected) | set(optional)
            if selected:
                systems = self._chemical_systems(selected, optional)
        docs: list[dict] = []
        seen_doc_keys: set[str] = set()
        for system in systems:
            kwargs = dict(base_kwargs)
            if system:
                kwargs["chemsys"] = "-".join(system)
            for doc in self._summary_search(kwargs, fields=fields, limit=limit):
                key = str(doc.get("material_id") or doc.get("formula_pretty") or doc)
                if key in seen_doc_keys:
                    continue
                seen_doc_keys.add(key)
                docs.append(doc)
        if allowed_elements:
            docs = [
                doc
                for doc in docs
                if required_elements.issubset(self._formula_elements(doc.get("formula_pretty", "")))
                and self._formula_elements(doc.get("formula_pretty", "")).issubset(allowed_elements)
            ]
        return [self._to_entry(doc) for doc in docs[:limit]]

    def _chemical_systems(self, required: list[str], optional: list[str]) -> list[list[str]]:
        systems: list[list[str]] = []
        max_optional = min(len(optional), 6)
        limited_optional = optional[:max_optional]
        for mask in range(1 << len(limited_optional)):
            system = set(required)
            for index, element in enumerate(limited_optional):
                if mask & (1 << index):
                    system.add(element)
            systems.append(sorted(system))
        systems.sort(key=lambda values: (len(values), values))
        return systems

    def _summary_search(
        self,
        params: dict[str, str],
        *,
        fields: list[str],
        limit: int,
    ) -> list[dict]:
        request_params = {
            **params,
            "_fields": ",".join(fields),
            "_limit": str(max(1, int(limit))),
            "id_format": "legacy",
        }
        payload = self._get_json(self.SUMMARY_PATH, request_params)
        data = payload.get("data")
        if data is None:
            data = payload.get("response")
        if not isinstance(data, list):
            return []
        return [doc for doc in data if isinstance(doc, dict)]

    def _get_json(self, path: str, params: dict[str, str]) -> dict:
        if not self.api_key:
            raise ValueError("Materials Project API key is not configured")
        query = urlencode(params, doseq=True)
        url = f"{self.BASE_URL}{path}?{query}" if query else f"{self.BASE_URL}{path}"
        return self._request_json(url)

    def _request_json(self, url: str) -> dict:
        if not self.api_key:
            raise ValueError("Materials Project API key is not configured")
        ensure_online_allowed("Materials Project")
        request = Request(
            url,
            headers={
                "accept": "application/json",
                "X-API-KEY": self.api_key,
                "User-Agent": self.USER_AGENT,
            },
        )
        try:
            with urlopen(request, timeout=16, context=self._ssl_context()) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"Materials Project HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Materials Project is not reachable: {exc.reason}") from exc
        except TimeoutError as exc:
            raise RuntimeError("Materials Project request timed out") from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise RuntimeError("Materials Project returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Materials Project returned an unexpected response")
        return payload

    def _extract_cif_text(self, value) -> str | None:
        if isinstance(value, str):
            text = value.strip()
            return text if self._looks_like_cif(text) else None
        if isinstance(value, list):
            for item in value:
                text = self._extract_cif_text(item)
                if text:
                    return text
            return None
        if not isinstance(value, dict):
            return None
        for key in ("cif", "CIF", "response", "data"):
            if key in value:
                text = self._extract_cif_text(value[key])
                if text:
                    return text
        return None

    def _looks_like_cif(self, text: str) -> bool:
        lowered = text[:4000].casefold()
        return (
            "data_" in lowered
            and "_cell_length_a" in lowered
            and "_atom_site" in lowered
        )

    def _ssl_context(self) -> ssl.SSLContext:
        try:
            import certifi

            return ssl.create_default_context(cafile=certifi.where())
        except Exception:
            return ssl.create_default_context()

    def _to_entry(self, doc) -> MaterialsProjectEntry:
        def value(name: str, default=""):
            if isinstance(doc, dict):
                return doc.get(name, default)
            return getattr(doc, name, default)

        material_id = str(value("material_id", "") or "")
        formula = str(value("formula_pretty", "") or "")
        symmetry = value("symmetry", None)
        if isinstance(symmetry, dict):
            spacegroup = str(symmetry.get("symbol") or symmetry.get("number") or "")
        else:
            spacegroup = str(getattr(symmetry, "symbol", "") or getattr(symmetry, "number", "") or "")
        energy = value("energy_above_hull", "")
        if energy is None:
            energy_text = ""
        else:
            try:
                energy_text = f"E hull {float(energy):.4g}"
            except Exception:
                energy_text = str(energy)
        return MaterialsProjectEntry(
            material_id=material_id,
            formula=formula,
            name=formula,
            spacegroup=spacegroup,
            energy_above_hull=energy_text,
        )

    def _structure_to_cif_text(
        self,
        structure: dict,
        *,
        material_id: str,
        formula: str = "",
        symmetry=None,
    ) -> str:
        lattice = structure.get("lattice")
        if not isinstance(lattice, dict):
            raise ValueError("Materials Project structure has no lattice")
        a, b, c, alpha, beta, gamma = self._lattice_parameters(lattice)
        sites = structure.get("sites")
        if not isinstance(sites, list) or not sites:
            raise ValueError("Materials Project structure has no atomic sites")

        lines = [
            f"data_{self._cif_token(material_id or 'materials_project')}",
            "_audit_creation_method 'XRD Phase Finder Materials Project REST adapter v2'",
        ]
        if formula:
            lines.append(f"_chemical_formula_sum '{formula}'")
        space_group_symbol, space_group_number = self._symmetry_fields(symmetry)
        lines.extend(
            [
                f"_cell_length_a {a:.8g}",
                f"_cell_length_b {b:.8g}",
                f"_cell_length_c {c:.8g}",
                f"_cell_angle_alpha {alpha:.8g}",
                f"_cell_angle_beta {beta:.8g}",
                f"_cell_angle_gamma {gamma:.8g}",
                f"_symmetry_space_group_name_H-M '{space_group_symbol}'",
                f"_space_group_name_H-M_alt '{space_group_symbol}'",
                f"_space_group_IT_number {space_group_number}",
                f"_symmetry_Int_Tables_number {space_group_number}",
                "loop_",
                "_atom_site_label",
                "_atom_site_type_symbol",
                "_atom_site_fract_x",
                "_atom_site_fract_y",
                "_atom_site_fract_z",
                "_atom_site_occupancy",
            ]
        )
        counters: dict[str, int] = {}
        for site in sites:
            if not isinstance(site, dict):
                continue
            coords = site.get("abc") or site.get("frac_coords")
            if not self._is_coord_triplet(coords):
                continue
            for element, occupancy in self._site_species(site):
                counters[element] = counters.get(element, 0) + 1
                label = f"{element}{counters[element]}"
                x, y, z = (float(value) for value in coords)
                lines.append(
                    f"{label} {element} {x:.10g} {y:.10g} {z:.10g} {float(occupancy):.8g}"
                )
        if not counters:
            raise ValueError("Materials Project structure has no readable atomic sites")
        lines.append("")
        return "\n".join(lines)

    def _formula_elements(self, formula: str) -> set[str]:
        return {match.group(0) for match in re.finditer(r"[A-Z][a-z]?", formula)}

    def _symmetry_fields(self, symmetry) -> tuple[str, int]:
        symbol = ""
        number = None
        if isinstance(symmetry, dict):
            symbol = str(
                symmetry.get("symbol")
                or symmetry.get("international")
                or symmetry.get("hm")
                or ""
            ).strip()
            number = symmetry.get("number") or symmetry.get("int_number")
        else:
            symbol = str(
                getattr(symmetry, "symbol", "")
                or getattr(symmetry, "international", "")
                or getattr(symmetry, "hm", "")
                or ""
            ).strip()
            number = getattr(symmetry, "number", None) or getattr(symmetry, "int_number", None)
        symbol = symbol.replace("'", " ").strip() or "P 1"
        try:
            number_int = int(number)
        except Exception:
            number_int = 1
        return symbol, number_int

    def _lattice_parameters(self, lattice: dict) -> tuple[float, float, float, float, float, float]:
        required = ("a", "b", "c", "alpha", "beta", "gamma")
        if all(self._finite_number(lattice.get(key)) for key in required):
            return tuple(float(lattice[key]) for key in required)  # type: ignore[return-value]
        matrix = lattice.get("matrix")
        if not (
            isinstance(matrix, list)
            and len(matrix) == 3
            and all(isinstance(row, list) and len(row) == 3 for row in matrix)
        ):
            raise ValueError("Materials Project lattice has no cell parameters")
        vectors = [tuple(float(value) for value in row) for row in matrix]
        a, b, c = (self._norm(vector) for vector in vectors)
        alpha = self._angle(vectors[1], vectors[2])
        beta = self._angle(vectors[0], vectors[2])
        gamma = self._angle(vectors[0], vectors[1])
        return a, b, c, alpha, beta, gamma

    def _site_species(self, site: dict) -> list[tuple[str, float]]:
        species = site.get("species")
        result: list[tuple[str, float]] = []
        if isinstance(species, list):
            for item in species:
                if isinstance(item, dict):
                    element = str(item.get("element") or item.get("label") or item.get("species") or "").strip()
                    occupancy = item.get("occu", item.get("occupancy", 1.0))
                else:
                    element = str(item).strip()
                    occupancy = 1.0
                element = self._element_symbol(element)
                if element and self._finite_number(occupancy):
                    result.append((element, float(occupancy)))
        if result:
            return result
        element = self._element_symbol(str(site.get("species_string") or site.get("label") or "").strip())
        return [(element, 1.0)] if element else []

    def _element_symbol(self, value: str) -> str:
        match = re.match(r"([A-Z][a-z]?)", value)
        return match.group(1) if match else ""

    def _cif_token(self, value: str) -> str:
        token = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip())
        return token or "materials_project"

    def _is_coord_triplet(self, value) -> bool:
        return isinstance(value, (list, tuple)) and len(value) == 3 and all(
            self._finite_number(item) for item in value
        )

    def _finite_number(self, value) -> bool:
        try:
            number = float(value)
        except Exception:
            return False
        return math.isfinite(number)

    def _norm(self, vector: tuple[float, float, float]) -> float:
        return math.sqrt(sum(component * component for component in vector))

    def _angle(self, left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
        denominator = self._norm(left) * self._norm(right)
        if denominator <= 0:
            raise ValueError("Materials Project lattice contains a zero vector")
        cosine = sum(a * b for a, b in zip(left, right)) / denominator
        cosine = max(-1.0, min(1.0, cosine))
        return math.degrees(math.acos(cosine))
