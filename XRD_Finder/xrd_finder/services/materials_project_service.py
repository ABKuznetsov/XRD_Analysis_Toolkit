from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


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

    The dependency is intentionally soft: the rest of the application must keep
    working when mp-api is not installed or when the user has no API key yet.
    """

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
        client_kind = self._client_kind()
        client_available = bool(client_kind)
        if not client_available:
            label = "mp-api or pymatgen Materials Project client not installed"
        else:
            label = f"Ready ({client_kind})"
        return MaterialsProjectStatus(
            configured=bool(self.api_key) and client_available,
            client_available=client_available,
            label=label,
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

    def search_elements(self, elements: list[str], limit: int = 80) -> list[MaterialsProjectEntry]:
        selected = [element.strip() for element in elements if element.strip()]
        if not selected:
            return []
        return self._search(formula=None, elements=selected, limit=limit)

    def download_cif(self, material_id: str, target_dir: str | Path) -> Path:
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        output_path = target / f"{material_id}.cif"
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path
        with self._mpr() as mpr:
            structure = mpr.get_structure_by_material_id(material_id)
        try:
            cif_text = structure.to(fmt="cif")
        except TypeError:
            cif_text = str(structure)
        output_path.write_text(cif_text, encoding="utf-8")
        return output_path

    def _search(
        self,
        formula: str | None,
        elements: list[str] | None,
        limit: int,
    ) -> list[MaterialsProjectEntry]:
        if not self.status(check_client=True).configured:
            return []
        fields = ["material_id", "formula_pretty", "symmetry", "energy_above_hull"]
        client_kind = self._client_kind()
        kwargs = {"fields": fields} if client_kind == "mp-api" else {"_fields": fields, "_limit": limit}
        if formula:
            kwargs["formula"] = formula
        if elements:
            kwargs["elements"] = elements
        with self._mpr() as mpr:
            if hasattr(mpr, "materials"):
                docs = mpr.materials.summary.search(**kwargs)
            else:
                docs = mpr.summary_search(**kwargs)
        return [self._to_entry(doc) for doc in docs[:limit]]

    def _mpr(self):
        try:
            from mp_api.client import MPRester

            return self._with_request_timeout(MPRester(self.api_key))
        except Exception:
            from pymatgen.ext.matproj import MPRester

        return self._with_request_timeout(MPRester(self.api_key))

    def _with_request_timeout(self, mpr):
        session = getattr(mpr, "session", None)
        if session is None or getattr(session, "_xrd_timeout_wrapped", False):
            return mpr
        original_request = session.request

        def request_with_timeout(method, url, **kwargs):
            kwargs.setdefault("timeout", (4, 12))
            return original_request(method, url, **kwargs)

        session.request = request_with_timeout
        session._xrd_timeout_wrapped = True
        return mpr

    def _client_available(self) -> bool:
        return bool(self._client_kind())

    def _client_kind(self) -> str:
        try:
            import mp_api.client  # noqa: F401
        except Exception:
            pass
        else:
            return "mp-api"
        try:
            from pymatgen.ext.matproj import MPRester  # noqa: F401
        except Exception:
            return ""
        return "pymatgen"

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
