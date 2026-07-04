from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Event:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[Event], None]]] = defaultdict(list)

    def subscribe(self, event_name: str, callback: Callable[[Event], None]) -> None:
        self._subscribers[event_name].append(callback)

    def publish(self, event_name: str, **payload: Any) -> None:
        event = Event(name=event_name, payload=payload)
        for callback in list(self._subscribers.get(event_name, [])):
            callback(event)
