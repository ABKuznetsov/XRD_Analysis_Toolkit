from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import sqlite3
import time
import re

from xrd_finder.io.cif_loader import create_phase_from_cif
from xrd_finder.services.cache_paths import default_phase_cache_root
from xrd_finder.services.cod_online_service import CodEntry, CodOnlineService, formula_elements


DEFAULT_CACHE_ROOT = default_phase_cache_root()


@dataclass(slots=True)
class CachedPhaseEntry:
    source: str
    entry_id: str
    formula: str = ""
    name: str = ""
    spacegroup: str = ""
    source_text: str = ""
    cif_path: str = ""
    a: float | None = None
    b: float | None = None
    c: float | None = None
    alpha: float | None = None
    beta: float | None = None
    gamma: float | None = None
    volume: float | None = None
    atoms_json: str = ""

    @property
    def cached(self) -> bool:
        return bool(self.cif_path)


class LocalPhaseCache:
    def __init__(self, root: str | Path = DEFAULT_CACHE_ROOT) -> None:
        self.root = Path(root)
        self.cif_dir = self.root / "cif"
        self.index_path = self.root / "index.sqlite"
        self.cif_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def status_row(self) -> list[str]:
        cached = self.cached_count()
        size = sum(path.stat().st_size for path in self.cif_dir.glob("*.cif") if path.is_file())
        return [
            "Local phase cache",
            "Ready",
            f"{cached} cached CIF files",
            str(cached),
            f"{size / (1024 * 1024):.1f}",
            "sqlite+cif",
            str(self.root),
        ]

    def cached_count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("select count(*) from phases where cif_path != ''").fetchone()[0])

    def search_is_fresh(self, source: str, query_key: str, max_age_seconds: float = 7 * 24 * 60 * 60) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "select updated_at from search_cache where source = ? and query_key = ?",
                (source, query_key),
            ).fetchone()
        if not row:
            return False
        return (time.time() - float(row["updated_at"])) < max_age_seconds

    def mark_search(self, source: str, query_key: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                insert into search_cache(source, query_key, updated_at)
                values(?, ?, ?)
                on conflict(source, query_key) do update set updated_at = excluded.updated_at
                """,
                (source, query_key, time.time()),
            )

    def upsert_cod_entries(self, entries: list[CodEntry]) -> None:
        with self._connect() as connection:
            for entry in entries:
                self._upsert(
                    connection,
                    CachedPhaseEntry(
                        source="COD",
                        entry_id=entry.cod_id,
                        formula=entry.formula,
                        name=entry.name or entry.mineral,
                        spacegroup=entry.spacegroup,
                        source_text=entry.source,
                    ),
                    keep_cif=True,
                )

    def upsert_materials_project_entries(self, entries) -> None:
        with self._connect() as connection:
            for entry in entries:
                self._upsert(
                    connection,
                    CachedPhaseEntry(
                        source="MP",
                        entry_id=entry.material_id,
                        formula=entry.formula,
                        name=entry.name or entry.formula,
                        spacegroup=entry.spacegroup,
                        source_text=entry.energy_above_hull,
                    ),
                    keep_cif=True,
                )

    def upsert_computational_entries(self, entries) -> None:
        with self._connect() as connection:
            for entry in entries:
                self._upsert(
                    connection,
                    CachedPhaseEntry(
                        source=entry.source,
                        entry_id=entry.entry_id,
                        formula=entry.formula,
                        name=entry.name or entry.formula,
                        spacegroup=entry.spacegroup,
                        source_text=entry.note,
                    ),
                    keep_cif=True,
                )

    def search(
        self,
        text: str = "",
        elements: list[str] | None = None,
        excluded_elements: list[str] | None = None,
        sources: list[str] | None = None,
        limit: int = 100,
    ) -> list[CachedPhaseEntry]:
        required = {element.strip() for element in elements or [] if element.strip()}
        excluded = {element.strip() for element in excluded_elements or [] if element.strip()}
        allowed_sources = {source.strip() for source in sources or [] if source.strip()}
        text = text.strip().lower()
        where = ["1 = 1"]
        params: list[object] = []
        if allowed_sources:
            placeholders = ", ".join("?" for _ in allowed_sources)
            where.append(f"source in ({placeholders})")
            params.extend(sorted(allowed_sources))
        for element in sorted(required):
            where.append("' ' || elements || ' ' like ?")
            params.append(f"% {element} %")
        for element in sorted(excluded):
            where.append("' ' || elements || ' ' not like ?")
            params.append(f"% {element} %")
        if text:
            like_text = f"%{text}%"
            compact_formula = self._formula_key(text)
            where.append(
                "("
                "lower(entry_id) like ? or "
                "lower(formula) like ? or "
                "lower(name) like ? or "
                "lower(spacegroup) like ? or "
                "formula_key like ?"
                ")"
            )
            params.extend([like_text, like_text, like_text, like_text, f"%{compact_formula}%"])
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                select source, entry_id, formula, name, spacegroup, source_text, cif_path, elements,
                       a, b, c, alpha, beta, gamma, volume, atoms_json
                from phases
                where {" and ".join(where)}
                order by updated_at desc
                limit ?
                """,
                (*params, max(limit * 5, limit)),
            ).fetchall()
        results = []
        seen = set()
        for row in rows:
            dedupe_key = self._dedupe_key(row)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            results.append(self._row_to_entry(row))
            if len(results) >= limit:
                break
        return results

    def download_cod_entry(self, entry: CodEntry, cod_online: CodOnlineService) -> Path:
        self.upsert_cod_entries([entry])
        cif_path = cod_online.download_cif(entry.cod_id, self.cif_dir)
        self.index_cif(cif_path, source="COD", entry_id=entry.cod_id, fallback=entry)
        return cif_path

    def add_user_cif(self, cif_path: str | Path) -> CachedPhaseEntry:
        source_path = Path(cif_path)
        user_dir = self.root / "user_cif"
        user_dir.mkdir(parents=True, exist_ok=True)
        target_path = user_dir / source_path.name
        if target_path.exists() and target_path.resolve() != source_path.resolve():
            target_path = user_dir / f"{source_path.stem}_{int(time.time())}{source_path.suffix}"
        if target_path.resolve() != source_path.resolve():
            shutil.copy2(source_path, target_path)
        entry_id = target_path.stem
        self.index_cif(target_path, source="USER", entry_id=entry_id)
        entry = self.get("USER", entry_id)
        if entry is None:
            return CachedPhaseEntry(source="USER", entry_id=entry_id, name=entry_id, cif_path=str(target_path))
        return entry

    def cif_path(self, source: str, entry_id: str) -> Path | None:
        with self._connect() as connection:
            row = connection.execute(
                "select cif_path from phases where source = ? and entry_id = ?",
                (source, entry_id),
            ).fetchone()
        if not row or not row["cif_path"]:
            return None
        path = Path(row["cif_path"])
        return path if path.exists() else None

    def cif_path_for_cache_id(self, cache_id: str) -> Path | None:
        if ":" in cache_id:
            source, entry_id = cache_id.split(":", 1)
            return self.cif_path(source, entry_id)
        return self.cif_path("COD", cache_id)

    def get(self, source: str, entry_id: str) -> CachedPhaseEntry | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                select source, entry_id, formula, name, spacegroup, source_text, cif_path, elements,
                       a, b, c, alpha, beta, gamma, volume, atoms_json
                from phases
                where source = ? and entry_id = ?
                """,
                (source, entry_id),
            ).fetchone()
        return self._row_to_entry(row) if row else None

    def build_index(self) -> int:
        count = 0
        for cif_path in self.cif_dir.glob("*.cif"):
            entry_id = cif_path.stem
            self.index_cif(cif_path, source="COD", entry_id=entry_id)
            count += 1
        user_dir = self.root / "user_cif"
        for cif_path in user_dir.glob("*.cif") if user_dir.exists() else []:
            entry_id = cif_path.stem
            self.index_cif(cif_path, source="USER", entry_id=entry_id)
            count += 1
        return count

    def clear_user_library(self) -> None:
        self._clear_sources(["USER"])
        self._remove_cache_dirs(["user_cif"])

    def clear_cod_cache(self) -> None:
        self._clear_sources(["COD"])
        self._remove_cache_dirs(["cif", "cod_bulk_cif", "downloads"])
        self.cif_dir.mkdir(parents=True, exist_ok=True)

    def clear_materials_project_cache(self) -> None:
        self._clear_sources(["MP"])
        self._remove_cache_dirs(["materials_project_cif"])

    def clear_aflow_cache(self) -> None:
        self._clear_sources(["AFLOW"])
        self._remove_cache_dirs(["aflow_cif"])

    def clear_oqmd_cache(self) -> None:
        self._clear_sources(["OQMD"])
        self._remove_cache_dirs(["oqmd_cif"])

    def index_cif_folder(self, folder: str | Path, source: str = "COD") -> int:
        root = Path(folder)
        if not root.exists():
            raise FileNotFoundError(f"Folder does not exist: {root}")
        count = 0
        for cif_path in root.rglob("*.cif"):
            self.index_cif(cif_path, source=source, entry_id=cif_path.stem)
            count += 1
        return count

    def index_cif(
        self,
        cif_path: str | Path,
        source: str,
        entry_id: str,
        fallback: CodEntry | None = None,
    ) -> None:
        cif_path = Path(cif_path)
        try:
            _phase, structure = create_phase_from_cif(cif_path)
            formula = self._best_formula(structure.formula, fallback.formula if fallback else "")
            name = self._best_name(structure.name, fallback.name if fallback else "", formula, entry_id)
            spacegroup = structure.space_group or (fallback.spacegroup if fallback else "")
            source_text = (fallback.source if fallback else "") or str(structure.metadata.get("publication", "") or "")
            cell = structure.cell
            atoms_json = self._atoms_to_json(structure)
        except Exception:
            formula = fallback.formula if fallback else ""
            name = fallback.name if fallback else cif_path.stem
            spacegroup = fallback.spacegroup if fallback else ""
            source_text = fallback.source if fallback else ""
            cell = None
            atoms_json = ""
        entry = CachedPhaseEntry(
            source=source,
            entry_id=entry_id,
            formula=formula,
            name=name,
            spacegroup=spacegroup,
            source_text=source_text,
            cif_path=str(cif_path),
            a=getattr(cell, "a", None),
            b=getattr(cell, "b", None),
            c=getattr(cell, "c", None),
            alpha=getattr(cell, "alpha", None),
            beta=getattr(cell, "beta", None),
            gamma=getattr(cell, "gamma", None),
            volume=getattr(cell, "volume", None),
            atoms_json=atoms_json,
        )
        with self._connect() as connection:
            self._upsert(connection, entry, keep_cif=False)

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                create table if not exists phases (
                    source text not null,
                    entry_id text not null,
                    formula text not null default '',
                    name text not null default '',
                    spacegroup text not null default '',
                    source_text text not null default '',
                    elements text not null default '',
                    formula_key text not null default '',
                    cif_path text not null default '',
                    a real,
                    b real,
                    c real,
                    alpha real,
                    beta real,
                    gamma real,
                    volume real,
                    atoms_json text not null default '',
                    updated_at real not null,
                    primary key (source, entry_id)
                )
                """
            )
            connection.execute(
                """
                create table if not exists search_cache (
                    source text not null,
                    query_key text not null,
                    updated_at real not null,
                    primary key (source, query_key)
                )
                """
            )
            existing = {row[1] for row in connection.execute("pragma table_info(phases)").fetchall()}
            for column in ["a", "b", "c", "alpha", "beta", "gamma", "volume"]:
                if column not in existing:
                    connection.execute(f"alter table phases add column {column} real")
            if "atoms_json" not in existing:
                connection.execute("alter table phases add column atoms_json text not null default ''")
            if "formula_key" not in existing:
                connection.execute("alter table phases add column formula_key text not null default ''")
                connection.execute("update phases set formula_key = lower(replace(formula, ' ', '')) where formula_key = ''")
            connection.execute("create index if not exists idx_phases_source_updated on phases(source, updated_at desc)")
            connection.execute("create index if not exists idx_phases_formula_key on phases(formula_key)")
            connection.execute("create index if not exists idx_phases_elements on phases(elements)")

    def _connect(self) -> sqlite3.Connection:
        self.root.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.index_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _clear_sources(self, sources: list[str]) -> None:
        if not sources:
            return
        placeholders = ", ".join("?" for _ in sources)
        with self._connect() as connection:
            connection.execute(f"delete from phases where source in ({placeholders})", sources)
            connection.execute(f"delete from search_cache where source in ({placeholders})", sources)

    def _remove_cache_dirs(self, names: list[str]) -> None:
        root = self.root.resolve()
        for name in names:
            path = (self.root / name).resolve()
            if path == root or root not in path.parents:
                continue
            if path.exists():
                shutil.rmtree(path)

    def _upsert(self, connection: sqlite3.Connection, entry: CachedPhaseEntry, keep_cif: bool) -> None:
        old_cif = ""
        if keep_cif:
            row = connection.execute(
                "select cif_path from phases where source = ? and entry_id = ?",
                (entry.source, entry.entry_id),
            ).fetchone()
            old_cif = row["cif_path"] if row else ""
        cif_path = old_cif or entry.cif_path
        connection.execute(
            """
            insert into phases(
                source, entry_id, formula, name, spacegroup, source_text, elements, formula_key, cif_path,
                a, b, c, alpha, beta, gamma, volume, atoms_json, updated_at
            )
            values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(source, entry_id) do update set
                formula = excluded.formula,
                name = excluded.name,
                spacegroup = excluded.spacegroup,
                source_text = excluded.source_text,
                elements = excluded.elements,
                formula_key = excluded.formula_key,
                cif_path = excluded.cif_path,
                a = excluded.a,
                b = excluded.b,
                c = excluded.c,
                alpha = excluded.alpha,
                beta = excluded.beta,
                gamma = excluded.gamma,
                volume = excluded.volume,
                atoms_json = excluded.atoms_json,
                updated_at = excluded.updated_at
            """,
            (
                entry.source,
                entry.entry_id,
                entry.formula,
                entry.name,
                entry.spacegroup,
                entry.source_text,
                " ".join(sorted(formula_elements(entry.formula))),
                self._formula_key(entry.formula),
                cif_path,
                entry.a,
                entry.b,
                entry.c,
                entry.alpha,
                entry.beta,
                entry.gamma,
                entry.volume,
                entry.atoms_json,
                time.time(),
            ),
        )

    def _row_to_entry(self, row: sqlite3.Row) -> CachedPhaseEntry:
        return CachedPhaseEntry(
            source=row["source"],
            entry_id=row["entry_id"],
            formula=row["formula"],
            name=row["name"],
            spacegroup=row["spacegroup"],
            source_text=row["source_text"],
            cif_path=row["cif_path"],
            a=row["a"],
            b=row["b"],
            c=row["c"],
            alpha=row["alpha"],
            beta=row["beta"],
            gamma=row["gamma"],
            volume=row["volume"],
            atoms_json=row["atoms_json"],
        )

    def _dedupe_key(self, row: sqlite3.Row) -> tuple:
        cell_key = self._cell_key(row)
        if cell_key is None:
            return ("unique", row["source"], row["entry_id"])
        return (
            self._normalize_formula(row["formula"]),
            self._normalize_text(row["spacegroup"]),
            cell_key,
        )

    def _cell_key(self, row: sqlite3.Row) -> tuple | None:
        values = [row["a"], row["b"], row["c"], row["alpha"], row["beta"], row["gamma"]]
        if any(value is None for value in values):
            return None
        lengths = tuple(round(float(value), 2) for value in values[:3])
        angles = tuple(round(float(value), 1) for value in values[3:])
        volume = row["volume"]
        volume_key = round(float(volume), 1) if volume is not None else None
        return lengths + angles + (volume_key,)

    def _normalize_formula(self, formula: str) -> str:
        tokens = re.findall(r"([A-Z][a-z]?)([0-9.]+)?", formula or "")
        if not tokens:
            return self._normalize_text(formula)
        parts = []
        for element, amount in sorted(tokens):
            amount_text = amount.rstrip("0").rstrip(".") if amount else "1"
            parts.append(f"{element}{amount_text}")
        return " ".join(parts)

    def _formula_key(self, formula: str) -> str:
        tokens = re.findall(r"([A-Z][a-z]?)([0-9.]+)?", formula or "")
        if not tokens:
            return re.sub(r"\s+", "", (formula or "").lower())
        return "".join(f"{element.lower()}{amount}" for element, amount in tokens)

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()

    def _best_formula(self, structure_formula: str, fallback_formula: str) -> str:
        return fallback_formula.strip() or structure_formula.strip()

    def _best_name(self, structure_name: str, fallback_name: str, formula: str, entry_id: str) -> str:
        fallback_name = (fallback_name or "").strip()
        if fallback_name:
            return fallback_name
        structure_name = (structure_name or "").strip()
        if structure_name and self._normalize_formula(structure_name) != self._normalize_formula(formula):
            return structure_name
        return formula.strip() or entry_id

    def _atoms_to_json(self, structure) -> str:
        atoms = []
        for atom in getattr(structure, "atoms", []) or []:
            atoms.append(
                {
                    "label": atom.label,
                    "element": atom.element,
                    "x": atom.x,
                    "y": atom.y,
                    "z": atom.z,
                    "occupancy": atom.occupancy,
                    "biso": atom.biso,
                    "uiso": atom.uiso,
                    "wyckoff": atom.wyckoff,
                    "multiplicity": atom.multiplicity,
                }
            )
        return json.dumps(atoms, ensure_ascii=True, separators=(",", ":"))
