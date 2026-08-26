from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from crystal_viewer.core.document import StructureDocument


@dataclass(slots=True)
class StructureCollection:
    max_compared: int = 4
    documents: dict[str, StructureDocument] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    visual_slots: dict[str, str] = field(default_factory=dict)
    compared_ids: list[str] = field(default_factory=list)

    def add(self, document: StructureDocument) -> None:
        if document.id not in self.documents:
            self.order.append(document.id)
        self.documents[document.id] = document

    def assign_visual(
        self,
        slot: Literal["A", "B"],
        document_id: str,
    ) -> None:
        if document_id not in self.documents:
            raise KeyError(document_id)
        self.visual_slots[slot] = document_id

    def visual_pair(self) -> tuple[StructureDocument, StructureDocument] | None:
        if "A" not in self.visual_slots or "B" not in self.visual_slots:
            return None
        return (
            self.documents[self.visual_slots["A"]],
            self.documents[self.visual_slots["B"]],
        )

    def set_compared(self, document_id: str, enabled: bool) -> None:
        if document_id not in self.documents:
            raise KeyError(document_id)
        if enabled and document_id not in self.compared_ids:
            if len(self.compared_ids) >= self.max_compared:
                words = {2: "two", 4: "four"}
                limit = words.get(self.max_compared, str(self.max_compared))
                raise ValueError(f"Detailed comparison accepts at most {limit} structures.")
            self.compared_ids.append(document_id)
        elif not enabled and document_id in self.compared_ids:
            self.compared_ids.remove(document_id)

    def compared_documents(self) -> tuple[StructureDocument, ...]:
        return tuple(self.documents[document_id] for document_id in self.compared_ids)
