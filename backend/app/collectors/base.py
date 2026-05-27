"""Collector protocol for signal sources."""

from typing import List, Protocol, Tuple, runtime_checkable

from app.domain.models import ClusterRef, RawSignal


@runtime_checkable
class Collector(Protocol):
    def collect(self) -> Tuple[List[ClusterRef], List[RawSignal]]: ...
