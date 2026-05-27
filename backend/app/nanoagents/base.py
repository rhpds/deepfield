"""Base protocol for nano-agent filters."""

from typing import List, Protocol, runtime_checkable

from app.domain.models import FilterDecision, NormalizedSignal


@runtime_checkable
class NanoAgent(Protocol):
    name: str

    def filter(self, signals: List[NormalizedSignal]) -> List[FilterDecision]: ...
