from __future__ import annotations

from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QSettings


class StatusLike(Protocol):
    configured: bool
    label: str


class MatchPdf2Like(Protocol):
    def is_configured(self) -> bool: ...

    def status(self) -> StatusLike: ...


def database_summary_row(row: list[str]) -> list[str]:
    source = row[0] if len(row) > 0 else ""
    state = row[1] if len(row) > 1 else ""
    label = row[2] if len(row) > 2 else ""
    files = row[3] if len(row) > 3 else ""
    size = row[4] if len(row) > 4 else ""
    location = row[6] if len(row) > 6 else (row[3] if len(row) > 3 else "")
    details = label
    if files or size:
        suffix = ", ".join(part for part in [f"{files} files" if files else "", f"{size} MB" if size else ""] if part)
        details = f"{label} ({suffix})" if label else suffix
    return [source, state, details, location]


def user_phase_library_status_row(local_row: list[str]) -> list[str]:
    return [
        "User phase library",
        local_row[1],
        local_row[2],
        local_row[3],
        local_row[4],
        "sqlite+cif",
        local_row[6],
    ]


def match_pdf2_status_row(match_pdf2: MatchPdf2Like) -> list[str]:
    status = match_pdf2.status()
    return [
        "PDF-2",
        "Ready" if status.configured else "Not configured",
        status.label,
        str(getattr(status, "root", "")),
    ]


def source_states(settings: QSettings, match_pdf2: MatchPdf2Like) -> dict[str, bool]:
    return {
        "sources/user_library": bool(settings.value("sources/user_library", True, type=bool)),
        "sources/cod_local": bool(settings.value("sources/cod_local", True, type=bool)),
        "sources/cod_online": bool(settings.value("sources/cod_online", True, type=bool)),
        "sources/rruff": bool(settings.value("sources/rruff", False, type=bool)),
        "sources/match_pdf2": bool(settings.value("sources/match_pdf2", match_pdf2.is_configured(), type=bool)),
        "sources/aflow": bool(settings.value("sources/aflow", False, type=bool)),
        "sources/oqmd": bool(settings.value("sources/oqmd", False, type=bool)),
    }


def database_rows(
    user_library_row: list[str],
    rruff_row: list[str],
    match_pdf2_row: list[str],
    ccdc_status: StatusLike,
    aflow_label: str,
    oqmd_label: str,
    materials_project_status: StatusLike,
    local_cache_root: Path,
) -> list[list[str]]:
    return [
        database_summary_row(user_library_row),
        [
            "COD online",
            "Available",
            "Download CIF files to the user library",
            "crystallography.net/cod",
        ],
        [
            "COD local/bulk",
            "Available",
            "Index a downloaded COD CIF folder or ZIP archive",
            str(local_cache_root),
        ],
        database_summary_row(rruff_row),
        match_pdf2_row,
        [
            "CCDC / CSD",
            "Ready" if ccdc_status.configured else "Not configured",
            ccdc_status.label,
            "CSD Python API / ccdc.cam.ac.uk",
        ],
        [
            "AFLOW",
            "Available",
            aflow_label,
            "aflow.org",
        ],
        [
            "OQMD",
            "Available",
            oqmd_label,
            "oqmd.org",
        ],
        [
            "Materials Project",
            "Ready" if materials_project_status.configured else "Not configured",
            materials_project_status.label,
            "user API key",
        ],
    ]
