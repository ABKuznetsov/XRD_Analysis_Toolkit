from __future__ import annotations

import math
import re
from xrd_finder.services.cod_online_service import formula_elements
from xrd_finder.services.local_phase_cache import DERIVED_CACHE_VERSION


def normalize_candidate_row(row: list[str]) -> list[str]:
    if len(row) >= 10:
        return [
            row[1],
            row[2],
            row[3],
            row[4],
            "",
            row[8],
            "",
            row[9],
        ]
    if len(row) >= 8:
        return row[:8]
    if len(row) == 7:
        return [row[0], row[1], row[2], row[3], row[4], row[5], "", row[6]]
    if len(row) == 6:
        return [row[0], row[1], row[2], row[3], "", row[4], "", row[5]]
    if len(row) >= 5:
        return ["", "", "", row[4], "", "", "", ""]
    padded = list(row) + [""] * 8
    return padded[:8]



class CandidateRowFormatter:
    """Local card formatting shared by search and the isolated Gain reader."""

    def __init__(self, local_phase_cache):
        self.local_phase_cache = local_phase_cache

    def cache_rows(self, entries) -> list[list[str]]:
        return [
            [
                entry.source,
                entry.entry_id,
                self.display_formula(entry.formula),
                self.phase_display_name(entry.source, entry.formula, entry.name),
                getattr(entry, "spacegroup", ""),
                "",
                self.display_iic(getattr(entry, "iic", None), getattr(entry, "derived_version", 0), getattr(entry, "iic_method", "")),
            ]
            for entry in entries
        ]

    def phase_display_name(self, source, formula, name="") -> str:
        if str(source).strip().upper() == 'MP' and formula:
            return self.display_formula(formula)
        return name or self.display_formula(formula)

    def dedupe_candidate_rows(self, rows: list[list[str]]) -> list[list[str]]:
        unique = []
        seen = set()
        for row in rows:
            normalized = normalize_candidate_row(row)
            key = ((normalized[0].strip().upper(), normalized[1].strip())
                   if normalized[0].strip() and normalized[1].strip()
                   else tuple(value.strip().lower() for value in normalized[:4]))
            if key in seen:
                continue
            seen.add(key)
            unique.append(normalized)
        return unique

    def filter_candidate_rows_by_excluded_elements(
        self,
        rows: list[list[str]],
        options,
    ) -> list[list[str]]:
        filtered = []
        for row in rows:
            normalized = normalize_candidate_row(row)
            formula = normalized[2] if len(normalized) > 2 else ""
            if self.candidate_formula_allowed(formula, options, source=normalized[0]):
                filtered.append(row)
        return filtered

    @staticmethod
    def candidate_formula_allowed(formula: str, options, *, source='') -> bool:
        if not formula:
            return True
        excluded = set(options.excluded_elements)
        required = {element.strip() for element in options.required_elements if element.strip()}
        allowed = required | {element.strip() for element in options.optional_elements if element.strip()}
        elements = formula_elements(formula)
        from xrd_finder.services.source_registry import ORGANIC_FRAMEWORK_SOURCES
        allow_organic=getattr(options,'allow_organic',None)
        material_allowed=(bool(allow_organic) if allow_organic is not None
                          and source in ORGANIC_FRAMEWORK_SOURCES and 'C' in elements
                          else options.material_class_allowed(formula))
        return (required.issubset(elements) and not elements.intersection(excluded)
                and (not getattr(options, 'restrict_to_selected_elements', True)
                     or not allowed or elements.issubset(allowed))
                and material_allowed)

    def display_formula(self, formula: str) -> str:
        parts = re.findall(r"[A-Z][a-z]?[0-9.]*", formula or "")
        return " ".join(parts) if parts else formula

    def display_iic(self, value, derived_version: int = DERIVED_CACHE_VERSION, method: str = "") -> str:
        if not self.local_phase_cache.calculated_iic.value_current(value, method):
            return ""
        if int(derived_version or 0) != DERIVED_CACHE_VERSION:
            return ""
        if value is None or value == "":
            return ""
        try:
            number = float(value)
        except (TypeError, ValueError):
            return ""
        if not math.isfinite(number) or number <= 0:
            return ""
        return f"~{number:.3g}"
