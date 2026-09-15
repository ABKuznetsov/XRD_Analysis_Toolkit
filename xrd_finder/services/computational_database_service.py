from __future__ import annotations

from dataclasses import dataclass
import math
import json
from pathlib import Path
import re
from urllib.parse import quote, urlencode
import html
from urllib.request import Request

from xrd_finder.services.network import open_url


@dataclass(slots=True)
class ComputationalEntry:
    source: str
    entry_id: str
    formula: str = ""
    name: str = ""
    spacegroup: str = ""
    note: str = ""
    url_hint: str = ""


@dataclass(slots=True)
class OnlineSourceStatus:
    configured: bool
    label: str


class AflowService:
    label = "AFLOW"
    base_url = "https://aflow.org/API/aflux/"

    def status(self) -> OnlineSourceStatus:
        return OnlineSourceStatus(True, "online structure source (experimental)")

    def search_text(self, query: str, limit: int = 80) -> list[ComputationalEntry]:
        query = query.strip()
        if not query:
            return []
        elements = _element_tokens(query)
        residue = re.sub(r"[A-Z][a-z]?|[0-9.]+|\s|,|;|-|_", "", query)
        if elements and not residue and not re.search(r"\d", query):
            return self.search_elements(elements, limit=limit)
        clauses = [f"compound({quote(_compact_formula(query), safe='')})"]
        return self._search(clauses, limit=limit)

    def search_elements(self, elements: list[str], limit: int = 80) -> list[ComputationalEntry]:
        selected = [element.strip() for element in elements if element.strip()]
        if not selected:
            return []
        species = ",".join(quote(element, safe="") for element in selected)
        clauses = [f"species({species})", f"nspecies({len(selected)})"]
        return self._search(clauses, limit=limit)

    def download_cif(self, entry_id: str, target_dir: str | Path, url_hint: str = "", formula_hint: str = "") -> Path:
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        safe_id = _safe_id(entry_id)
        output_path = target / f"{safe_id}.cif"
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path
        errors = []
        for url in self._candidate_cif_urls(entry_id, url_hint):
            try:
                text = _read_text(url, timeout=45.0)
                if _looks_like_cif(text):
                    output_path.write_text(text, encoding="utf-8")
                    return output_path
                errors.append(f"{url}: {_response_kind(text)}")
            except Exception as exc:
                errors.append(f"{url}: {exc}")
        for url in self._candidate_vasp_urls(entry_id, url_hint):
            try:
                text = _read_text(url, timeout=45.0)
                if _looks_like_vasp(text):
                    self._write_vasp_as_cif(text, output_path)
                    return output_path
                errors.append(f"{url}: {_response_kind(text)}")
            except Exception as exc:
                errors.append(f"{url}: {exc}")
        details = "; ".join(errors[:4])
        raise ValueError("AFLOW structure export is not available for this entry." + (f" Details: {details}" if details else ""))

    def _search(self, clauses: list[str], limit: int) -> list[ComputationalEntry]:
        query_parts = list(clauses) + [
            "catalog(ICSD)",
            "$paging(1,%d)" % int(limit),
            "$format(json)",
        ]
        url = self.base_url + "?" + ",".join(query_parts)
        text = _read_text(url, timeout=35.0)
        payload = json.loads(text)
        if isinstance(payload, dict):
            records = payload.get("data") or payload.get("aflowlib") or payload.get("entries") or []
        else:
            records = payload
        entries = []
        for record in records[:limit] if isinstance(records, list) else []:
            if not isinstance(record, dict):
                continue
            entry_id = str(record.get("auid") or record.get("aurl") or record.get("compound") or "").strip()
            if not entry_id:
                continue
            formula = str(record.get("compound") or record.get("formula") or "")
            spacegroup = str(record.get("spacegroup_relax") or record.get("spacegroup_orig") or "")
            aurl = str(record.get("aurl") or "")
            note = " ".join(part for part in [spacegroup, aurl] if part)
            entries.append(
                ComputationalEntry(
                    source="AFLOW",
                    entry_id=entry_id,
                    formula=formula,
                    name=formula or entry_id,
                    spacegroup=spacegroup,
                    note=note,
                    url_hint=aurl,
                )
            )
        return entries

    def _candidate_cif_urls(self, entry_id: str, url_hint: str) -> list[str]:
        urls = []
        for base in self._candidate_entry_urls(entry_id, url_hint):
            urls.extend([
                base + "/CONTCAR.relax.cif",
                base + "/structure.cif",
                base + "/?format=cif",
            ])
        return list(dict.fromkeys(urls))

    def _candidate_vasp_urls(self, entry_id: str, url_hint: str) -> list[str]:
        urls = []
        for base in self._candidate_entry_urls(entry_id, url_hint):
            urls.extend([
                base + "/CONTCAR.relax",
                base + "/CONTCAR.relax.vasp",
                base + "/POSCAR.orig",
                base + "/POSCAR",
            ])
        return list(dict.fromkeys(urls))

    def _candidate_entry_urls(self, entry_id: str, url_hint: str) -> list[str]:
        urls = []
        for raw in [url_hint, entry_id]:
            urls.extend(self._extract_entry_urls(raw))
        if not urls and entry_id.lower().startswith("aflow:"):
            urls.extend(self._entry_urls_from_metadata(entry_id))
        return list(dict.fromkeys(urls))

    def _extract_entry_urls(self, text: str) -> list[str]:
        urls = []
        for match in re.findall(r"(?:https?://)?aflowlib\.duke\.edu[:/][^\s;,]+", text or ""):
            raw = match.strip().rstrip(".,)")
            if raw.startswith("https://aflowlib.duke.edu:"):
                raw = raw.replace("https://aflowlib.duke.edu:", "https://aflowlib.duke.edu/", 1)
            elif raw.startswith("http://aflowlib.duke.edu:"):
                raw = raw.replace("http://aflowlib.duke.edu:", "https://aflowlib.duke.edu/", 1)
            elif raw.startswith("aflowlib.duke.edu:"):
                raw = "https://aflowlib.duke.edu/" + raw.split(":", 1)[1]
            elif raw.startswith("aflowlib.duke.edu/"):
                raw = "https://" + raw
            urls.append(raw.rstrip("/"))
        return urls

    def _entry_urls_from_metadata(self, entry_id: str) -> list[str]:
        query = f"?auid({quote(entry_id, safe='')}),aurl,$format(json)"
        try:
            payload = json.loads(_read_text(self.base_url + query, timeout=25.0))
        except Exception:
            return []
        records = payload if isinstance(payload, list) else payload.get("data", []) if isinstance(payload, dict) else []
        urls = []
        for record in records if isinstance(records, list) else []:
            if isinstance(record, dict):
                urls.extend(self._extract_entry_urls(str(record.get("aurl") or "")))
        return urls

    def _write_vasp_as_cif(self, text: str, output_path: Path) -> None:
        lattice, sites = _parse_vasp_structure(text)
        _write_p1_cif(output_path, data_name=output_path.stem, lattice=lattice, sites=sites)


class OqmdService:
    label = "OQMD"
    base_url = "https://oqmd.org/oqmdapi/formationenergy"

    def status(self) -> OnlineSourceStatus:
        return OnlineSourceStatus(True, "online structure source (experimental)")

    def search_text(self, query: str, limit: int = 80) -> list[ComputationalEntry]:
        query = query.strip()
        if not query:
            return []
        elements = _element_tokens(query)
        residue = re.sub(r"[A-Z][a-z]?|[0-9.]+|\s|,|;|-|_", "", query)
        if elements and not residue and not re.search(r"\d", query):
            return self.search_elements(elements, limit=limit)
        return self._search({"composition": _compact_formula(query), "limit": str(limit)}, limit=limit)

    def search_elements(self, elements: list[str], limit: int = 80) -> list[ComputationalEntry]:
        selected = [element.strip() for element in elements if element.strip()]
        if not selected:
            return []
        ordered = sorted(selected)
        return self._search({"composition": "-".join(ordered), "limit": str(min(limit, 40))}, limit=limit, required_elements=selected)

    def download_cif(self, entry_id: str, target_dir: str | Path, url_hint: str = "", formula_hint: str = "") -> Path:
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        safe_id = _safe_id(entry_id)
        output_path = target / f"{safe_id}.cif"
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path
        record = self._record_from_hint(url_hint) or self._record_from_formula(entry_id, formula_hint)
        if record:
            self._write_record_as_cif(record, output_path)
            return output_path
        raw_id = re.sub(r"^oqmd-?", "", entry_id, flags=re.IGNORECASE)
        urls = self._candidate_cif_urls(raw_id, url_hint)
        errors = []
        for url in urls:
            try:
                text = _read_text(url, timeout=45.0)
                if _looks_like_cif(text):
                    output_path.write_text(text, encoding="utf-8")
                    return output_path
                errors.append(f"{url}: {_response_kind(text)}")
            except Exception as exc:
                errors.append(f"{url}: {exc}")
        raise ValueError("OQMD structure export is not available for this entry." + (" Details: " + "; ".join(errors[:3]) if errors else ""))

    def _candidate_cif_urls(self, raw_id: str, url_hint: str) -> list[str]:
        urls = []
        for candidate in re.findall(r"https?://[^\s;]+", url_hint or ""):
            if not candidate.startswith("oqmd-json:"):
                urls.append(candidate.rstrip(".,)"))
        urls.extend([
            f"https://oqmd.org/materials/export/conventional/cif/{quote(raw_id, safe='')}",
            f"https://oqmd.org/materials/export/primitive/cif/{quote(raw_id, safe='')}",
            f"https://oqmd.org/materials/export/cif/{quote(raw_id, safe='')}",
        ])
        return list(dict.fromkeys(url for url in urls if url))

    def _record_from_hint(self, url_hint: str) -> dict | None:
        prefix = "oqmd-json:"
        if not (url_hint or "").startswith(prefix):
            return None
        try:
            return json.loads(url_hint[len(prefix):])
        except Exception:
            return None

    def _record_from_formula(self, entry_id: str, formula_hint: str) -> dict | None:
        formula = _compact_formula(formula_hint)
        if not formula:
            return None
        raw_id = re.sub(r"^oqmd-?", "", entry_id or "", flags=re.IGNORECASE)
        try:
            entries = self._search({"composition": formula, "limit": "80"}, limit=80)
        except Exception:
            return None
        for entry in entries:
            if re.sub(r"^oqmd-?", "", entry.entry_id, flags=re.IGNORECASE) != raw_id:
                continue
            return self._record_from_hint(entry.url_hint)
        return None

    def _write_record_as_cif(self, record: dict, output_path: Path) -> None:
        lattice = record.get("unit_cell") or []
        sites = record.get("sites") or []
        cif_sites = []
        for site in sites:
            parsed = _parse_oqmd_site(str(site))
            if parsed is None:
                continue
            element, xyz = parsed
            cif_sites.append((element, xyz))
        if len(lattice) != 3 or not cif_sites:
            raise ValueError("OQMD JSON record does not contain a usable unit_cell/sites structure.")
        _write_p1_cif(output_path, data_name=output_path.stem, lattice=lattice, sites=cif_sites)

    def _search(
        self,
        params: dict[str, str],
        limit: int,
        required_elements: list[str] | None = None,
    ) -> list[ComputationalEntry]:
        url = self.base_url + "?" + urlencode(params)
        text = _read_text(url, timeout=35.0)
        payload = json.loads(text)
        records = payload.get("data") if isinstance(payload, dict) else payload
        entries = []
        for record in records[:limit] if isinstance(records, list) else []:
            if not isinstance(record, dict):
                continue
            raw_id = str(record.get("entry_id") or record.get("id") or record.get("name") or "").strip()
            if not raw_id:
                continue
            entry_id = raw_id if raw_id.lower().startswith("oqmd") else f"oqmd-{raw_id}"
            formula = str(record.get("composition") or record.get("formula") or record.get("name") or "")
            if required_elements and not set(required_elements).issubset(_formula_elements(formula)):
                continue
            spacegroup = str(record.get("spacegroup") or record.get("spacegroup_symbol") or "")
            formation = record.get("delta_e") or record.get("formationenergy") or record.get("stability") or ""
            note = " ".join(str(part) for part in [spacegroup, formation] if part not in (None, ""))
            entries.append(
                ComputationalEntry(
                    source="OQMD",
                    entry_id=entry_id,
                    formula=formula,
                    name=formula or entry_id,
                    spacegroup=spacegroup,
                    note=note,
                    url_hint="oqmd-json:" + json.dumps(record, separators=(",", ":")),
                )
            )
        return entries


def _read_text(url: str, timeout: float) -> str:
    request = Request(url, headers={"User-Agent": "XRD-Analysis-Toolkit/1.0"})
    with open_url(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _element_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Z][a-z]?", text or "")


def _compact_formula(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _safe_id(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text or "entry").strip("_") or "entry"


def _looks_like_cif(text: str) -> bool:
    sample = (text or "").lstrip()[:500].lower()
    return sample.startswith("data_") or "_cell_length_a" in sample or "_atom_site" in sample


def _looks_like_vasp(text: str) -> bool:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if len(lines) < 8:
        return False
    try:
        float(lines[1].split()[0])
    except Exception:
        return False
    return not _looks_like_cif(text) and not _looks_like_json(text) and "<html" not in (text or "").lower()[:300]


def _line_is_counts(line: str) -> bool:
    parts = line.split()
    if not parts:
        return False
    try:
        return all(float(part).is_integer() for part in parts)
    except Exception:
        return False


def _formula_symbols(text: str) -> list[str]:
    compact = re.split(r"\s|\[|\(", text or "", maxsplit=1)[0]
    return re.findall(r"[A-Z][a-z]?", compact)


def _looks_like_json(text: str) -> bool:
    sample = (text or "").lstrip()[:20]
    return sample.startswith("{") or sample.startswith("[")


def _response_kind(text: str) -> str:
    sample = (text or "").lstrip()[:500].lower()
    if _looks_like_json(text):
        return "JSON metadata, not a structure file"
    if "<html" in sample:
        return "HTML page, not a structure file"
    if _looks_like_vasp(text):
        return "VASP/POSCAR structure"
    return "not a recognized structure file"


def _parse_oqmd_site(site: str) -> tuple[str, list[float]] | None:
    match = re.match(r"\s*([A-Z][a-z]?)\s*@\s*(.+?)\s*$", html.unescape(site or ""))
    if not match:
        return None
    parts = match.group(2).split()
    if len(parts) < 3:
        return None
    try:
        return match.group(1), [float(parts[0]), float(parts[1]), float(parts[2])]
    except Exception:
        return None


def _formula_elements(text: str) -> set[str]:
    return set(re.findall(r"[A-Z][a-z]?", text or ""))


def _parse_vasp_structure(text: str) -> tuple[list[list[float]], list[tuple[str, list[float]]]]:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if len(lines) < 8:
        raise ValueError("AFLOW VASP structure is too short to convert to CIF.")
    try:
        scale = float(lines[1].split()[0])
        lattice = [[float(value) * scale for value in lines[index].split()[:3]] for index in range(2, 5)]
    except Exception as exc:
        raise ValueError("AFLOW VASP structure has invalid lattice vectors.") from exc

    symbols_line_index = 5
    if _line_is_counts(lines[symbols_line_index]):
        symbols = _formula_symbols(lines[0])
        counts_line_index = symbols_line_index
    else:
        symbols = re.findall(r"[A-Z][a-z]?", lines[symbols_line_index])
        counts_line_index = symbols_line_index + 1
    if not symbols or counts_line_index >= len(lines):
        raise ValueError("AFLOW VASP structure has no element symbols.")
    try:
        counts = [int(float(value)) for value in lines[counts_line_index].split()]
    except Exception as exc:
        raise ValueError("AFLOW VASP structure has invalid atom counts.") from exc
    if len(symbols) != len(counts):
        raise ValueError("AFLOW VASP structure element/count columns do not match.")

    coord_mode_index = counts_line_index + 1
    if coord_mode_index < len(lines) and lines[coord_mode_index].lower().startswith("s"):
        coord_mode_index += 1
    if coord_mode_index >= len(lines):
        raise ValueError("AFLOW VASP structure has no coordinate mode.")
    coordinate_mode = lines[coord_mode_index].lower()
    coordinate_start = coord_mode_index + 1
    total_atoms = sum(counts)
    coordinate_lines = lines[coordinate_start:coordinate_start + total_atoms]
    if len(coordinate_lines) < total_atoms:
        raise ValueError("AFLOW VASP structure has fewer coordinates than atom counts.")

    expanded_symbols = []
    for symbol, count in zip(symbols, counts):
        expanded_symbols.extend([symbol] * count)
    sites = []
    for symbol, line in zip(expanded_symbols, coordinate_lines):
        try:
            values = [float(value) for value in line.split()[:3]]
        except Exception as exc:
            raise ValueError("AFLOW VASP structure has invalid atom coordinates.") from exc
        if coordinate_mode.startswith(("c", "k")):
            values = _cartesian_to_fractional(values, lattice)
        sites.append((symbol, [_wrap_fraction(value) for value in values]))
    if not sites:
        raise ValueError("AFLOW VASP structure contains no atomic sites.")
    return lattice, sites


def _write_p1_cif(
    output_path: Path,
    *,
    data_name: str,
    lattice: list[list[float]],
    sites: list[tuple[str, list[float]]],
) -> None:
    a, b, c, alpha, beta, gamma = _cell_parameters_from_lattice(lattice)
    lines = [
        f"data_{_safe_id(data_name)}",
        "_audit_creation_method 'XRD Phase Finder lightweight structure adapter'",
        "_symmetry_space_group_name_H-M 'P 1'",
        "_symmetry_Int_Tables_number 1",
        f"_cell_length_a {a:.8f}",
        f"_cell_length_b {b:.8f}",
        f"_cell_length_c {c:.8f}",
        f"_cell_angle_alpha {alpha:.8f}",
        f"_cell_angle_beta {beta:.8f}",
        f"_cell_angle_gamma {gamma:.8f}",
        "loop_",
        "_symmetry_equiv_pos_as_xyz",
        "'x, y, z'",
        "loop_",
        "_atom_site_label",
        "_atom_site_type_symbol",
        "_atom_site_fract_x",
        "_atom_site_fract_y",
        "_atom_site_fract_z",
        "_atom_site_occupancy",
    ]
    counters: dict[str, int] = {}
    for symbol, coords in sites:
        counters[symbol] = counters.get(symbol, 0) + 1
        x, y, z = (_wrap_fraction(float(value)) for value in coords[:3])
        lines.append(f"{symbol}{counters[symbol]} {symbol} {x:.8f} {y:.8f} {z:.8f} 1.0")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _cell_parameters_from_lattice(lattice: list[list[float]]) -> tuple[float, float, float, float, float, float]:
    if len(lattice) != 3:
        raise ValueError("Structure lattice must contain three vectors.")
    vectors = [[float(value) for value in vector[:3]] for vector in lattice]
    if any(len(vector) != 3 for vector in vectors):
        raise ValueError("Structure lattice vectors must be three-dimensional.")
    a_vec, b_vec, c_vec = vectors
    a = _vector_norm(a_vec)
    b = _vector_norm(b_vec)
    c = _vector_norm(c_vec)
    if min(a, b, c) <= 0:
        raise ValueError("Structure lattice has a zero-length vector.")
    alpha = _angle_deg(b_vec, c_vec)
    beta = _angle_deg(a_vec, c_vec)
    gamma = _angle_deg(a_vec, b_vec)
    return a, b, c, alpha, beta, gamma


def _vector_norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def _angle_deg(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    denominator = _vector_norm(left) * _vector_norm(right)
    cosine = max(-1.0, min(1.0, dot / denominator))
    return math.degrees(math.acos(cosine))


def _cartesian_to_fractional(cartesian: list[float], lattice: list[list[float]]) -> list[float]:
    try:
        import numpy as np

        matrix = np.array(lattice, dtype=float).T
        return np.linalg.solve(matrix, np.array(cartesian, dtype=float)).tolist()
    except Exception as exc:
        raise ValueError("Cannot convert Cartesian AFLOW coordinates to fractional coordinates.") from exc


def _wrap_fraction(value: float) -> float:
    wrapped = value % 1.0
    if abs(wrapped - 1.0) < 1e-10 or abs(wrapped) < 1e-10:
        return 0.0
    return wrapped
