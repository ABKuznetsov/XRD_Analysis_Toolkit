from __future__ import annotations

from dataclasses import dataclass
import mmap
import os
from pathlib import Path
import re
import threading

from xrd_finder.services.cod_online_service import formula_elements


DEFAULT_MATCH_PDF2_ROOT = Path(r"C:\Program Files\Match3\PDF2-2004")
MATCH_PDF2_ENV = "XRD_MANAGER_MATCH_PDF2_DIR"


@dataclass(slots=True)
class MatchPdf2Status:
    configured: bool
    label: str
    root: Path
    count: int = 0


@dataclass(slots=True)
class MatchPdf2Entry:
    entry_id: str
    formula: str = ""
    name: str = ""
    chemical_name: str = ""
    quality: str = ""


@dataclass(slots=True)
class MatchPdf2Peak:
    d_spacing: float
    intensity: float
    h: str = ""
    k: str = ""
    l: str = ""


class MatchPdf2Service:
    def __init__(self, root: str | Path | None = None) -> None:
        env_root = os.environ.get(MATCH_PDF2_ENV)
        self.root = Path(root or env_root or DEFAULT_MATCH_PDF2_ROOT)
        self.summary_path = self.root / "summary.dat"
        self.pdf2_path = self.root / "pdf2.dat"
        self._entries: list[MatchPdf2Entry] | None = None
        self._details_cache: dict[str, dict[str, object]] = {}
        self._lock = threading.RLock()

    def status(self) -> MatchPdf2Status:
        if not self.summary_path.exists():
            return MatchPdf2Status(False, "summary.dat not found", self.root, 0)
        count = len(self._entries) if self._entries is not None else 0
        label = f"{count} PDF-2 cards" if count else "summary.dat ready"
        return MatchPdf2Status(True, label, self.root, count)

    def is_configured(self) -> bool:
        return self.summary_path.exists()

    def set_root(self, root: str | Path) -> None:
        with self._lock:
            self.root = Path(root)
            self.summary_path = self.root / "summary.dat"
            self.pdf2_path = self.root / "pdf2.dat"
            self._entries = None
            self._details_cache.clear()

    def refresh(self) -> int:
        with self._lock:
            self._entries = None
        return len(self._load_entries())

    def clear(self) -> None:
        with self._lock:
            self._entries = None
            self._details_cache.clear()

    def search(
        self,
        text: str = "",
        elements: list[str] | None = None,
        excluded_elements: list[str] | None = None,
        limit: int = 100,
    ) -> list[MatchPdf2Entry]:
        if not self.summary_path.exists():
            return []
        required = {element.strip() for element in elements or [] if element.strip()}
        excluded = {element.strip() for element in excluded_elements or [] if element.strip()}
        query = text.strip().lower()
        results = []
        for entry in self._load_entries():
            entry_elements = formula_elements(entry.formula)
            if required and not required.issubset(entry_elements):
                continue
            if excluded and entry_elements & excluded:
                continue
            if query:
                haystack = " ".join(
                    [
                        entry.entry_id,
                        self.short_entry_id(entry.entry_id),
                        entry.chemical_name,
                        entry.name,
                        entry.formula,
                    ]
                ).lower()
                if query not in haystack:
                    continue
            results.append(entry)
            if len(results) >= limit:
                break
        return results

    def diffraction_peaks(self, entry_id: str, limit: int = 250) -> list[MatchPdf2Peak]:
        if not self.pdf2_path.exists():
            return []
        chunk, tag_base = self._card_chunk(entry_id)
        if not chunk or not tag_base:
            return []
        return self._parse_diffraction_peaks(chunk, tag_base, limit=limit)

    def card_details(self, entry_id: str) -> dict[str, object]:
        cache_key = entry_id.strip()
        with self._lock:
            cached = self._details_cache.get(cache_key)
            if cached is not None:
                return dict(cached)
        if not self.pdf2_path.exists():
            return {}
        chunk, tag_base = self._card_chunk(entry_id)
        if not chunk or not tag_base:
            with self._lock:
                self._details_cache[cache_key] = {}
            return {}
        parts = self._tag_parts(chunk, tag_base)
        details: dict[str, object] = {}
        space_group, space_group_number = self._parse_space_group(parts)
        if space_group:
            details["space_group"] = space_group
        if space_group_number:
            details["space_group_number"] = space_group_number
        cell = self._parse_cell(parts)
        if cell:
            details["cell"] = cell
        with self._lock:
            self._details_cache[cache_key] = dict(details)
        return details

    def has_structure_data(self, entry_id: str) -> bool:
        details = self.card_details(entry_id)
        return bool(details.get("cell") or details.get("space_group") or details.get("space_group_number"))

    def _load_entries(self) -> list[MatchPdf2Entry]:
        with self._lock:
            if self._entries is None:
                self._entries = self._read_summary()
            return self._entries

    def short_entry_id(self, entry_id: str) -> str:
        match = re.match(r"\d{2}-(\d{3})-(\d{4})$", entry_id or "")
        if not match:
            return entry_id
        return f"{int(match.group(1)):02d}-{int(match.group(2)):04d}"

    def _card_chunk(self, entry_id: str, window_size: int = 42000) -> tuple[str, str]:
        card_code = self._card_code(entry_id)
        if not card_code:
            return "", ""
        code_bytes = card_code.encode("ascii")
        with self.pdf2_path.open("rb") as handle:
            with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
                position = 0
                while True:
                    position = mapped.find(code_bytes, position)
                    if position < 1:
                        return "", ""
                    prefix = mapped[position - 1 : position]
                    suffix = mapped[position + len(code_bytes) : position + len(code_bytes) + 1]
                    if prefix.isalpha() and suffix.isalpha():
                        start = position - 1
                        end = min(start + window_size, len(mapped))
                        tag_base = (prefix + code_bytes + suffix).decode("ascii", errors="ignore")
                        chunk = mapped[start:end].decode("latin1", errors="ignore")
                        if f"{tag_base}G" in chunk or f"{tag_base}I" in chunk:
                            return chunk, tag_base
                    position += len(code_bytes)

    def _card_code(self, entry_id: str) -> str:
        text = (entry_id or "").strip()
        match = re.match(r"\d{2}-(\d{3})-(\d{4})$", text)
        if match:
            return f"{int(match.group(1)):02d}{int(match.group(2)):04d}"
        match = re.match(r"(\d{1,2})-(\d{1,5})$", text)
        if match:
            return f"{int(match.group(1)):02d}{int(match.group(2)):04d}"
        return ""

    def _parse_diffraction_peaks(self, chunk: str, tag_base: str, limit: int) -> list[MatchPdf2Peak]:
        peaks = []
        peak_pattern = re.compile(
            r"(?P<d>(?:\d+\.\d{5}|\.\d{6}))\s*(?P<intensity>\d{1,3})"
            r"(?:\s+(?P<h>-?\d+)\s+(?P<k>-?\d+)\s+(?P<l>-?\d+))?"
        )
        for part in chunk.split(tag_base)[1:]:
            marker = part[:1]
            if marker not in {"G", "I"}:
                continue
            payload = part[1:].strip()
            if not payload or payload[0] not in ".0123456789":
                continue
            for match in peak_pattern.finditer(payload):
                try:
                    d_spacing = float(match.group("d"))
                    intensity = float(match.group("intensity"))
                except ValueError:
                    continue
                if d_spacing <= 0 or intensity <= 0:
                    continue
                peaks.append(
                    MatchPdf2Peak(
                        d_spacing=d_spacing,
                        intensity=min(intensity, 100.0),
                        h=match.group("h") or "",
                        k=match.group("k") or "",
                        l=match.group("l") or "",
                    )
                )
                if len(peaks) >= limit:
                    return peaks
        return peaks

    def _tag_parts(self, chunk: str, tag_base: str) -> list[tuple[str, str]]:
        parts = []
        for part in chunk.split(tag_base)[1:]:
            marker = part[:1]
            if not marker:
                continue
            parts.append((marker, part[1:]))
        return parts

    def _parse_space_group(self, parts: list[tuple[str, str]]) -> tuple[str, str]:
        for marker, payload in parts:
            if marker not in {"2", "3"}:
                continue
            tokens = payload.split()
            if len(tokens) < 2:
                continue
            if not re.match(r"^[A-Za-z0-9/\-]+$", tokens[0]):
                continue
            if not re.match(r"^\d{1,3}[A-Za-z]?$", tokens[1]):
                continue
            return tokens[0], tokens[1]
        return "", ""

    def _parse_cell(self, parts: list[tuple[str, str]]) -> dict[str, float] | None:
        for preferred_marker in ("D", "C"):
            for marker, payload in parts:
                if marker != preferred_marker:
                    continue
                values = [float(item) for item in re.findall(r"(?<![A-Za-z])[-+]?\d+\.\d+", payload)]
                if len(values) < 6:
                    continue
                cell = {
                    "a": values[0],
                    "b": values[1],
                    "c": values[2],
                    "alpha": values[3],
                    "beta": values[4],
                    "gamma": values[5],
                }
                if len(values) >= 7 and values[6] > 20:
                    cell["volume"] = values[6]
                return cell
        return None

    def _read_summary(self) -> list[MatchPdf2Entry]:
        entries = []
        for raw in self.summary_path.read_bytes().split(b"\x00"):
            text = raw.decode("latin1", errors="ignore").strip()
            if not text:
                continue
            entry = self._parse_summary_record(text)
            if entry is not None:
                entries.append(entry)
        return entries

    def _parse_summary_record(self, text: str) -> MatchPdf2Entry | None:
        match = re.search(r"\s+(\d{1,2})-\s*(\d{1,5})\s*([A-Za-z]*)\s*$", text)
        if not match:
            return None
        prefix = text[: match.start()].rstrip()
        set_no = int(match.group(1))
        card_no = int(match.group(2))
        quality = match.group(3).strip()
        chemical_name = ""
        name_text = prefix
        if "/" in prefix:
            chemical_name, name_text = (part.strip() for part in prefix.split("/", 1))
        name, formula = self._split_name_formula(name_text)
        source_prefix = "01" if "C" in quality else "00"
        return MatchPdf2Entry(
            entry_id=f"{source_prefix}-{set_no:03d}-{card_no:04d}",
            formula=formula,
            name=name,
            chemical_name=chemical_name,
            quality=quality,
        )

    def _split_name_formula(self, text: str) -> tuple[str, str]:
        parts = re.split(r"\s{2,}", text.strip())
        if len(parts) > 1:
            formula = parts[-1].strip()
            if len(formula_elements(formula)) >= 1 and any(char.isdigit() for char in formula):
                return " ".join(part.strip() for part in parts[:-1] if part.strip()), formula
        formula_start = self._formula_start(text)
        if formula_start is None:
            return text.strip(), ""
        return text[:formula_start].strip(), text[formula_start:].strip()

    def _formula_start(self, text: str) -> int | None:
        matches = list(re.finditer(r"(?<![a-z])(?:[A-Z][a-z]?|\*)[0-9A-Za-z().,+\-!/\[\] ]*$", text.strip()))
        for match in reversed(matches):
            fragment = match.group(0).strip()
            if len(formula_elements(fragment)) >= 1 and any(char.isdigit() for char in fragment):
                return match.start()
        return None
