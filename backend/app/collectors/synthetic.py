"""Synthetic collector — wraps SyntheticFleetGenerator as a Collector."""

from typing import List, Optional, Tuple

from app.domain.models import ClusterRef, RawSignal
from app.generators.synthetic import SyntheticFleetGenerator


class SyntheticCollector:
    def __init__(self, profile: str = "tiny", seed: int = 42, **overrides):
        self.generator = SyntheticFleetGenerator(profile, seed, **overrides)

    def collect(self) -> Tuple[List[ClusterRef], List[RawSignal]]:
        return self.generator.generate()
