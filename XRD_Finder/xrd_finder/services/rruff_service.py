from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import sqlite3
import time
from urllib.request import urlopen
from xrd_finder.services.network import create_ssl_context
from zipfile import ZipFile

from xrd_finder.services.cod_online_service import formula_elements


RRUFF_POWDER_XY_PROCESSED_URL = "https://www.rruff.net/zipped_data_files/powder/XY_Processed.zip"


@dataclass(slots=True)
class RruffEntry:
    rruff_id: str
    name: str = ""
    formula: str = ""
    path: str = ""
    source_text: str = ""


class RruffService:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.archive_path = self.root / "XY_Processed.zip"
        self.powder_dir = self.root / "powder_xy_processed"
        self.index_path = self.root / "index.sqlite"
        self.root.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()
        self._ssl_context = self._create_ssl_context()

    def status_row(self) -> list[str]:
        count = self.indexed_count()
        archive_size = self.archive_path.stat().st_size if self.archive_path.exists() else 0
        data_size = sum(path.stat().st_size for path in self.powder_dir.rglob("*") if path.is_file()) if self.powder_dir.exists() else 0
        return [
            "RRUFF powder",
            "Ready" if count else "Not indexed",
            f"{count} reference patterns",
            str(count),
            f"{(archive_size + data_size) / (1024 * 1024):.1f}",
            "local XY",
            str(self.root),
        ]

    def indexed_count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("select count(*) from rruff_patterns").fetchone()[0])

    def download_powder_archive(
        self,
        url: str = RRUFF_POWDER_XY_PROCESSED_URL,
        timeout: float = 120.0,
    ) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp_path = self.archive_path.with_suffix(".zip.part")
        with urlopen(url, timeout=timeout, context=self._ssl_context) as response:
            with tmp_path.open("wb") as handle:
                shutil.copyfileobj(response, handle)
        tmp_path.replace(self.archive_path)
        return self.archive_path

    def update_powder_database(
        self,
        url: str = RRUFF_POWDER_XY_PROCESSED_URL,
        remove_archive: bool = True,
    ) -> int:
        self.download_powder_archive(url)
        count = self.index_powder_archive()
        if remove_archive and self.archive_path.exists():
            self.archive_path.unlink()
        return count

    def index_powder_archive(self) -> int:
        if not self.archive_path.exists():
            raise FileNotFoundError(f"RRUFF archive not found: {self.archive_path}")
        self.powder_dir.mkdir(parents=True, exist_ok=True)
        extracted = 0
        with ZipFile(self.archive_path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                member_path = Path(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    continue
                if not self._looks_like_xy_file(member_path.name):
                    continue
                target_path = self.powder_dir / member_path
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target_path.open("wb") as target:
                    shutil.copyfileobj(source, target)
                extracted += 1
        return self.index_powder_folder()

    def index_powder_folder(self) -> int:
        if not self.powder_dir.exists():
            return 0
        count = 0
        with self._connect() as connection:
            connection.execute("delete from rruff_patterns")
            for path in self.powder_dir.rglob("*"):
                if not path.is_file() or not self._looks_like_xy_file(path.name):
                    continue
                entry = self._entry_from_file(path)
                if not entry.rruff_id:
                    continue
                self._upsert(connection, entry)
                count += 1
        return count

    def clear(self) -> None:
        if self.archive_path.exists():
            self.archive_path.unlink()
        if self.powder_dir.exists():
            shutil.rmtree(self.powder_dir)
        self._ensure_schema()
        connection = self._connect()
        try:
            connection.execute("delete from rruff_patterns")
            connection.commit()
        finally:
            connection.close()

    def search(
        self,
        text: str = "",
        elements: list[str] | None = None,
        excluded_elements: list[str] | None = None,
        limit: int = 100,
    ) -> list[RruffEntry]:
        required = {element.strip() for element in elements or [] if element.strip()}
        excluded = {element.strip() for element in excluded_elements or [] if element.strip()}
        text = text.strip().lower()
        with self._connect() as connection:
            rows = connection.execute(
                """
                select rruff_id, name, formula, path, source_text, elements
                from rruff_patterns
                order by updated_at desc
                """
            ).fetchall()
        results = []
        for row in rows:
            row_elements = set((row["elements"] or "").split())
            if required and not required.issubset(row_elements):
                continue
            if excluded and row_elements & excluded:
                continue
            haystack = " ".join([row["rruff_id"], row["name"], row["formula"], row["source_text"]]).lower()
            if text and text not in haystack:
                continue
            results.append(
                RruffEntry(
                    rruff_id=row["rruff_id"],
                    name=row["name"],
                    formula=row["formula"],
                    path=row["path"],
                    source_text=row["source_text"],
                )
            )
            if len(results) >= limit:
                break
        return results

    def pattern_path(self, rruff_id: str) -> Path | None:
        with self._connect() as connection:
            row = connection.execute(
                "select path from rruff_patterns where rruff_id = ?",
                (rruff_id,),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    """
                    select path from rruff_patterns
                    where rruff_id like ? or path like ?
                    order by updated_at desc
                    limit 1
                    """,
                    (f"{rruff_id}%", f"%{rruff_id}%"),
                ).fetchone()
        if not row or not row["path"]:
            return None
        path = Path(row["path"])
        return path if path.exists() else None

    def _entry_from_file(self, path: Path) -> RruffEntry:
        name = self._mineral_name_from_path(path)
        rruff_id = self._rruff_id_from_path(path)
        source_text = ""
        formula = ""
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:8000]
        except Exception:
            text = ""
        if text:
            formula = self._metadata_value(text, ["formula", "chemistry", "ideal chemistry"])
            source_text = self._metadata_value(text, ["source", "description", "owner"])
            if not name:
                name = self._metadata_value(text, ["mineral", "name"])
            if not rruff_id:
                match = re.search(r"\bR[0-9]{5,7}\b", text)
                rruff_id = match.group(0) if match else ""
        return RruffEntry(
            rruff_id=rruff_id,
            name=name or rruff_id,
            formula=formula,
            path=str(path),
            source_text=source_text or "RRUFF measured powder pattern",
        )

    def _mineral_name_from_path(self, path: Path) -> str:
        stem = path.stem
        first = re.split(r"__+", stem)[0]
        return first.replace("_", " ").strip()

    def _rruff_id_from_path(self, path: Path) -> str:
        match = re.search(r"(?:^|[^A-Za-z0-9])(R[0-9]{5,7}(?:-[0-9]+)?)(?=$|[^A-Za-z0-9])", path.name)
        return match.group(1) if match else path.stem

    def _metadata_value(self, text: str, keys: list[str]) -> str:
        for key in keys:
            pattern = rf"(?im)^\s*[#;!/\s]*{re.escape(key)}\s*[:=]\s*(.+?)\s*$"
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        return ""

    def _looks_like_xy_file(self, name: str) -> bool:
        lowered = name.lower()
        if lowered.startswith(("readme", "license")):
            return False
        return lowered.endswith((".xy", ".txt", ".dat", ".csv"))

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                create table if not exists rruff_patterns (
                    rruff_id text primary key,
                    name text not null default '',
                    formula text not null default '',
                    path text not null default '',
                    source_text text not null default '',
                    elements text not null default '',
                    updated_at real not null
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        self.root.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.index_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _upsert(self, connection: sqlite3.Connection, entry: RruffEntry) -> None:
        connection.execute(
            """
            insert into rruff_patterns(rruff_id, name, formula, path, source_text, elements, updated_at)
            values(?, ?, ?, ?, ?, ?, ?)
            on conflict(rruff_id) do update set
                name = excluded.name,
                formula = excluded.formula,
                path = excluded.path,
                source_text = excluded.source_text,
                elements = excluded.elements,
                updated_at = excluded.updated_at
            """,
            (
                entry.rruff_id,
                entry.name,
                entry.formula,
                entry.path,
                entry.source_text,
                " ".join(sorted(formula_elements(entry.formula))),
                time.time(),
            ),
        )

    def _create_ssl_context(self):
        return create_ssl_context()
