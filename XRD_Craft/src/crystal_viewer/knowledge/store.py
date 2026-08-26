from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from crystal_viewer.knowledge.model import (
    InterpretationChanges,
    KnowledgePreset,
    MotifFingerprint,
    PeriodicBondChange,
)


class PresetConflictError(ValueError):
    """Raised when an imported UUID already exists in the local library."""


class UnsupportedSchemaError(ValueError):
    """Raised when a preset belongs to an unsupported future schema."""


@dataclass(frozen=True, slots=True)
class KnowledgeWarning:
    code: str
    message: str
    path: Path


def _freeze(value):
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, dict):
        return {key: _freeze(item) for key, item in value.items()}
    return value


def _bond_change(payload: dict[str, object]) -> PeriodicBondChange:
    return PeriodicBondChange(
        first=int(payload["first"]),
        second=int(payload["second"]),
        image=tuple(int(value) for value in payload["image"]),  # type: ignore[arg-type]
        distance=float(payload["distance"]),
    )


def _decode_preset(payload: object) -> KnowledgePreset:
    if not isinstance(payload, dict):
        raise ValueError("preset root must be a JSON object")
    schema_version = payload.get("schema_version")
    if schema_version != 1:
        raise UnsupportedSchemaError(f"unsupported schema version: {schema_version!r}")
    raw_changes = payload["changes"]
    if not isinstance(raw_changes, dict):
        raise ValueError("changes must be a JSON object")
    changes = InterpretationChanges(
        name=raw_changes.get("name"),
        vocabulary=raw_changes.get("vocabulary"),
        member_polyhedron_ids=tuple(str(value) for value in raw_changes.get("member_polyhedron_ids", ())),
        role_overrides=tuple(
            (int(item[0]), str(item[1])) for item in raw_changes.get("role_overrides", ())
        ),
        bond_additions=tuple(_bond_change(item) for item in raw_changes.get("bond_additions", ())),
        bond_removals=tuple(_bond_change(item) for item in raw_changes.get("bond_removals", ())),
    )
    raw_fingerprint = payload.get("fingerprint")
    fingerprint = None
    if raw_fingerprint is not None:
        if not isinstance(raw_fingerprint, dict):
            raise ValueError("fingerprint must be a JSON object")
        fingerprint = MotifFingerprint(
            algorithm=str(raw_fingerprint["algorithm"]),
            periodic_rank=int(raw_fingerprint["periodic_rank"]),
            nodes=tuple(_freeze(item) for item in raw_fingerprint["nodes"]),
            edges=tuple(_freeze(item) for item in raw_fingerprint["edges"]),
            topology_digest=str(raw_fingerprint.get("topology_digest", "")),
        )
    return KnowledgePreset(
        schema_version=1,
        id=str(payload["id"]),
        scope=str(payload["scope"]),  # type: ignore[arg-type]
        source_identity=str(payload["source_identity"]),
        analysis_method=str(payload["analysis_method"]),
        fingerprint=fingerprint,
        changes=changes,
        created_at=str(payload["created_at"]),
        modified_at=str(payload["modified_at"]),
        note=str(payload.get("note", "")),
        accepted_count=int(payload.get("accepted_count", 0)),
        dismissed_count=int(payload.get("dismissed_count", 0)),
    )


def _encoded(preset: KnowledgePreset) -> str:
    return json.dumps(asdict(preset), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


class KnowledgeStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @property
    def index_path(self) -> Path:
        return self.root.parent / "knowledge-index.json"

    def _path(self, preset: KnowledgePreset) -> Path:
        return self.root / preset.scope / f"{preset.id}.json"

    def _find(self, preset_id: str) -> Path | None:
        matches = [
            path
            for scope in ("local", "reusable")
            if (path := self.root / scope / f"{preset_id}.json").is_file()
        ]
        if len(matches) > 1:
            raise PresetConflictError(f"preset id exists in multiple scopes: {preset_id}")
        return matches[0] if matches else None

    def _write_index(self) -> None:
        presets, warnings = self.load_all()
        payload = {
            "schema_version": 1,
            "presets": [
                {"id": item.id, "scope": item.scope, "modified_at": item.modified_at}
                for item in presets
            ],
            "warning_count": len(warnings),
        }
        _atomic_write(
            self.index_path,
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        )

    def save(self, preset: KnowledgePreset) -> Path:
        existing = self._find(preset.id)
        target = self._path(preset)
        if existing is not None and existing != target:
            raise PresetConflictError(f"preset id already exists in {existing.parent.name}: {preset.id}")
        _atomic_write(target, _encoded(preset))
        self._write_index()
        return target

    def load_all(self) -> tuple[tuple[KnowledgePreset, ...], tuple[KnowledgeWarning, ...]]:
        presets: list[KnowledgePreset] = []
        warnings: list[KnowledgeWarning] = []
        for scope in ("local", "reusable"):
            directory = self.root / scope
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.json"), key=lambda item: item.name):
                try:
                    preset = _decode_preset(json.loads(path.read_text(encoding="utf-8")))
                    if preset.scope != scope:
                        raise ValueError(
                            f"preset scope {preset.scope!r} does not match directory {scope!r}"
                        )
                    presets.append(preset)
                except UnsupportedSchemaError as error:
                    warnings.append(KnowledgeWarning("unsupported-schema", str(error), path))
                except (KeyError, TypeError, ValueError, OSError, UnicodeError, json.JSONDecodeError) as error:
                    warnings.append(KnowledgeWarning("invalid-preset", str(error), path))
        presets.sort(key=lambda item: (item.scope, item.id))
        return tuple(presets), tuple(warnings)

    def delete(self, preset_id: str) -> bool:
        path = self._find(preset_id)
        if path is None:
            return False
        path.unlink()
        self._write_index()
        return True

    def export_preset(self, preset_id: str, destination: str | Path) -> Path:
        source = self._find(preset_id)
        if source is None:
            raise KeyError(preset_id)
        preset = _decode_preset(json.loads(source.read_text(encoding="utf-8")))
        target = Path(destination)
        if target.suffix.lower() != ".cbpreset":
            target = target.with_suffix(".cbpreset")
        _atomic_write(target, _encoded(preset))
        return target

    def import_preset(self, source: str | Path) -> KnowledgePreset:
        path = Path(source)
        preset = _decode_preset(json.loads(path.read_text(encoding="utf-8")))
        if self._find(preset.id) is not None:
            raise PresetConflictError(f"preset id already exists: {preset.id}")
        self.save(preset)
        return preset


__all__ = [
    "KnowledgeStore",
    "KnowledgeWarning",
    "PresetConflictError",
]
